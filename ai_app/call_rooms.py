"""Calls with more than two people ("Add person" during a direct-chat call).

Everyone in the room connects to everyone else browser to browser (WebRTC
mesh, up to ROOM_MAX people), so the server only passes messages between
them: each member has an inbox in the cache that the others drop offers,
answers, ICE candidates and mute / camera / recording flags into, and that
the member's call screen polls every second.

The two people already on the direct-chat call stay connected over that
call; everyone who joins later connects to each member through the room.
The person who joined later always sends the offer, so two people never
offer to each other at the same time.
"""
import secrets
import threading

from django.core.cache import cache
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone

from .models import ChatUser, DirectThread
from .support_chat import CALL_RING_SECONDS, CALL_STALE_SECONDS, _fail, _json_body, ice_servers

ROOM_MAX = 4
BOX_MAX = 400
SIGNALS = ('offer', 'answer', 'ice', 'flag', 'bye')
# One worker process (Procfile): this keeps two requests from writing the same
# room or inbox at once and losing one of the changes.
_lock = threading.RLock()


def _room_key(rid):
    return f'callroom-{rid}'


def _box_key(rid, uid):
    return f'callroom-{rid}-box-{uid}'


def _of_key(uid):
    return f'callroom-of-{uid}'      # the room a user is invited to / in right now


def ring_key(uid):
    return f'roomring-{uid}'


def _save(room):
    cache.set(_room_key(room['id']), room, CALL_STALE_SECONDS)


def _load(rid):
    room = cache.get(_room_key(str(rid)[:32]))
    if not room:
        return None
    now = timezone.now().timestamp()
    changed = False
    for uid, m in room['members'].items():   # an invite nobody answered
        if m['state'] == 'invited' and now - m['at'] > CALL_RING_SECONDS:
            m['state'] = 'missed'
            changed = True
            _forget(uid, room['id'])
    if changed:
        _save(room)
    return room


def _forget(uid, rid):
    if cache.get(_of_key(uid)) == rid:
        cache.delete(_of_key(uid))
    if cache.get(ring_key(uid)) == rid:
        cache.delete(ring_key(uid))


def _seq(room):
    room['seq'] = room.get('seq', 0) + 1
    return room['seq']


def _member(user, state, by=None, seq=0):
    return {'name': user.name, 'state': state, 'at': timezone.now().timestamp(), 'by': by, 'seq': seq}


def share_call(viewer_id, owner_id):
    """True while two people are in (or invited to) the same call room — lets
    them see each other's profile picture on the call screen."""
    rid = cache.get(_of_key(str(viewer_id)))
    return bool(rid) and rid == cache.get(_of_key(str(owner_id)))


def _photo(uid):
    user = ChatUser.objects.filter(pk=int(uid)).only('photo').first()
    return reverse('chats_user_photo', args=[int(uid)]) if user and user.photo else ''


def _room_json(room, me):
    return {
        'id': room['id'], 'kind': room['kind'], 'me': str(me.pk), 'max': ROOM_MAX,
        'members': [{'id': uid, 'name': m['name'], 'state': m['state'], 'seq': m.get('seq', 0),
                     'initial': (m['name'][:1] or '?').upper(), 'photo': _photo(uid)}
                    for uid, m in room['members'].items()],
    }


def _push(room, to, item):
    key = _box_key(room['id'], to)
    box = cache.get(key, [])
    item['n'] = _seq(room)
    box.append(item)
    cache.set(key, box[-BOX_MAX:], CALL_STALE_SECONDS)


def _contact(me, other):
    """Only people you already chat with (and haven't blocked) can be added."""
    low, high = sorted([me.pk, other.pk])
    return DirectThread.objects.filter(user_a_id=low, user_b_id=high, blocked_by__isnull=True).first()


def create_for_dm(me, thread, state):
    """Turns a direct-chat call into a room (first "Add person"). Returns the room id."""
    from .direct_chat import _dm_call_key
    if state.get('room') and _load(state['room']):
        return state['room']
    rid = secrets.token_hex(8)
    room = {'id': rid, 'kind': state['kind'], 'thread': thread.pk, 'created': timezone.now().timestamp(), 'seq': 0,
            'members': {}}
    for uid in (state['caller'], state['callee']):
        user = ChatUser.objects.get(pk=int(uid))
        room['members'][uid] = _member(user, 'joined', seq=_seq(room))
        cache.set(_of_key(uid), rid, CALL_STALE_SECONDS)
    _save(room)
    state['room'] = rid
    cache.set(_dm_call_key(thread.pk), state, CALL_STALE_SECONDS)
    return rid


def api_rooms(request):
    """POST {action: 'create', thread, call}: make the current direct-chat call a room."""
    from .direct_chat import _dm_call_state, _me, _my_thread
    me, error = _me(request)
    if error:
        return error
    if request.method != 'POST':
        return _fail('POST only.', 405)
    data = _json_body(request)
    thread = _my_thread(me, data.get('thread'))
    state = _dm_call_state(thread) if thread else None
    if not state or state.get('id') != data.get('call') or state['status'] != 'active':
        return _fail('Add people once the call has connected.', 409)
    with _lock:
        rid = create_for_dm(me, thread, state)
    return JsonResponse({'ok': True, 'room': _room_json(_load(rid), me), 'ice_servers': ice_servers()})


