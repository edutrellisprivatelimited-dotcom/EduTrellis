"""EduChats app lock (⋮ → App lock).

With a PIN set, every browser / installed app has to unlock EduChats before it
gets any chat data: support_chat.current_user() treats a locked session as
signed out, so every API, photo and file refuses, and the page shows only the
lock screen (chats_locked.html). Unlocking (PIN, or fingerprint / face / Windows
Hello through WebAuthn) marks this session unlocked in the cache; each request
keeps that fresh, and once nothing has been heard for the chosen time
(immediately, 1 minute, 30 minutes) it locks again. Logging in with the
password also unlocks, so "Forgot PIN?" is: log out, log in.

WebAuthn is done here with `cryptography` (attestation "none"; ES256 and RS256
keys, the ones phones, Macs and Windows Hello use).
"""
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlsplit

import hmac
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone

LOCK_AFTER_CHOICES = (0, 60, 1800)     # straight away, 1 minute, 30 minutes
GRACE = 20                            # "straight away" still survives a page reload
MAX_TRIES = 5                         # wrong PINs before a pause
SIGN_OUT_AFTER = 10                   # wrong PINs before this session is signed out
MAX_KEYS = 10


# ── the PIN ──
# A 4–6 digit PIN has at most a million values, so no hash makes it strong on its
# own — the server-side wrong-PIN limit below is the real protection. A salted
# PBKDF2 at a modest cost keeps unlocking instant.
PIN_ROUNDS = 60000


def hash_pin(pin):
    salt = secrets.token_hex(8)
    digest = hashlib.pbkdf2_hmac('sha256', pin.encode(), salt.encode(), PIN_ROUNDS).hex()
    return f'pin${PIN_ROUNDS}${salt}${digest}'


def check_pin(pin, stored):
    try:
        kind, rounds, salt, digest = stored.split('$')
    except ValueError:
        return False
    if kind != 'pin':
        return False
    test = hashlib.pbkdf2_hmac('sha256', str(pin).encode(), salt.encode(), int(rounds)).hex()
    return hmac.compare_digest(test, digest)


# ── is this session unlocked? ────────────────────────────────────────────────

def lock_enabled(user):
    return bool(user and not user.is_guest and user.app_lock_pin)


def _key(request, user):
    return f'educhats-unlocked-{user.pk}-{request.session.session_key or "-"}'


def _ttl(user):
    return max(user.app_lock_after, 0) + GRACE


def is_unlocked(request, user):
    """True when no lock is set, or this session has unlocked recently (and keeps it alive)."""
    if not lock_enabled(user):
        return True
    if not request.session.session_key:
        return False
    key = _key(request, user)
    if cache.get(key):
        cache.touch(key, _ttl(user))
        return True
    return False


def mark_unlocked(request, user):
    if not request.session.session_key:
        request.session.save()
    cache.set(_key(request, user), 1, _ttl(user))
    cache.delete(f'educhats-lockfail-{user.pk}')


def lock_now(request, user):
    cache.delete(_key(request, user))


# ── WebAuthn (fingerprint / face / Windows Hello) ────────────────────────────

def _b64u(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _unb64u(text):
    text = str(text or '')
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def cbor_decode(data, pos=0):
    """(value, next position) — the small part of CBOR WebAuthn uses."""
    first = data[pos]
    major, info = first >> 5, first & 0x1f
    pos += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        arg = int.from_bytes(data[pos:pos + size], 'big')
        pos += size
    else:
        raise ValueError('unsupported CBOR')
    if major == 0:
        return arg, pos
    if major == 1:
        return -1 - arg, pos
    if major == 2:
        return bytes(data[pos:pos + arg]), pos + arg
    if major == 3:
        return bytes(data[pos:pos + arg]).decode(), pos + arg
    if major == 4:
        out = []
        for _ in range(arg):
            item, pos = cbor_decode(data, pos)
            out.append(item)
        return out, pos
    if major == 5:
        out = {}
        for _ in range(arg):
            k, pos = cbor_decode(data, pos)
            v, pos = cbor_decode(data, pos)
            out[k] = v
        return out, pos
    if major == 7:
        return {20: False, 21: True, 22: None}.get(info), pos
    raise ValueError('unsupported CBOR')


def _rp_id(request):
    return request.get_host().split(':')[0]


def _origin_ok(request, origin):
    parts = urlsplit(origin or '')
    host = request.get_host()
    if parts.netloc != host:
        return False
    local = host.split(':')[0] in ('localhost', '127.0.0.1')
    return parts.scheme == 'https' or (local and parts.scheme == 'http')


def _client_data(request, raw, kind, session_key):
    data = json.loads(raw)
    expected = request.session.pop(session_key, None)
    if data.get('type') != kind or not expected or data.get('challenge') != expected:
        raise ValueError('challenge')
    if not _origin_ok(request, data.get('origin')):
        raise ValueError('origin')
    return data


def _auth_data(request, auth):
    if auth[:32] != hashlib.sha256(_rp_id(request).encode()).digest():
        raise ValueError('rp')
    flags = auth[32]
    if not (flags & 0x01 and flags & 0x04):   # user present + verified (fingerprint / face / PIN)
        raise ValueError('not verified')
    return flags, int.from_bytes(auth[33:37], 'big')


def _public_key(cred):
    from cryptography.hazmat.primitives.asymmetric import ec, rsa
    if cred['kty'] == 2:
        x, y = _unb64u(cred['x']), _unb64u(cred['y'])
        return ec.EllipticCurvePublicNumbers(int.from_bytes(x, 'big'), int.from_bytes(y, 'big'), ec.SECP256R1()).public_key()
    return rsa.RSAPublicNumbers(int.from_bytes(_unb64u(cred['e']), 'big'), int.from_bytes(_unb64u(cred['n']), 'big')).public_key()


def _verify_signature(cred, signature, signed):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding
    key = _public_key(cred)
    if cred['kty'] == 2:
        key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
    else:
        key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())


