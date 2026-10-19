"""Locations and view-once media for every EduChats conversation.

Locations: one pin or a live location that moves for 15 min / 1 h / 8 h, sent to
the support chat, a direct chat, a group, or (by the support team) to a member.
View once: a photo or video the other side can open a single time. Its file is
never listed in the chat; opening it hands out a short-lived link, and the file
is deleted from the server soon after it has been opened.
"""
import secrets
from datetime import timedelta

from django.core.cache import cache
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ChatMessage, ChatUser, DirectMessage, DirectThread, GroupMember, GroupMessage

LIVE_MINUTES = (0, 15, 60, 480)
ONCE_KINDS = ('image', 'video')
ONCE_LINK_SECONDS = 10 * 60   # a video keeps asking for pieces while it plays
ONCE_KEEP = timedelta(minutes=15)   # the file is deleted this long after it was opened


# ── shared JSON ──────────────────────────────────────────────────────────────

def location_json(message):
    return {
        'id': message.pk, 'lat': message.latitude, 'lng': message.longitude,
        'live_until': timezone.localtime(message.live_until).isoformat() if message.live_until else None,
        'live': bool(message.live_until and message.live_until > timezone.now()),
        'updated': timezone.localtime(message.location_updated_at or message.created_at).isoformat(),
    }


def live_locations(rows):
    """Live locations still running (or ended in the last minute) in these messages,
    so an open chat can move their pins without reloading."""
    recent = timezone.now() - timedelta(minutes=1)
    return [location_json(m) for m in rows.filter(kind='location', live_until__gte=recent)]


def once_json(message, scope, opened):
    """What a chat shows for a view-once photo/video: never the file itself."""
    return {'once': True, 'opened': bool(opened), 'open_url': reverse('chats_once_open', args=[scope, message.pk])}


def wants_once(request, kind):
    return bool(request.POST.get('once')) and kind in ONCE_KINDS


# ── sending a location ───────────────────────────────────────────────────────

def _coords(data):
    try:
        lat, lng = float(data.get('lat')), float(data.get('lng'))
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng


def _target(request, me, to):
    """(model, create kwargs, json(message), touch(message), error) for where `to` points."""
    from .support_chat import _fail, _message_json, staff_account
    to = str(to or '')
    if to.startswith('sx'):   # the support team, to a member
        if not staff_account(request, me) or not to[2:].isdigit():
            return None, _fail('This chat is not available.', 404)
        member = ChatUser.objects.filter(pk=int(to[2:])).exclude(pk=me.pk).first()
        if not member:
            return None, _fail('This chat is not available.', 404)
        return {'model': ChatMessage, 'make': {'user': member, 'sender': ChatMessage.SENDER_ADMIN},
                'mine': {'user': member, 'sender': ChatMessage.SENDER_ADMIN}, 'json': _message_json,
                'touch': lambda m: None}, None
    if me.is_guest:
        return None, _fail('Sign up or log in to share your location.', 403)
    if to.startswith('g'):
        from .group_chat import _membership, _message_json as group_json
        ms = _membership(me, to[1:])
        if not ms:
            return None, _fail("You're not in this group any more.", 404)
        if not (ms.is_admin or not ms.group.only_admins_send):
            return None, _fail('Only admins can send messages in this group.', 403)

        def touch(m):
            from .models import ChatGroup
            ChatGroup.objects.filter(pk=ms.group_id).update(updated_at=m.created_at)
            GroupMember.objects.filter(pk=ms.pk).update(last_read=m.pk)
        return {'model': GroupMessage, 'make': {'group': ms.group, 'sender': me}, 'mine': {'group': ms.group, 'sender': me},
                'json': lambda m: group_json(m, me), 'touch': touch}, None
    from .direct_chat import _message_json as dm_json, _my_thread
    try:
        thread = _my_thread(me, int(to))
    except (TypeError, ValueError):
        thread = None
    if not thread:
        return None, _fail('This chat is not available.', 404)
    if thread.blocked_by_id:
        return None, _fail("You can't message this person.", 403)
    if not thread.other(me).is_active:
        return None, _fail('This account is not available any more.', 403)
    return {'model': DirectMessage, 'make': {'thread': thread, 'sender': me}, 'mine': {'thread': thread, 'sender': me},
            'json': lambda m: dm_json(m, me),
            'touch': lambda m: DirectThread.objects.filter(pk=thread.pk).update(updated_at=m.created_at)}, None


