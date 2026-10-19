"""EduChats notifications: Web Push to phones and computers, and the app-icon badge.

A browser (or the installed app) that allows notifications saves a
PushSubscription through api_push. When a message is saved for someone, the
post_save hooks at the bottom send each of their devices a small encrypted
push from a background thread. The service worker (educhats_pwa.py) shows it
and sets the app badge to the unread count inside it.

The push itself is standard Web Push, done here with `cryptography`:
RFC 8291 message encryption (aes128gcm) plus a VAPID (RFC 8292) signature.
The VAPID key pair is made the first time and kept in EduChatsAppSettings.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from django.db import close_old_connections, connection, transaction
from django.db.models import Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import JsonResponse
from django.utils import timezone

from .models import (ChatMessage, ChatUser, DirectMessage, DirectThread, EduChatsAppSettings, GroupMember,
                     GroupMessage, PushSubscription, SupportProfile)

log = logging.getLogger(__name__)

# Only real push services — the server POSTs to these addresses, so nothing else is accepted.
PUSH_HOSTS = re.compile(r'(?:^|\.)(?:fcm\.googleapis\.com|android\.googleapis\.com|push\.services\.mozilla\.com'
                        r'|push\.apple\.com|notify\.windows\.com|push\.microsoft\.com)\Z')
MAX_DEVICES = 10            # per account; the oldest goes first
SUBJECT = 'mailto:support@edutrellis.com'


def _b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _unb64u(text):
    text = str(text)
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


# ── VAPID ────────────────────────────────────────────────────────────────────

def vapid_keys():
    """(private key, public key as base64url) — created and saved the first time."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    app = EduChatsAppSettings.load()
    if app.vapid_private and app.vapid_public:
        d = int.from_bytes(_unb64u(app.vapid_private), 'big')
        return ec.derive_private_key(d, ec.SECP256R1()), app.vapid_public
    key = ec.generate_private_key(ec.SECP256R1())
    private = _b64u(key.private_numbers().private_value.to_bytes(32, 'big'))
    public = _b64u(key.public_key().public_bytes(serialization.Encoding.X962,
                                                 serialization.PublicFormat.UncompressedPoint))
    # .update() so the app's icon version (updated_at) doesn't change
    EduChatsAppSettings.objects.filter(pk=app.pk).update(vapid_private=private, vapid_public=public)
    return key, public


def _vapid_header(endpoint, key, public):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    parts = urlsplit(endpoint)
    head = _b64u(json.dumps({'typ': 'JWT', 'alg': 'ES256'}, separators=(',', ':')).encode())
    claims = _b64u(json.dumps({'aud': f'{parts.scheme}://{parts.netloc}', 'exp': int(time.time()) + 12 * 3600,
                               'sub': SUBJECT}, separators=(',', ':')).encode())
    signing_input = f'{head}.{claims}'.encode()
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    token = f'{head}.{claims}.{_b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))}'
    return f'vapid t={token}, k={public}'


# ── RFC 8291 encryption (Content-Encoding: aes128gcm) ────────────────────────