def _device_name(request):
    ua = request.META.get('HTTP_USER_AGENT', '')
    for needle, name in (('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android phone'), ('Windows', 'Windows Hello'),
                         ('Macintosh', 'Mac'), ('CrOS', 'Chromebook'), ('Linux', 'Linux computer')):
        if needle in ua:
            return name
    return 'This device'


def register_options(request, user):
    challenge = _b64u(secrets.token_bytes(32))
    request.session['educhats-webauthn-reg'] = challenge
    from .models import EduChatsAppSettings
    return {
        'challenge': challenge,
        'rp': {'name': EduChatsAppSettings.load().app_name, 'id': _rp_id(request)},
        'user': {'id': _b64u(f'educhats-{user.pk}'.encode()), 'name': user.username or user.email or user.name,
                 'displayName': user.name},
        'pubKeyCredParams': [{'type': 'public-key', 'alg': -7}, {'type': 'public-key', 'alg': -257}],
        'authenticatorSelection': {'authenticatorAttachment': 'platform', 'userVerification': 'required',
                                   'residentKey': 'discouraged'},
        'excludeCredentials': [{'type': 'public-key', 'id': k['id']} for k in user.app_lock_keys or []],
        'timeout': 60000, 'attestation': 'none',
    }


def register_finish(request, user, cred):
    resp = cred.get('response') or {}
    raw_client = _unb64u(resp.get('clientDataJSON'))
    _client_data(request, raw_client, 'webauthn.create', 'educhats-webauthn-reg')
    att, _ = cbor_decode(_unb64u(resp.get('attestationObject')))
    auth = att['authData']
    flags, count = _auth_data(request, auth)
    if not flags & 0x40:
        raise ValueError('no credential')
    id_len = int.from_bytes(auth[53:55], 'big')
    cred_id = auth[55:55 + id_len]
    cose, _ = cbor_decode(auth, 55 + id_len)
    kty, alg = cose.get(1), cose.get(3)
    if kty == 2 and alg == -7 and cose.get(-1) == 1:
        key = {'kty': 2, 'x': _b64u(cose[-2]), 'y': _b64u(cose[-3])}
    elif kty == 3 and alg == -257:
        key = {'kty': 3, 'n': _b64u(cose[-1]), 'e': _b64u(cose[-2])}
    else:
        raise ValueError('key type')
    key.update(id=_b64u(cred_id), alg=alg, count=count, name=_device_name(request),
               created=timezone.localtime().strftime('%d %b %Y'))
    keys = [k for k in (user.app_lock_keys or []) if k['id'] != key['id']][-(MAX_KEYS - 1):]
    user.app_lock_keys = keys + [key]
    user.save(update_fields=['app_lock_keys'])
    return key


def unlock_options(request, user, ids=None):
    """Only this device's own keys (the page says which), so no other-device / QR prompt."""
    challenge = _b64u(secrets.token_bytes(32))
    request.session['educhats-webauthn-get'] = challenge
    keys = [k for k in user.app_lock_keys or [] if not ids or k['id'] in ids]
    return {'challenge': challenge, 'rpId': _rp_id(request), 'timeout': 60000, 'userVerification': 'required',
            'allowCredentials': [{'type': 'public-key', 'id': k['id'], 'transports': ['internal']} for k in keys]}


def unlock_finish(request, user, cred):
    keys = user.app_lock_keys or []
    key = next((k for k in keys if k['id'] == cred.get('id')), None)
    if not key:
        raise ValueError('unknown key')
    resp = cred.get('response') or {}
    raw_client = _unb64u(resp.get('clientDataJSON'))
    _client_data(request, raw_client, 'webauthn.get', 'educhats-webauthn-get')
    auth = _unb64u(resp.get('authenticatorData'))
    _, count = _auth_data(request, auth)
    _verify_signature(key, _unb64u(resp.get('signature')), auth + hashlib.sha256(raw_client).digest())
    if count and key.get('count') and count <= key['count']:
        raise ValueError('cloned key')
    key['count'] = count
    user.save(update_fields=['app_lock_keys'])


