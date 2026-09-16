import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import TestCase, override_settings

from . import ai_chat, business_info, company_knowledge, doc_extract, privacy, request_router
from .middleware import CanonicalHostMiddleware, PublicAssetCacheMiddleware
from .models import AIConversation, AIMessage, AINote, Cart, Category, Product, PWASettings, StoreProfile
from .views import AI_CURRENT_CONVERSATION_SESSION_KEY, _ai_document_instruction


class AIConversationPersistenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='chat-persistence@example.com',
            email='chat-persistence@example.com',
            password='test-password-123',
        )
        StoreProfile.objects.create(user=self.user, phone='9999999999')

    def test_open_conversation_is_restored_on_authenticated_refresh(self):
        self.client.force_login(self.user)
        older = AIConversation.objects.create(user=self.user, title='Older chat')
        selected = AIConversation.objects.create(user=self.user, title='Selected chat')
        AIMessage.objects.create(conversation=selected, role=AIMessage.ROLE_USER, content='Keep this open')

        response = self.client.get(f'/AI/api/conversations/{selected.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session[AI_CURRENT_CONVERSATION_SESSION_KEY], selected.id)

        response = self.client.get('/AI/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['ai_resume_conversation_id'], selected.id)
        self.assertContains(response, f'var AI_RESUME_CONVERSATION_ID = {selected.id};')
        self.assertNotEqual(older.id, response.context['ai_resume_conversation_id'])

    def test_refresh_falls_back_to_newest_owned_conversation(self):
        self.client.force_login(self.user)
        conversation = AIConversation.objects.create(user=self.user, title='Latest chat')

        response = self.client.get('/AI/')

        self.assertEqual(response.context['ai_resume_conversation_id'], conversation.id)
        self.assertEqual(self.client.session[AI_CURRENT_CONVERSATION_SESSION_KEY], conversation.id)

    def test_guest_chat_survives_login_and_remains_selected(self):
        session = self.client.session
        session.save()
        guest_session_key = session.session_key
        conversation = AIConversation.objects.create(
            session_key=guest_session_key,
            title='Guest chat',
        )
        AIMessage.objects.create(conversation=conversation, role=AIMessage.ROLE_USER, content='Before login')
        session[AI_CURRENT_CONVERSATION_SESSION_KEY] = conversation.id
        session.save()

        response = self.client.post(
            '/store/api/login/',
            data=json.dumps({
                'identifier': self.user.email,
                'password': 'test-password-123',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        conversation.refresh_from_db()
        self.assertEqual(conversation.user, self.user)
        self.assertEqual(conversation.session_key, '')
        self.assertEqual(self.client.session[AI_CURRENT_CONVERSATION_SESSION_KEY], conversation.id)

        response = self.client.get('/AI/')
        self.assertEqual(response.context['ai_resume_conversation_id'], conversation.id)
        response = self.client.get(f'/AI/api/conversations/{conversation.id}/')
        self.assertEqual(response.json()['messages'][0]['content'], 'Before login')


class AIResponseReliabilityTests(TestCase):
    def test_request_routing_does_not_need_a_runtime_ml_model(self):
        self.assertEqual(request_router.classify('Debug this Python traceback'), 'code')
        self.assertEqual(request_router.classify('Research the latest facts and sources'), 'research')
        self.assertEqual(request_router.classify('Hello, how are you?'), 'general')
        self.assertEqual(request_router.choose_model('Fix this JavaScript bug', 'quick')[0], 'code')
        self.assertEqual(request_router.choose_chatgpt_worker('Hello, how are you?')[0], 'quick')
        self.assertEqual(request_router.choose_chatgpt_worker('Write a Python function')[0], 'code')

    def test_chatgpt_uses_worker_model_with_stable_truthful_identity(self):
        chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='answer'))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=iter([chunk])),
        )))

        with patch('myapp.ai_chat._get_client', return_value=client):
            result = ''.join(ai_chat.stream_chat(
                [{'role': 'user', 'content': 'Write a Python function'}],
                model_key='code', identity_model_key=ai_chat.CHATGPT_56_MODEL_KEY,
            ))

        self.assertEqual(result, 'answer')
        request = client.chat.completions.create.call_args.kwargs
        self.assertEqual(request['model'], ai_chat.MODELS['code']['id'])
        self.assertEqual(request['messages'][0]['role'], 'system')
        self.assertIn('Vidhyora Nova', request['messages'][0]['content'])

    def test_chatgpt_is_the_fresh_default_for_staff_on_every_page_load(self):
        user = User.objects.create_user(
            username='staff-fresh-default@example.com', password='test-password-123', is_staff=True,
        )
        self.client.force_login(user)
        response = self.client.get('/AI/')

        self.assertEqual(ai_chat.DEFAULT_MODEL_KEY, ai_chat.CHATGPT_56_MODEL_KEY)
        self.assertEqual(response.context['ai_default_model'], ai_chat.CHATGPT_56_MODEL_KEY)
        self.assertEqual(response.context['ai_default_model_label'], 'Vidhyora Nova')
        self.assertNotContains(response, "localStorage.getItem('ai_model')")
        self.assertNotContains(response, "localStorage.setItem('ai_model'")

    def test_guest_defaults_to_quick_and_only_sees_free_tier_models(self):
        # Guests and free (unsubscribed, non-staff) accounts are restricted
        # to the cheap models — ChatGPT 5.6/Ultra/Nemotron Super are staff-only.
        response = self.client.get('/AI/')

        self.assertEqual(response.context['ai_default_model'], 'quick')
        self.assertEqual(response.context['ai_default_model_label'], 'Vidhyora Flux')
        self.assertEqual(
            {m['key'] for m in response.context['ai_models']},
            {'quick', 'light', 'code'},
        )

    def test_free_account_model_request_is_downgraded_server_side(self):
        # Even if a stale/tampered client asks for a restricted model, the
        # backend clamps it rather than trusting the payload.
        user = User.objects.create_user(username='free-model-clamp@example.com', password='test-password-123')
        self.client.force_login(user)

        with patch('myapp.views.ai_chat.stream_chat', side_effect=lambda *args, **kwargs: iter(['reply'])):
            with patch('myapp.views.light_mode.save_from_chat'):
                response = self.client.post(
                    '/AI/api/send/',
                    data=json.dumps({'model': 'ultra', 'message': 'Hello there'}),
                    content_type='application/json',
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Model-Key'], 'quick')

    def test_chatgpt_routes_general_code_and_image_turns(self):
        user = User.objects.create_user(
            username='chatgpt-router@example.com', password='test-password-123', is_staff=True,
        )
        self.client.force_login(user)

        with patch('myapp.views.ai_chat.stream_chat', side_effect=lambda *args, **kwargs: iter(['reply'])) as stream_chat:
            with patch('myapp.views.light_mode.save_from_chat'):
                with patch('myapp.views.image_ocr.extract_data_uri', return_value=''):
                    cases = (
                        ({'message': 'Hello there'}, 'quick', 'general'),
                        ({'message': 'Debug this Python function'}, 'code', 'code'),
                        ({'message': 'What is in this?', 'image': 'data:image/png;base64,AA=='}, 'vision', 'image'),
                    )
                    for extra_payload, worker_key, category in cases:
                        payload = {'model': ai_chat.CHATGPT_56_MODEL_KEY, **extra_payload}
                        response = self.client.post(
                            '/AI/api/send/', data=json.dumps(payload), content_type='application/json',
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(b''.join(response.streaming_content).decode(), 'reply')
                        self.assertEqual(response['X-Model-Key'], ai_chat.CHATGPT_56_MODEL_KEY)
                        self.assertEqual(response['X-Routed-Model-Key'], worker_key)
                        self.assertEqual(response['X-Request-Category'], category)
                        call = stream_chat.call_args
                        self.assertEqual(call.kwargs['model_key'], worker_key)
                        self.assertEqual(call.kwargs['identity_model_key'], ai_chat.CHATGPT_56_MODEL_KEY)

    def test_accuracy_rules_cover_maths_and_unclear_images(self):
        self.assertTrue(ai_chat.is_math_request('Solve 2x + 5 = 17'))
        self.assertTrue(ai_chat.is_math_request('Calculate 18% of 450'))
        self.assertFalse(ai_chat.is_math_request('Write a friendly customer email'))
        self.assertTrue(ai_chat.is_code_request('Fix this Django traceback'))
        self.assertFalse(ai_chat.is_code_request('Write a friendly customer email'))
        self.assertIn('never give only a number', ai_chat.COMPACT_SYSTEM_PROMPT)
        self.assertIn('ask for a clearer image', ai_chat.COMPACT_SYSTEM_PROMPT)
        self.assertIn('Never claim an action', ai_chat.COMPACT_SYSTEM_PROMPT)
        self.assertIn('complete, secure, directly usable code', ai_chat.CODE_SYSTEM_SUFFIX)
        self.assertIn('Do not claim code was executed or tested', ai_chat.CODE_SYSTEM_SUFFIX)

        chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='answer'))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=iter([chunk])),
        )))
        with patch('myapp.ai_chat._get_client', return_value=client):
            list(ai_chat.stream_chat([{'role': 'user', 'content': 'Calculate 2 + 3'}], model_key='quick'))
        sent_messages = client.chat.completions.create.call_args.kwargs['messages']
        late_reminder = sent_messages[-2]['content']
        self.assertIn('step-by-step', late_reminder)
        self.assertIn('**Final answer:**', late_reminder)
        self.assertIn('verify the result', late_reminder)

    def test_mixed_multimodal_request_gets_complete_response_rules(self):
        prompt = (
            "1. Calculate 15% of 800.\n"
            "2. Analyze the attached screenshot.\n"
            "3. Fix this Python error.\n"
            "4. Explain the relevant Django setting.\n"
            "5. Check whether the logic is valid.\n"
            "6. Product cost is 500, advertising is 100, selling price is 900; calculate profit percentage."
        )
        self.assertEqual(ai_chat.count_user_requests(prompt), 6)
        chunk = SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content='answer'))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(return_value=iter([chunk])),
        )))
        content = [
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AA=='}},
        ]
        with patch('myapp.ai_chat._get_client', return_value=client):
            list(ai_chat.stream_chat([{'role': 'user', 'content': content}], model_key='vision'))

        sent_messages = client.chat.completions.create.call_args.kwargs['messages']
        reminder = sent_messages[-2]['content']
        self.assertIn('Answer every one exactly once', reminder)
        self.assertIn('numbered section per item', reminder)
        self.assertIn('Total cost = product cost + advertising expense', reminder)
        self.assertIn('net profit / total cost × 100', reminder)
        self.assertIn('frontend-safe Markdown', reminder)
        self.assertIn('never labels like pythonCopy', reminder)
        self.assertIn('Analyse the attached image itself', reminder)
        self.assertIn('continue answering all other items', reminder)

    def test_note_router_understands_numbered_read_and_edit_commands(self):
        self.assertEqual(request_router.match_read_note('open note 1'), '1')
        self.assertEqual(request_router.match_read_note('read my note #2'), '#2')
        self.assertEqual(request_router.match_edit_note('edit note 1'), ('1', ''))
        self.assertEqual(request_router.match_edit_note('edit note 1 to Call at 7'), ('1', 'Call at 7'))
        self.assertTrue(request_router.is_note_intent('create a note: Call at 7'))

    def test_note_router_tolerates_common_typos_without_over_correcting(self):
        # A missed match here doesn't fail quietly — it falls through to the
        # real AI model, which (per its own history of this router's past
        # confirmations) fabricates its own fake "done!" instead of just not
        # understanding. See request_router._typo_correct_note_keywords.
        self.assertEqual(request_router.match_delete_note('delet all notyes'), request_router.DELETE_ALL_NOTES)
        self.assertTrue(request_router.is_note_intent('tkae this noet'))
        self.assertTrue(request_router.is_show_notes_intent('shwo my notess'))
        self.assertEqual(request_router.match_edit_note('edti note about milk to bread'), ('milk', 'bread'))
        self.assertEqual(request_router.match_read_note('opne note 1'), '1')
        self.assertTrue(request_router.is_note_intent('remmember a noet: call home'))
        self.assertEqual(request_router.match_delete_note('eraze note 2'), '2')
        self.assertEqual(request_router.match_edit_note('renmae note 1 to New title'), ('1', 'New title'))
        self.assertTrue(request_router.is_show_notes_intent('reed all notyes'))
        # Ordinary sentences that merely contain a word close to one of the
        # trigger keywords must never get swept in as a false positive —
        # 'made' -> 'make' would otherwise turn a past-tense remark into a
        # live "make a note" command.
        self.assertFalse(request_router.is_note_intent('she made a note about it yesterday, what should I do'))
        self.assertFalse(request_router.is_note_intent('I have not opened the store today'))

    def test_company_context_contains_public_contacts_and_prices(self):
        self.assertTrue(company_knowledge.is_company_query('what is the sales team number?'))
        self.assertIn('+91 96959 53183', company_knowledge.PUBLIC_SITE_CONTEXT)
        self.assertIn('₹8,999', company_knowledge.PUBLIC_SITE_CONTEXT)

    def test_company_query_detection_covers_realistic_contact_phrasings(self):
        # These specific phrasings are what actually reached the AI model
        # ungrounded before this fix (the old regex required 'your ...' or
        # 'company's ...' or the brand name) — that gap, not a wrong fact in
        # the prompt itself, is what let it fabricate a fake US toll-free
        # number and a fake sales@edutrellis.com email for "sales team
        # number" style questions. See business_info.py for the real values.
        for query in (
            'sales number', 'contact number', 'WhatsApp number', 'sales email',
            'contact EduTrellis', 'company address', 'customer-support email',
            'how can I contact you?',
        ):
            self.assertTrue(company_knowledge.is_company_query(query), msg=query)
        # Unrelated messages must not get swept in as a false positive.
        for query in ('explain object oriented programming', 'help me write a poem'):
            self.assertFalse(company_knowledge.is_company_query(query), msg=query)

    def test_no_fabricated_contact_details_anywhere_in_ai_facing_text(self):
        wrong_markers = ('555', 'edutrellis.com', 'sales@edutrellis', '1-800', '1‑800')
        for text in (ai_chat.SYSTEM_PROMPT, company_knowledge.PUBLIC_SITE_CONTEXT):
            for marker in wrong_markers:
                self.assertNotIn(marker, text)
        # The real values must come from one shared source, not be retyped.
        self.assertIn(business_info.PHONE_DISPLAY, ai_chat.SYSTEM_PROMPT)
        self.assertIn(business_info.EMAIL_SUPPORT, ai_chat.SYSTEM_PROMPT)
        self.assertIn(business_info.PHONE_DISPLAY, company_knowledge.PUBLIC_SITE_CONTEXT)
        self.assertIn('no separate sales line', ai_chat.SYSTEM_PROMPT)
        self.assertIn('toll-free', company_knowledge.PUBLIC_SITE_CONTEXT)

    def test_knowledge_base_has_no_hallucinated_contact_entries(self):
        # Regression check for the specific cached chat reply that invented
        # a fake toll-free number and sales@edutrellis.com (purged by
        # migration 0042) — asserts the *class* of bad data can't be present,
        # not just that one row is gone.
        from myapp.models import KnowledgeEntry
        wrong_markers = ('edutrellis.com', 'sales@edutrellis', '1-800-555', '1‑800‑555')
        for entry in KnowledgeEntry.objects.all():
            for marker in wrong_markers:
                self.assertNotIn(marker, entry.content, msg=f'entry {entry.pk} ({entry.topic!r})')

    @override_settings(AI_USE_PRESIDIO=False)
    def test_fast_privacy_path_redacts_common_identifiers(self):
        redacted = privacy.redact('Email me@example.com or call 9876543210')

        self.assertEqual(redacted, 'Email <EMAIL> or call <PHONE>')

    def test_default_model_retries_on_quick_backend(self):
        chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content='Recovered reply'))]
        )
        create = SimpleNamespace()
        create.create = Mock(
            side_effect=[TimeoutError('upstream timed out'), iter([chunk])]
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=create))

        with patch('myapp.ai_chat._get_client', return_value=client):
            result = ''.join(ai_chat.stream_chat(
                [{'role': 'user', 'content': 'Hello'}], model_key=ai_chat.DEFAULT_MODEL_KEY
            ))

        self.assertEqual(result, 'Recovered reply')
        self.assertEqual(create.create.call_count, 2)
        self.assertEqual(
            create.create.call_args_list[1].kwargs['model'],
            ai_chat.MODELS['quick']['id'],
        )


