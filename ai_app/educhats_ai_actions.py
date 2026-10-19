"""EduTrellis AI doing things for you in EduChats (⋮ → More AI features).

"Let AI send messages for you": with the switch on, asking the AI chat to message
someone — "say hello to @rnt", "send a message to rnt saying I'm on my way",
"tell rnt that the class is at 5", "rnt ko hello bolo" — sends that message as
you in your direct chat with them, and the AI answers "Done ✅ …". Only plain,
clear commands are acted on; anything else is a normal question for the AI.
"""
import re

from django.core.cache import cache

from .models import ChatMessage, ChatUser, DirectMessage, DirectThread

PENDING_SECONDS = 5 * 60   # "What should I say to them?" waits this long for your answer

_PRE = r'^(?:(?:please|pls|plz|kindly|hey|hi|ai|can you|could you|would you|will you)[\s,]+)*'
_WHO = r'(?!to\s)(?P<at>@)?(?P<who>[A-Za-z0-9_.]{2,30})'
_SEP = r'(?:\s*(?:saying|that says|which says|and say|and tell (?:him|her|them)|that|:|-|,)\s*|\s+)'
_NOUN = r'(?:a\s+|an\s+)?(?:message|msg|text|dm|note|whatsapp)'
_HINDI_DO = r'(?:bolo|bol do|bol de|bhejo|bhej do|bhej de|likho|likh do|send karo|message karo|msg karo)'

# (pattern, explicit): "explicit" commands name the person after "to", so if that
# person isn't found we say so; the others only count when the person is found.
PATTERNS = [
    (re.compile(_PRE + r'(?:send|drop|write)\s+' + _NOUN + r'\s+(?:to\s+)?' + _WHO + _SEP + r'(?P<body>.+)$', re.I | re.S), True),
    (re.compile(_PRE + r'(?:send|drop|write)\s+' + _NOUN + r'\s+(?:to\s+)?' + _WHO + r'[\s.!?]*$', re.I), True),
    (re.compile(_PRE + r'(?:message|msg|text|dm|ping|whatsapp)\s+(?:to\s+)?' + _WHO + _SEP + r'(?P<body>.+)$', re.I | re.S), False),
    (re.compile(_PRE + r'(?:message|msg|text|dm|ping|whatsapp)\s+(?:to\s+)?' + _WHO + r'[\s.!?]*$', re.I), False),
    (re.compile(_PRE + r'send\s+(?P<body>.+?)\s+to\s+' + _WHO + r'[\s.!?]*$', re.I | re.S), True),
    (re.compile(_PRE + r'say\s+(?P<body>.+?)\s+to\s+' + _WHO + r'[\s.!?]*$', re.I | re.S), True),
    (re.compile(_PRE + r'(?:tell|inform)\s+' + _WHO + r'\s+(?:that\s+|to\s+)?(?P<body>.+)$', re.I | re.S), False),
    (re.compile(_PRE + _WHO + r'\s+ko\s+(?:message|msg|text)\s+(?:bhejo|bhej do|karo|kar do)\s*(?:ki|:|-)?\s*(?P<body>.*)$', re.I | re.S), True),
    (re.compile(_PRE + _WHO + r'\s+ko\s+(?P<body>.+?)\s+' + _HINDI_DO + r'[\s.!?]*$', re.I | re.S), True),
]
_CANCEL = re.compile(r'^\s*(cancel|stop|nothing|never ?mind|no|nahi|rehne do|leave it)\W*$', re.I)
_GREETINGS = {'hi', 'hello', 'hey', 'hii', 'hiii', 'helo', 'namaste', 'good morning', 'good night', 'good evening', 'thanks', 'thank you'}


def parse(text):
    """{'who', 'at', 'body', 'explicit'} for a "message someone" command, else None."""
    text = (text or '').strip()
    for pattern, explicit in PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        body = (m.groupdict().get('body') or '').strip()
        body = re.sub(r'[\s,]*(?:please|pls|plz|for me|on my behalf)[\s.!]*$', '', body, flags=re.I).strip()
        body = body.strip('"\'“”‘’ ').strip()
        if body.lower().rstrip('!.') in _GREETINGS:
            body = body[:1].upper() + body[1:]
        return {'who': m.group('who').rstrip('.').lower(), 'at': bool(m.group('at')), 'body': body,
                'explicit': explicit or bool(m.group('at'))}
    return None


