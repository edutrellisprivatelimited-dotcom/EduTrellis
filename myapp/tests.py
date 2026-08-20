import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from . import doc_extract
from .models import AIConversation, AIMessage, StoreProfile
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