class AINoteCRUDTests(TestCase):
    """Exercises My Notes end-to-end through /AI/api/send/, not just the
    request_router regex parsing — request_router.match_read_note/
    match_edit_note being correct in isolation once shipped with a plain
    `re.fullmatch(...)` call in views._ai_matching_notes with no `import re`
    at the top of views.py, which 500'd every read/edit/delete-by-number
    request while create/show (which never call that function) kept working
    silently. A regex-level unit test alone can't catch that class of bug."""
    def setUp(self):
        self.user = User.objects.create_user(
            username='note-crud@example.com', email='note-crud@example.com', password='test-password-123',
        )
        StoreProfile.objects.create(user=self.user, phone='9999999999')
        self.client.force_login(self.user)

    def send(self, message, conversation_id=None):
        payload = {'message': message}
        if conversation_id:
            payload['conversation_id'] = conversation_id
        response = self.client.post('/AI/api/send/', data=json.dumps(payload), content_type='application/json')
        body = b''.join(response.streaming_content).decode('utf-8')
        self.assertEqual(response.status_code, 200, msg=body)
        return response, body

    def test_full_note_lifecycle_via_chat(self):
        response, _ = self.send('note down: buy milk and eggs')
        conversation_id = int(response['X-Conversation-Id'])
        self.send('note down: call dentist tomorrow', conversation_id)
        self.assertEqual(AINote.objects.filter(user=self.user).count(), 2)

        _, show_body = self.send('show my notes', conversation_id)
        self.assertIn('buy milk and eggs', show_body)
        self.assertIn('call dentist tomorrow', show_body)

        _, read_body = self.send('open note 1', conversation_id)
        self.assertIn('call dentist tomorrow', read_body)

        edit_response, edit_body = self.send('replace note about milk with buy milk, eggs and bread', conversation_id)
        self.assertEqual(edit_response['X-Notes-Changed'], '1')
        self.assertIn('buy milk, eggs and bread', AINote.objects.get(heading__icontains='bread').content)

        delete_response, delete_body = self.send('delete note about dentist', conversation_id)
        self.assertEqual(delete_response['X-Notes-Changed'], '1')
        self.assertEqual(AINote.objects.filter(user=self.user).count(), 1)

        self.send('delete all my notes', conversation_id)
        self.assertEqual(AINote.objects.filter(user=self.user).count(), 0)

    def test_contextual_partial_edit_preserves_the_rest_of_the_note(self):
        response, _ = self.send('add note: I have to work tomorow at 4pm')
        conversation_id = int(response['X-Conversation-Id'])
        note = AINote.objects.get(user=self.user)
        self.assertEqual(note.content, 'I have to work tomorrow at 4pm')

        self.send('edit note 1', conversation_id)
        update_response, update_body = self.send('update the time to 7pm', conversation_id)
        self.assertEqual(update_response['X-Notes-Changed'], '1')
        note.refresh_from_db()
        self.assertEqual(note.content, 'I have to work tomorrow at 7pm')
        self.assertIn(note.content, update_body)

    def test_ambiguous_contextual_edit_asks_then_applies_the_choice(self):
        response, _ = self.send('save note: Meeting tomorrow at 4pm')
        conversation_id = int(response['X-Conversation-Id'])
        self.send('update the first note', conversation_id)

        ambiguous_response, ambiguous_body = self.send('update it to 7pm', conversation_id)
        self.assertNotIn('X-Notes-Changed', ambiguous_response)
        self.assertEqual(ambiguous_body, 'Should I update only the time to 7pm, or replace the full note?')
        self.assertEqual(AINote.objects.get(user=self.user).content, 'Meeting tomorrow at 4pm')

        final_response, final_body = self.send('only the time', conversation_id)
        self.assertEqual(final_response['X-Notes-Changed'], '1')
        self.assertEqual(AINote.objects.get(user=self.user).content, 'Meeting tomorrow at 7pm')
        self.assertIn('Meeting tomorrow at 7pm', final_body)

    def test_explicit_database_id_targets_note_without_text_search(self):
        response, _ = self.send('add note: Original text')
        conversation_id = int(response['X-Conversation-Id'])
        note = AINote.objects.get(user=self.user)

        update_response, _ = self.send(f'replace note id {note.pk} with Replaced by database ID', conversation_id)
        self.assertEqual(update_response['X-Notes-Changed'], '1')
        note.refresh_from_db()
        self.assertEqual(note.content, 'Replaced by database ID')

    def test_rename_changes_only_heading_and_never_stores_sidebar_number(self):
        response, _ = self.send('write note: Client meeting at 3pm')
        conversation_id = int(response['X-Conversation-Id'])
        note = AINote.objects.get(user=self.user)

        rename_response, rename_body = self.send('rename the first note to Tomorrow meeting', conversation_id)
        self.assertEqual(rename_response['X-Notes-Changed'], '1')
        note.refresh_from_db()
        self.assertEqual(note.heading, 'Tomorrow meeting')
        self.assertEqual(note.content, 'Client meeting at 3pm')
        self.assertFalse(note.heading.startswith('1.'))
        self.assertIn('Tomorrow meeting', rename_body)
        self.assertIn('Client meeting at 3pm', rename_body)

    def test_bare_save_never_copies_chat_history_and_empty_copy_is_exact(self):
        response, body = self.send('take a note')
        self.assertEqual(AINote.objects.filter(user=self.user).count(), 0)
        self.assertEqual(body, 'What would you like the note to say?')

        conversation_id = int(response['X-Conversation-Id'])
        _, body = self.send('show all notes', conversation_id)
        self.assertEqual(body, 'You don’t have any saved notes.')

    def test_chat_listing_and_sidebar_api_use_identical_database_snapshot(self):
        response, _ = self.send('create a note: first database note')
        conversation_id = int(response['X-Conversation-Id'])
        self.send('remember a note: second database note', conversation_id)

        api_notes = self.client.get('/AI/api/notes/').json()['notes']
        _, chat_body = self.send('view all notes', conversation_id)
        self.assertEqual([item['content'] for item in api_notes], ['second database note', 'first database note'])
        for item in api_notes:
            self.assertIn(item['content'], chat_body)
            self.assertEqual(chat_body.count(item['content']), 1)

        delete_response, _ = self.send('delet all notyes', conversation_id)
        self.assertEqual(delete_response['X-Notes-Changed'], '1')
        self.assertEqual(self.client.get('/AI/api/notes/').json()['notes'], [])