def _find_person(me, who):
    """The account `who` points to: an exact @username, else someone you already chat
    with whose name or first name matches (only if that's one person)."""
    person = ChatUser.objects.filter(username__iexact=who, is_guest=False, is_active=True).exclude(pk=me.pk).first()
    if person:
        return person
    threads = DirectThread.objects.filter(user_a=me) | DirectThread.objects.filter(user_b=me)
    peers = [t.other(me) for t in threads.select_related('user_a', 'user_b')]
    matches = [p for p in peers if p.is_active and (p.name.lower() == who or p.name.lower().split(' ')[0] == who)]
    return matches[0] if len(matches) == 1 else None


def _send_dm(me, person, body):
    """Sends `body` to `person` as me. Returns '' or why it couldn't be sent."""
    from .direct_chat import NEW_THREAD_LIMIT
    from .support_chat import MAX_MESSAGE, SEND_LIMIT_ERROR, over_send_limit, set_live
    low, high = sorted([me.pk, person.pk])
    thread = DirectThread.objects.filter(user_a_id=low, user_b_id=high).first()
    if thread and thread.blocked_by_id:
        return f"I couldn't send it — {'you have blocked' if thread.blocked_by_id == me.pk else 'you cannot message'} {person.name}."
    if not thread:
        key = f'chats-newdm-{me.pk}'
        made = cache.get(key, 0)
        if made >= NEW_THREAD_LIMIT:
            return 'You have started a lot of new chats. Please wait a while before starting another.'
        cache.set(key, made + 1, 3600)
        thread = DirectThread.objects.create(user_a_id=low, user_b_id=high, started_by=me)
    if over_send_limit(me):
        return SEND_LIMIT_ERROR
    message = DirectMessage.objects.create(thread=thread, sender=me, body=body[:MAX_MESSAGE], kind='text')
    set_live('typing', f'd{thread.pk}', me.pk, False)
    DirectThread.objects.filter(pk=thread.pk).update(updated_at=message.created_at)
    return ''


def _send_support(me, body):
    from .support_chat import MAX_MESSAGE, SEND_LIMIT_ERROR, over_send_limit
    if over_send_limit(me):
        return SEND_LIMIT_ERROR
    ChatMessage.objects.create(user=me, sender=ChatMessage.SENDER_USER, body=body[:MAX_MESSAGE])
    return ''


def handle(me, text):
    """The AI's answer when `text` asks it to message someone (and does it), else None."""
    if not me or me.is_guest:
        return None
    pending_key = f'educhats-ai-send-{me.pk}'
    pending = cache.get(pending_key)
    cmd = parse(text)
    if not cmd and pending:   # the answer to "What should I say to them?"
        cache.delete(pending_key)
        if _CANCEL.match(text):
            return "Okay, I won't send anything."
        cmd = {'who': pending, 'at': True, 'body': text.strip(), 'explicit': True}
    if not cmd:
        return None
    to_support = cmd['who'] in ('support', 'supportteam', 'edutrellissupport')
    person = None if to_support else _find_person(me, cmd['who'])
    if not person and not to_support:
        if not cmd['explicit']:
            return None   # "tell me a joke" — just a question
        return (f"I couldn't find anyone on EduChats called “{cmd['who']}”. "
                "Check their @username and try again — for example: say hello to @username")
    if not me.ai_send_messages:
        return ("I can send messages for you, but that's switched off. Turn it on in "
                "⋮ Menu → More AI features → Let AI send messages for you, then ask me again.")
    name = 'the support team' if to_support else f'{person.name} (@{person.username})'
    if not cmd['body']:
        cache.set(pending_key, 'support' if to_support else person.username, PENDING_SECONDS)
        return f'What should I say to {name}? (Say "cancel" to stop.)'
    cache.delete(pending_key)
    error = _send_support(me, cmd['body']) if to_support else _send_dm(me, person, cmd['body'])
    if error:
        return error
    return f'Done ✅ Message sent to {name}:\n\n“{cmd["body"]}”'