def send_location(request, me, data):
    """api/location/ with `to` (a direct chat id, 'g<id>' or the support team's 'sx<member id>'):
    share a pin, start a live location, move it, or stop it."""
    from .support_chat import SEND_LIMIT_ERROR, _fail, over_send_limit
    target, error = _target(request, me, data.get('to'))
    if error:
        return error
    model, now = target['model'], timezone.now()
    if data.get('id'):
        message = model.objects.filter(pk=data['id'], kind='location', **target['mine']).first()
        if not message:
            return _fail('That location is no longer shared.', 404)
        if data.get('stop'):
            message.live_until = now
            message.save(update_fields=['live_until'])
            return JsonResponse({'ok': True, 'location': location_json(message)})
        coords = _coords(data)
        if not coords or not message.live_until or message.live_until <= now:
            return _fail('Live location has ended.')
        message.latitude, message.longitude = coords
        message.location_updated_at = now
        message.save(update_fields=['latitude', 'longitude', 'location_updated_at'])
        return JsonResponse({'ok': True, 'location': location_json(message)})
    coords = _coords(data)
    if not coords:
        return _fail('Could not read your location.')
    try:
        minutes = int(data.get('live_minutes') or 0)
    except (TypeError, ValueError):
        minutes = 0
    if minutes not in LIVE_MINUTES:
        minutes = 0
    if over_send_limit(me):
        return _fail(SEND_LIMIT_ERROR, 429)
    message = model.objects.create(
        kind='location', body='Live location' if minutes else 'Location', latitude=coords[0], longitude=coords[1],
        live_until=now + timedelta(minutes=minutes) if minutes else None, location_updated_at=now, **target['make'])
    target['touch'](message)
    return JsonResponse({'ok': True, 'message': target['json'](message)})


# ── view once ────────────────────────────────────────────────────────────────

def _expire_opened():
    """Deletes the files of view-once photos/videos opened a while ago."""
    cutoff = timezone.now() - ONCE_KEEP
    for model in (ChatMessage, DirectMessage):
        for m in model.objects.filter(view_once=True, opened_at__lt=cutoff).exclude(attachment=''):
            try:
                m.attachment.delete(save=False)
            except OSError:
                pass
            model.objects.filter(pk=m.pk).update(attachment='')


@require_POST
def api_once_open(request, scope, pk):
    """The person it was sent to opens a view-once photo/video: one time only."""
    from .support_chat import _fail, _staff_viewer, current_user
    me = current_user(request)
    now = timezone.now()
    gone = _fail('This photo or video was already opened.', 410)
    if scope == 's':
        m = ChatMessage.objects.filter(pk=pk, view_once=True).first()
        if not m:
            return _fail('Not found.', 404)
        allowed = _staff_viewer(request, me) if m.sender == ChatMessage.SENDER_USER else bool(me and me.pk == m.user_id)
        if not allowed:
            return _fail('Only the person it was sent to can open it.', 403)
        if m.opened_at or not m.attachment:
            return gone
        ChatMessage.objects.filter(pk=m.pk).update(opened_at=now)
        url = reverse('chats_attachment', args=[m.pk])
    elif scope == 'd':
        m = DirectMessage.objects.filter(pk=pk, view_once=True).select_related('thread').first()
        if not m or not me or me.pk not in (m.thread.user_a_id, m.thread.user_b_id):
            return _fail('Not found.', 404)
        if m.sender_id == me.pk:
            return _fail('Only the person it was sent to can open it.', 403)
        if m.opened_at or not m.attachment:
            return gone
        DirectMessage.objects.filter(pk=m.pk).update(opened_at=now)
        url = reverse('chats_dm_file', args=[m.pk])
    elif scope == 'g':
        m = GroupMessage.objects.filter(pk=pk, view_once=True).first()
        if not m or not me or not GroupMember.objects.filter(group_id=m.group_id, user=me).exists():
            return _fail('Not found.', 404)
        if m.sender_id == me.pk:
            return _fail('Only the people it was sent to can open it.', 403)
        if me.pk in (m.opened_by or []) or not m.attachment:
            return gone
        m.opened_by = list(m.opened_by or []) + [me.pk]
        m.save(update_fields=['opened_by'])
        url = reverse('chats_group_file', args=[m.pk])
    else:
        return _fail('Not found.', 404)
    token = secrets.token_urlsafe(18)
    cache.set(f'once-link-{token}', f'{scope}{m.pk}', ONCE_LINK_SECONDS)
    _expire_opened()
    return JsonResponse({'ok': True, 'url': f'{url}?once={token}', 'kind': m.kind, 'caption': m.body})


def once_link_ok(request, scope, pk):
    """A view-once file is only served through the link handed out when it was opened."""
    token = request.GET.get('once') or ''
    return bool(token) and cache.get(f'once-link-{token}') == f'{scope}{pk}'