def _hmac(key, data):
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(p256dh, auth, plaintext, salt=None, server_key=None):
    """The encrypted body for one subscription."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    ua_public = _unb64u(p256dh)
    auth_secret = _unb64u(auth)
    salt = salt or os.urandom(16)
    server_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = server_key.public_key().public_bytes(serialization.Encoding.X962,
                                                     serialization.PublicFormat.UncompressedPoint)
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = _hmac(_hmac(auth_secret, shared), b'WebPush: info\x00' + ua_public + as_public + b'\x01')
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b'Content-Encoding: aes128gcm\x00\x01')[:16]
    nonce = _hmac(prk, b'Content-Encoding: nonce\x00\x01')[:12]
    record = AESGCM(cek).encrypt(nonce, plaintext + b'\x02', None)   # \x02 = last record, no padding
    return salt + struct.pack('!I', 4096) + bytes([len(as_public)]) + as_public + record


def _send(sub, payload):
    """POST one push. Returns True when delivered; drops subscriptions the service says are gone."""
    key, public = vapid_keys()
    body = encrypt(sub.p256dh, sub.auth, json.dumps(payload, separators=(',', ':')).encode())
    req = urllib.request.Request(sub.endpoint, data=body, method='POST', headers={
        'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream', 'TTL': '86400',
        'Urgency': 'high', 'Authorization': _vapid_header(sub.endpoint, key, public),
        'Topic': re.sub(r'[^A-Za-z0-9_-]', '', str(payload.get('tag', 'educhats')))[:32] or 'educhats',
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):   # unsubscribed / expired
            PushSubscription.objects.filter(pk=sub.pk).delete()
        else:
            log.warning('EduChats push failed (%s) for subscription %s', e.code, sub.pk)
        return False
    except Exception as e:
        log.warning('EduChats push could not be sent: %s', e)
        return False
    if ok:
        PushSubscription.objects.filter(pk=sub.pk).update(last_ok=timezone.now())
    return ok


# ── unread counts (the badge) ────────────────────────────────────────────────

def _is_staff(user):
    from .support_chat import staff_account
    return bool(staff_account(None, user))


def unread_by_chat(user):
    """{chat key: unread count} — the same keys the page uses."""
    out = {}
    if _is_staff(user):
        waiting = (ChatMessage.objects.filter(sender=ChatMessage.SENDER_USER, read_by_admin=False)
                   .exclude(user=user).values_list('user_id', flat=True).distinct())
        for uid in waiting:
            out[f'sx{uid}'] = 1   # one per person waiting, like the inbox badge
    else:
        n = user.messages.filter(sender=ChatMessage.SENDER_ADMIN, read_by_user=False,
                                 pk__gt=user.support_cleared_upto).count()
        if n:
            out['support'] = n
    for t in DirectThread.objects.filter(Q(user_a=user) | Q(user_b=user)):
        n = t.messages.filter(pk__gt=t.cleared_upto(user), read_at__isnull=True).exclude(sender=user).count()
        if n:
            out[str(t.pk)] = n
    for ms in GroupMember.objects.filter(user=user):
        n = (GroupMessage.objects.filter(group_id=ms.group_id, pk__gt=max(ms.last_read, ms.cleared_upto))
             .exclude(sender=user).exclude(kind='system').count())
        if n:
            out[f'g{ms.group_id}'] = n
    return out


# ── sending ──────────────────────────────────────────────────────────────────

def preview(kind, body, name=''):
    body = re.sub(r'\s+', ' ', body or '').strip()
    if kind == 'image':
        return '📷 ' + (body or 'Photo')
    if kind == 'video':
        return '🎥 ' + (body or 'Video')
    if kind == 'file':
        return '📄 ' + (body or name or 'Document')
    if kind == 'voice':
        return f'🎤 Voice message ({body})' if body else '🎤 Voice message'
    if kind == 'sticker':
        return 'Sticker'
    if kind == 'gif':
        return 'GIF'
    if kind == 'location':
        return '📍 ' + (body or 'Location')
    if kind == 'call':
        return '📞 ' + body
    return body[:160] + ('…' if len(body) > 160 else '')


def push_to(user, chat, title, body, call=False):
    """Every device of this user that allows notifications, unless the chat is muted there."""
    subs = list(PushSubscription.objects.filter(user=user))
    if not subs:
        return
    counts = unread_by_chat(user)
    for sub in subs:
        muted = set(str(m) for m in (sub.muted or []))
        if chat in muted and not call:
            continue
        badge = sum(n for key, n in counts.items() if key not in muted)
        _send(sub, {'title': title[:80], 'body': body[:200], 'chat': chat, 'tag': f'chat-{chat}',
                    'badge': badge, 'call': call, 'ts': int(time.time() * 1000)})


def _in_background(fn, *args):
    def run():
        close_old_connections()
        try:
            fn(*args)
        except Exception:
            log.exception('EduChats notification failed')
        finally:
            connection.close()

    def start():
        if not getattr(_in_background, 'disabled', False):
            threading.Thread(target=run, daemon=True).start()
    transaction.on_commit(start)


def _first(name):
    return (name or '').split(' ')[0] or 'Someone'


def _support_message(message_id):
    from .support_chat import is_live, staff_account
    m = ChatMessage.objects.filter(pk=message_id).select_related('user').first()
    if not m:
        return
    member = m.user
    text = preview(m.kind, m.body, m.attachment_name)
    if m.sender == ChatMessage.SENDER_USER:   # a member wrote to support → the support team
        if is_live('here', f's{member.pk}', 'staff'):
            return
        for staff in ChatUser.objects.filter(django_user__isnull=False, is_active=True, is_guest=False).exclude(pk=member.pk):
            if staff_account(None, staff):
                push_to(staff, f'sx{member.pk}', f'{member.name or "Guest"} · Support', text)
    else:                                     # support replied → the member
        if not is_live('here', f's{member.pk}', 'user'):
            push_to(member, 'support', SupportProfile.load().display_name, text)


def _direct_message(message_id):
    from .support_chat import is_live
    m = DirectMessage.objects.filter(pk=message_id).select_related('thread', 'sender').first()
    if not m or not m.sender:
        return
    other = m.thread.other(m.sender)
    if m.kind == 'call' and not m.body.lower().startswith('missed'):
        return
    if other.is_active and not m.thread.blocked_by_id and not is_live('here', f'd{m.thread_id}', other.pk):
        push_to(other, str(m.thread_id), m.sender.name, preview(m.kind, m.body, m.attachment_name))


def _group_message(message_id):
    m = GroupMessage.objects.filter(pk=message_id).select_related('group', 'sender').first()
    if not m or not m.sender or m.kind == 'system':
        return
    text = f'{_first(m.sender.name)}: {preview(m.kind, m.body, m.attachment_name)}'
    for ms in GroupMember.objects.filter(group=m.group).exclude(user=m.sender).select_related('user'):
        if ms.user.is_active:
            push_to(ms.user, f'g{m.group_id}', m.group.name, text)


def ring(user, chat, caller_name, kind):
    """An incoming call: a notification that stays until it's answered or dismissed."""
    label = 'video call' if kind == 'video' else 'voice call'
    _in_background(push_to, user, chat, caller_name, f'📞 Incoming {label}…', True)