# ── the API ──────────────────────────────────────────────────────────────────

def status(request, user):
    return {'enabled': lock_enabled(user), 'after': user.app_lock_after,
            'keys': [{'id': k['id'], 'name': k.get('name', 'Device'), 'created': k.get('created', '')} for k in user.app_lock_keys or []],
            'locked': not is_unlocked(request, user)}


def api_lock(request):
    """GET → status. POST {action, …}: set / after / off / lock / unlock / bio-* (see below)."""
    from .support_chat import _fail, _json_body, current_user
    user = current_user(request, allow_locked=True)
    if not user:
        return _fail('Please log in again.', 401)
    if user.is_guest:
        return _fail('Sign up first to use app lock.', 403)
    if request.method != 'POST':
        return JsonResponse({'ok': True, **status(request, user)})
    data = _json_body(request)
    action = data.get('action')
    unlocked = is_unlocked(request, user)

    # ── while locked ──
    if action == 'unlock':
        fails_key = f'educhats-lockfail-{user.pk}'
        fails = cache.get(fails_key) or {'n': 0, 'until': 0}
        wait = int(fails['until'] - time.time())
        if wait > 0:
            return _fail(f'Too many wrong PINs. Try again in {wait} seconds.', 429)
        if lock_enabled(user) and check_pin(str(data.get('pin', '')), user.app_lock_pin):
            mark_unlocked(request, user)
            return JsonResponse({'ok': True})
        fails['n'] += 1
        if fails['n'] >= SIGN_OUT_AFTER:
            cache.delete(fails_key)
            request.session.flush()
            return _fail('Too many wrong PINs, so you have been logged out. Log in again with your password.', 401)
        if fails['n'] >= MAX_TRIES:
            fails['until'] = time.time() + 30 * 2 ** (fails['n'] - MAX_TRIES)
        cache.set(fails_key, fails, 3600)
        left = SIGN_OUT_AFTER - fails['n']
        return _fail('Wrong PIN.' + (f' {left} tries left before you are logged out.' if fails['n'] >= MAX_TRIES - 1 else ''), 403)
    if action == 'bio-begin':
        if not user.app_lock_keys:
            return _fail('Fingerprint unlock is not set up.')
        ids = [str(i) for i in data.get('ids') or [] if isinstance(i, str)][:MAX_KEYS]
        return JsonResponse({'ok': True, 'options': unlock_options(request, user, ids)})
    if action == 'bio-finish':
        try:
            unlock_finish(request, user, data.get('credential') or {})
        except Exception:
            return _fail('That fingerprint / face could not be checked. Try again or use your PIN.', 403)
        mark_unlocked(request, user)
        return JsonResponse({'ok': True})
    if action == 'lock':
        lock_now(request, user)
        return JsonResponse({'ok': True})

    # ── settings: only from an unlocked EduChats ──
    if not unlocked:
        return _fail('Unlock EduChats first.', 423)
    if action == 'set':
        pin = str(data.get('pin', ''))
        if not (pin.isdigit() and 4 <= len(pin) <= 6):
            return _fail('Use 4 to 6 digits for your PIN.')
        if len(set(pin)) == 1 or pin in '0123456789' or pin in '9876543210':
            return _fail('That PIN is too easy to guess. Try a different one.')
        user.app_lock_pin = hash_pin(pin)
        if data.get('after') is not None:
            user.app_lock_after = int(data['after']) if str(data['after']).isdigit() and int(data['after']) in LOCK_AFTER_CHOICES else 0
        user.save(update_fields=['app_lock_pin', 'app_lock_after'])
        mark_unlocked(request, user)
        return JsonResponse({'ok': True, **status(request, user)})
    if action == 'after':
        value = int(data['after']) if str(data.get('after', '')).isdigit() else -1
        if value not in LOCK_AFTER_CHOICES:
            return _fail('Choose when EduChats should lock.')
        user.app_lock_after = value
        user.save(update_fields=['app_lock_after'])
        mark_unlocked(request, user)
        return JsonResponse({'ok': True, **status(request, user)})
    if action == 'off':
        user.app_lock_pin, user.app_lock_keys = '', []
        user.save(update_fields=['app_lock_pin', 'app_lock_keys'])
        return JsonResponse({'ok': True, **status(request, user)})
    if action == 'bio-register-begin':
        if not lock_enabled(user):
            return _fail('Set a PIN first.')
        return JsonResponse({'ok': True, 'options': register_options(request, user)})
    if action == 'bio-register-finish':
        try:
            register_finish(request, user, data.get('credential') or {})
        except Exception:
            return _fail('Fingerprint / face unlock could not be set up on this device.')
        return JsonResponse({'ok': True, **status(request, user)})
    if action == 'bio-remove':
        user.app_lock_keys = [k for k in user.app_lock_keys or [] if k['id'] != data.get('id')]
        user.save(update_fields=['app_lock_keys'])
        return JsonResponse({'ok': True, **status(request, user)})
    return _fail('Unknown action.')