class PublicPagePerformanceAndSEOTests(TestCase):
    def test_customize_settings_drive_share_metadata_and_favicon(self):
        customization = PWASettings.get_solo()
        customization.share_title = 'Custom sharing heading'
        customization.share_description = 'Custom sharing description.'
        customization.share_image.name = 'customize/share-card.png'
        customization.favicon.name = 'customize/favicon.ico'
        customization.save()

        response = self.client.get('/store/')

        self.assertContains(response, '<meta property="og:title" content="Custom sharing heading">', html=True)
        self.assertContains(response, '<meta property="og:description" content="Custom sharing description.">', html=True)
        self.assertContains(response, 'https://www.edutrellis.in/media/customize/share-card.png')
        self.assertContains(response, '<link rel="icon" href="/media/customize/favicon.ico">', html=True)

    def test_product_share_metadata_takes_priority_over_store_defaults(self):
        customization = PWASettings.get_solo()
        customization.share_title = 'Store sharing heading'
        customization.share_description = 'Store sharing description.'
        customization.save()
        category = Category.objects.create(name='Share Test', slug='share-test')
        product = Product.objects.create(
            category=category, slug='share-test-product', brand='EduTrellis',
            name='Dynamic Product', short_description='Dynamic product description.',
            price='99.00', mrp='99.00', is_active=True,
        )

        response = self.client.get(f'/store/product/{product.slug}/')

        self.assertContains(response, '<meta property="og:title" content="Dynamic Product — EduTrellis Store">', html=True)
        self.assertContains(response, '<meta property="og:description" content="Dynamic product description.">', html=True)

    def test_customize_dashboard_exposes_share_and_favicon_fields(self):
        admin = User.objects.create_user(
            username='customize-admin@example.com', password='test-password-123', is_staff=True,
        )
        self.client.force_login(admin)

        response = self.client.get('/store/dashboard/customize/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="share_title"')
        self.assertContains(response, 'name="share_description"')
        self.assertContains(response, 'name="share_image"')
        self.assertContains(response, 'name="favicon"')

    def test_apex_domain_redirects_permanently_to_canonical_www_host(self):
        middleware = CanonicalHostMiddleware(lambda request: HttpResponse('page'))

        response = middleware(RequestFactory().get(
            '/store/?category=audio', HTTP_HOST='edutrellis.in', secure=True,
        ))

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response['Location'],
            'https://www.edutrellis.in/store/?category=audio',
        )

    def test_estore_alias_and_missing_slash_use_permanent_redirects(self):
        alias = self.client.get('/estore')
        missing_slash = self.client.get('/store')

        self.assertRedirects(alias, '/store/', status_code=301, fetch_redirect_response=False)
        self.assertRedirects(missing_slash, '/store/', status_code=301, fetch_redirect_response=False)

    def test_anonymous_store_view_does_not_create_an_empty_cart(self):
        response = self.client.get('/store/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Cart.objects.count(), 0)

    def test_public_assets_receive_browser_cache_headers(self):
        middleware = PublicAssetCacheMiddleware(lambda request: HttpResponse('asset'))

        static_response = middleware(RequestFactory().get('/static/style.css'))
        media_response = middleware(RequestFactory().get('/media/products/example.webp'))

        self.assertIn('max-age=86400', static_response['Cache-Control'])
        self.assertIn('max-age=604800', media_response['Cache-Control'])

    def test_product_page_has_canonical_product_structured_data(self):
        category = Category.objects.create(name='SEO Test Audio', slug='seo-test-audio')
        product = Product.objects.create(
            category=category, slug='test-speaker', brand='EduTrellis',
            name='Test Speaker', short_description='A test product.',
            price='999.00', mrp='1299.00', is_active=True,
        )

        response = self.client.get(f'/store/product/{product.slug}/')
        schema = json.loads(response.context['product_schema_json'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(schema['@type'], 'Product')
        self.assertEqual(schema['offers']['priceCurrency'], 'INR')
        self.assertContains(
            response,
            f'<link rel="canonical" href="https://www.edutrellis.in/store/product/{product.slug}/">',
            html=True,
        )


class HTMLExtractionTests(TestCase):
    HTML = b'''<!doctype html>
        <html><head><style>.hidden { display:none }</style></head>
        <body><h1>Upload title</h1><p>Tom &amp; Jerry</p>
        <script>stealSecret()</script><noscript>hidden fallback</noscript></body></html>'''

    def test_html_uses_standard_library_fallback_without_bs4(self):
        with patch.dict('sys.modules', {'bs4': None}):
            text, truncated = doc_extract.extract('example.html', self.HTML)

        self.assertIn('Upload title', text)
        self.assertIn('Tom & Jerry', text)
        self.assertNotIn('stealSecret', text)
        self.assertNotIn('display:none', text)
        self.assertNotIn('hidden fallback', text)
        self.assertFalse(truncated)

    def test_html_upload_endpoint_returns_extracted_text(self):
        upload = SimpleUploadedFile('example.html', self.HTML, content_type='text/html')

        response = self.client.post('/AI/api/extract/', {'file': upload})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertIn('Upload title', response.json()['text'])
        self.assertIn('<h1>Upload title</h1>', response.json()['coding_text'])
        self.assertIn('<script>stealSecret()</script>', response.json()['coding_text'])

    def test_common_source_code_file_is_supported_without_renaming(self):
        source = b'def greet(name):\n    return f"Hello {name}"\n'

        text, truncated = doc_extract.extract('app.py', source)
        coding_text, coding_truncated = doc_extract.extract_editable_source('app.py', source, text)

        self.assertEqual(text, source.decode())
        self.assertEqual(coding_text, source.decode())
        self.assertFalse(truncated)
        self.assertFalse(coding_truncated)

    def test_document_action_instructions_keep_coding_and_details_separate(self):
        coding = _ai_document_instruction('coding', 'index.html')
        details = _ai_document_instruction('details', 'index.html')

        self.assertIn('COMPLETE updated file', coding)
        self.assertIn('never return only a patch', coding)
        self.assertIn('Analyse and explain only', details)
        self.assertIn('Do not rewrite the file', details)


class AIDocumentActionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='document-actions@example.com',
            email='document-actions@example.com',
            password='test-password-123',
            is_staff=True,
        )
        self.client.force_login(self.user)

    def test_coding_action_forces_code_mode_and_full_file_instruction(self):
        payload = {
            'message': 'Change the theme colors to blue.',
            'model': 'light',
            'document_name': 'index.html',
            'document_text': '<html><body>Original</body></html>',
            'document_mode': 'coding',
            'document_truncated': False,
        }
        with patch('myapp.views.ai_chat.stream_chat', return_value=iter(['updated file'])) as stream_chat:
            with patch('myapp.views.light_mode.save_from_chat'):
                response = self.client.post(
                    '/AI/api/send/', data=json.dumps(payload), content_type='application/json'
                )
                body = b''.join(response.streaming_content).decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(body, 'updated file')
        kwargs = stream_chat.call_args.kwargs
        self.assertEqual(kwargs['model_key'], 'code')
        self.assertEqual(kwargs['max_tokens'], 6000)
        self.assertIn('COMPLETE updated file', kwargs['document_instruction'])

    def test_details_action_keeps_analysis_only_instruction(self):
        payload = {
            'message': 'Show details about this file only.',
            'model': 'quick',
            'document_name': 'report.pdf',
            'document_text': 'Quarterly report content',
            'document_mode': 'details',
        }
        with patch('myapp.views.ai_chat.stream_chat', return_value=iter(['details'])) as stream_chat:
            with patch('myapp.views.light_mode.save_from_chat'):
                response = self.client.post(
                    '/AI/api/send/', data=json.dumps(payload), content_type='application/json'
                )
                b''.join(response.streaming_content)

        kwargs = stream_chat.call_args.kwargs
        self.assertEqual(kwargs['model_key'], 'quick')
        self.assertIsNone(kwargs['max_tokens'])
        self.assertIn('Do not rewrite the file', kwargs['document_instruction'])