def api_room(request, rid):
    """GET ?after=n → the people in the call and new messages for me.
    POST {action: invite|join|decline|signal|leave, ...}."""
    from .direct_chat import _me
    me, error = _me(request)
    if error:
        return error
    room = _load(rid)
    uid = str(me.pk)
    if not room or uid not in room['members']:
        return _fail('This call has ended.', 404)
    mine = room['members'][uid]
    if request.method != 'POST':
        try:
            after = int(request.GET.get('after') or 0)
        except ValueError:
            after = 0
        inbox = [m for m in cache.get(_box_key(room['id'], uid), []) if m['n'] > after] if mine['state'] == 'joined' else []
        return JsonResponse({'ok': True, 'room': _room_json(room, me), 'inbox': inbox,
                             'ice_servers': ice_servers() if request.GET.get('ice') else None})

    data = _json_body(request)
    with _lock:
        room = _load(rid)
        if not room or uid not in room['members']:
            return _fail('This call has ended.', 404)
        return _room_action(request, me, room, data)


def _room_action(request, me, room, data):
    uid = str(me.pk)
    mine = room['members'][uid]
    action = data.get('action')
    if action == 'invite':
        if mine['state'] != 'joined':
            return _fail('Join the call first.', 409)
        target = ChatUser.objects.filter(username=str(data.get('username', '')).lstrip('@').lower()[:30],
                                         is_active=True, is_guest=False).first()
        if not target or target.pk == me.pk:
            return _fail('Choose someone you chat with.', 404)
        tid = str(target.pk)
        if room['members'].get(tid, {}).get('state') in ('joined', 'invited'):
            return _fail(f'{target.name.split(" ")[0]} is already in this call.', 409)
        if sum(1 for m in room['members'].values() if m['state'] in ('joined', 'invited')) >= ROOM_MAX:
            return _fail(f'A call can have up to {ROOM_MAX} people.', 409)
        thread = _contact(me, target)
        if not thread:
            return _fail('You can only add people you already chat with.', 403)
        from .direct_chat import _ring_key
        busy_room = cache.get(_of_key(tid))
        if (busy_room and busy_room != room['id']) or cache.get(_ring_key(target.pk)):
            return _fail(f'{target.name.split(" ")[0]} is on another call.', 409)
        room['members'][tid] = _member(target, 'invited', by=me.name)
        _save(room)
        cache.set(_of_key(tid), room['id'], CALL_STALE_SECONDS)
        cache.set(ring_key(tid), room['id'], CALL_RING_SECONDS + 5)
        from .educhats_push import ring
        ring(target, str(thread.pk), f'{me.name} (group call)', room['kind'],
             {'path': f'api/calls/room/{room["id"]}/', 'body': {'action': 'decline'}})
    elif action == 'join':
        if mine['state'] != 'invited':
            return _fail('This invite has ended.', 409)
        mine.update(state='joined', at=timezone.now().timestamp(), seq=_seq(room))
        _save(room)
        cache.delete(ring_key(uid))
    elif action == 'decline':
        if mine['state'] == 'invited':
            mine.update(state='declined', at=timezone.now().timestamp())
            _save(room)
        _forget(uid, room['id'])
    elif action == 'signal':
        to = str(data.get('to', ''))
        kind = data.get('type')
        other = room['members'].get(to)
        if mine['state'] != 'joined' or not other or other['state'] != 'joined' or kind not in SIGNALS:
            return _fail('That person has left the call.', 409)
        payload = data.get('data')
        if len(str(payload)) > 20000:
            return _fail('Too big.', 400)
        _push(room, to, {'from': uid, 'type': kind, 'data': payload})
        _save(room)
    elif action == 'leave':
        if mine['state'] == 'joined':
            mine.update(state='left', at=timezone.now().timestamp())
            for other_id, other in room['members'].items():
                if other_id != uid and other['state'] == 'joined':
                    _push(room, other_id, {'from': uid, 'type': 'bye', 'data': None})
            _save(room)
        _forget(uid, room['id'])
    else:
        return _fail('Unknown action.', 400)
    return JsonResponse({'ok': True, 'room': _room_json(room, me), 'ice_servers': ice_servers() if action == 'join' else None})


def ringing_room(me):
    """For the chat list's "is anyone calling me?" check."""
    rid = cache.get(ring_key(str(me.pk)))
    room = _load(rid) if rid else None
    m = room and room['members'].get(str(me.pk))
    if not m or m['state'] != 'invited':
        return None
    others = [x['name'] for k, x in room['members'].items() if k != str(me.pk) and x['state'] == 'joined']
    return {'room': room['id'], 'kind': room['kind'], 'name': m.get('by') or 'EduChats',
            'others': others, 'members': _room_json(room, me)['members']}
