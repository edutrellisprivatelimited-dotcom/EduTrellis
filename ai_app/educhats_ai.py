"""EduTrellis AI inside EduChats — the pinned "EduTrellis AI" chat.

Free for every EduChats member: normal chat plus picture creation, using the
same models, identity rules and image generator as /ai/. There is no message
quota; a per-minute / per-hour speed limit only stops scripts from flooding it.
"""
import logging
import re
import secrets

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import EduChatsAIMessage
from .support_chat import MAX_MESSAGE, _fail, _ip, _json_body, current_user

logger = logging.getLogger(__name__)

HISTORY_TURNS = 20          # earlier messages sent along for context
PER_MINUTE = 15             # anti-flood only — no daily or total quota
IMAGES_PER_HOUR = 30


def _message_json(m):
    return {'id': m.pk, 'role': m.role, 'body': m.body, 'image': m.image_url,
            'at': timezone.localtime(m.created_at).isoformat()}


def _throttled(key, limit, seconds):
    count = cache.get(key, 0)
    if count >= limit:
        return True
    cache.set(key, count + 1, seconds)
    return False


def _model_key():
    from . import ai_chat
    for key in (ai_chat.DEFAULT_MODEL_KEY, ai_chat.TERRA_MODEL_KEY, ai_chat.SOL_MODEL_KEY):
        if ai_chat.is_model_enabled(key):
            return key
    return 'quick'


def _text_reply(user, history):
    from . import ai_chat
    from .views import _chatgpt_public_reply, _vidhyora_public_reply
    model_key = _model_key()
    context = f"The person chatting is {user.name}" + (f" (@{user.username})" if user.username else '') \
        + ", using EduTrellis AI inside EduChats, EduTrellis's chat app."
    reply = ''.join(ai_chat.stream_chat(history, model_key=model_key, user_context=context))
    reply = ai_chat.strip_think_tags(reply).strip()
    if model_key in (ai_chat.CHATGPT_56_MODEL_KEY, ai_chat.SOL_MODEL_KEY, ai_chat.TERRA_MODEL_KEY):
        return _chatgpt_public_reply(reply, ai_chat.chatgpt_persona_name(model_key))
    return _vidhyora_public_reply(reply, ai_chat.MODELS[model_key]['label'])


def _image_reply(prompt):
    from . import image_generation
    generated = image_generation.generate_image(prompt)
    folder = timezone.now().strftime('%Y/%m/%d')
    name = default_storage.save(f'ai_generated/{folder}/{secrets.token_hex(16)}.{generated.extension}',
                                ContentFile(generated.content))
    return default_storage.url(name)


def api_ai(request):
    user = current_user(request)
    if not user:
        return _fail('Please log in again.', 401)
    if request.method != 'POST':
        try:
            after = int(request.GET.get('after') or 0)
        except ValueError:
            after = 0
        rows = user.ai_messages.filter(pk__gt=after).order_by('-pk')[:200]
        return JsonResponse({'ok': True, 'messages': [_message_json(m) for m in reversed(list(rows))]})

    data = _json_body(request)
    text = re.sub(r'[ \t]+\n', '\n', str(data.get('body', ''))).strip()[:MAX_MESSAGE]
    if not text:
        return _fail('Type a message first.')
    who = f'u{user.pk}' if not user.is_guest else f'ip{_ip(request) or user.pk}'
    if _throttled(f'educhats-ai-{who}', PER_MINUTE, 60):
        return _fail("You're sending messages very fast — please wait a few seconds.", 429)

    from . import ai_chat
    wants_image = data.get('mode') == 'image' or (
        ai_chat.is_image_generation_request(text) or ai_chat.is_design_request(text))
    if wants_image and _throttled(f'educhats-ai-img-{who}', IMAGES_PER_HOUR, 3600):
        return _fail("You've created a lot of pictures this hour — please try again a little later.", 429)

    mine = EduChatsAIMessage.objects.create(user=user, role=EduChatsAIMessage.ROLE_USER, body=text)
    try:
        if wants_image:
            url = _image_reply(text)
            answer = EduChatsAIMessage.objects.create(
                user=user, role=EduChatsAIMessage.ROLE_ASSISTANT, image_url=url,
                body="Here's your picture — tap it to open full size, or describe what to change.")
        else:
            earlier = list(user.ai_messages.filter(pk__lt=mine.pk).exclude(body='').order_by('-pk')[:HISTORY_TURNS])[::-1]
            history = [{'role': m.role, 'content': m.body[:8000]} for m in earlier]
            # the model expects user/assistant turns to alternate, ending with the user
            merged = []
            for turn in history + [{'role': 'user', 'content': text}]:
                if merged and merged[-1]['role'] == turn['role']:
                    merged[-1]['content'] += '\n\n' + turn['content']
                else:
                    merged.append(dict(turn))
            if merged and merged[0]['role'] != 'user':
                merged = merged[1:]
            reply = _text_reply(user, merged) or "Sorry, I couldn't come up with an answer — could you rephrase that?"
            answer = EduChatsAIMessage.objects.create(user=user, role=EduChatsAIMessage.ROLE_ASSISTANT, body=reply)
    except Exception as exc:
        logger.exception('EduChats AI reply failed for chat user %s', user.pk)
        blocked = getattr(exc, 'blocked', False)
        note = ("That picture couldn't be made — try describing it a different way." if blocked
                else 'EduTrellis AI is busy right now. Please try again in a moment.')
        return JsonResponse({'ok': False, 'error': note, 'message': _message_json(mine)}, status=502)
    return JsonResponse({'ok': True, 'messages': [_message_json(mine), _message_json(answer)]})