def ring_support_team(member, kind):
    from .support_chat import staff_account

    def run():
        for staff in ChatUser.objects.filter(django_user__isnull=False, is_active=True, is_guest=False).exclude(pk=member.pk):
            if staff_account(None, staff):
                push_to(staff, f'sx{member.pk}', f'{member.name or "Guest"} · Support',
                        f'📞 Incoming {"video" if kind == "video" else "voice"} call…', True)
    _in_background(run)


@receiver(post_save, sender=ChatMessage)
def _on_support_message(sender, instance, created, raw=False, **kwargs):
    if not created or raw:
        return
    if instance.kind == ChatMessage.KIND_CALL and not instance.body.lower().startswith('missed'):
        return
    _in_background(_support_message, instance.pk)


@receiver(post_save, sender=DirectMessage)
def _on_direct_message(sender, instance, created, raw=False, **kwargs):
    if created and not raw:
        _in_background(_direct_message, instance.pk)


@receiver(post_save, sender=GroupMessage)
def _on_group_message(sender, instance, created, raw=False, **kwargs):
    if created and not raw and instance.kind != 'system':
        _in_background(_group_message, instance.pk)


# ── the page: subscribe / unsubscribe / muted chats ──────────────────────────

def api_push(request):
    """GET → the public key. POST {action: subscribe|unsubscribe|muted, subscription|endpoint, muted}."""
    from .support_chat import _fail, _json_body, current_user
    user = current_user(request)
    if not user:
        return _fail('Please log in again.', 401)
    if request.method != 'POST':
        return JsonResponse({'ok': True, 'public_key': vapid_keys()[1],
                             'devices': PushSubscription.objects.filter(user=user).count()})
    data = _json_body(request)
    action = data.get('action')
    muted = [str(m)[:20] for m in (data.get('muted') or []) if isinstance(m, (str, int))][:500]
    if action == 'subscribe':
        sub = data.get('subscription') or {}
        endpoint = str(sub.get('endpoint', ''))[:500]
        keys = sub.get('keys') or {}
        parts = urlsplit(endpoint)
        if parts.scheme != 'https' or not PUSH_HOSTS.search(parts.hostname or ''):
            return _fail('Notifications are not supported in this browser.')
        try:
            if len(_unb64u(keys.get('p256dh', ''))) != 65 or len(_unb64u(keys.get('auth', ''))) < 16:
                raise ValueError
        except Exception:
            return _fail('Notifications are not supported in this browser.')
        PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={
            'user': user, 'p256dh': str(keys['p256dh'])[:120], 'auth': str(keys['auth'])[:48], 'muted': muted,
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200]})
        extra = PushSubscription.objects.filter(user=user).order_by('-created_at').values_list('pk', flat=True)[MAX_DEVICES:]
        PushSubscription.objects.filter(pk__in=list(extra)).delete()
        return JsonResponse({'ok': True})
    endpoint = str(data.get('endpoint', ''))[:500]
    if action == 'unsubscribe':
        PushSubscription.objects.filter(user=user, endpoint=endpoint).delete()
        return JsonResponse({'ok': True})
    if action == 'muted':
        PushSubscription.objects.filter(user=user, endpoint=endpoint).update(muted=muted)
        return JsonResponse({'ok': True})
    return _fail('Unknown action.')


def api_badge(request):
    """The unread count for the app icon (the service worker asks when it wakes up)."""
    from .support_chat import current_user
    user = current_user(request)
    if not user:
        return JsonResponse({'ok': False, 'badge': 0})
    return JsonResponse({'ok': True, 'badge': sum(unread_by_chat(user).values())})
