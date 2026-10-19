"""Support inbox inside EduChats.

The superuser's own EduChats account *is* the support team: instead of a
"Support" chat with itself it gets a "Support inbox" row that lists every
member's support chat and answers it right there — the same messages, blue
ticks, typing, files and calls as Dashboard → EduChats → Chats.
"""
import hashlib
import re

from django.core.cache import cache
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone

from .educhats_social import socials_json
from .models import ChatMessage, ChatUser
from .support_chat import (ice_servers, MAX_MESSAGE, _call_state, _fail, _json_body, _live_locations,
                           _message_from_upload, _message_json, _presence, _public_call, _read_upto, call_action,
                           call_key, is_live, set_live, staff_account, touch_staff, upload_cid_key)

INBOX_SIZE = 300


def _photo(user):
    if not user.photo:
        return ''
    return reverse('chats_user_photo', args=[user.pk]) + '?v=' + hashlib.md5(user.photo.name.encode()).hexdigest()[:8]


def _person(user):
    return {
        'id': user.pk, 'name': user.name or 'Guest', 'username': user.username or '', 'guest': user.is_guest,
        'initial': ((user.name or '?')[:1]).upper(), 'photo': _photo(user), 'active': user.is_active,
        'presence': _presence(user.last_seen_at),   # staff see it, as on the dashboard
    }


def _ringing(user):
    call = cache.get(call_key(user.pk))
    return bool(call and call['status'] == 'ringing' and call['caller'] == 'user'
                and timezone.now().timestamp() - call['started'] <= 45)


def api_inbox(request):
    """Everyone who has written to support, newest conversation first."""
    me = staff_account(request)
    if not me:
        return _fail('Only the support team can open the inbox.', 403)
    touch_staff()
    last_id = ChatMessage.objects.filter(user=OuterRef('pk')).order_by('-pk').values('pk')[:1]
    users = (ChatUser.objects.exclude(pk=me.pk)
             .annotate(total=Count('messages'), last_at=Max('messages__created_at'), last_id=Subquery(last_id),
                       pending=Count('messages', filter=Q(messages__sender=ChatMessage.SENDER_USER,
                                                          messages__read_by_admin=False)))
             .filter(total__gt=0))
    q = re.sub(r'\s+', ' ', request.GET.get('q', '')).strip()[:60]
    if q:
        users = users.filter(Q(name__icontains=q) | Q(username__icontains=q.lstrip('@')) | Q(email__icontains=q)
                             | Q(phone__icontains=q) | Q(city__icontains=q))
    users = list(users.order_by('-last_at')[:INBOX_SIZE])
    last = ChatMessage.objects.in_bulk([u.last_id for u in users if u.last_id])
    rows = []
    for u in users:
        row = _person(u)
        m = last.get(u.last_id)
        row.update(pending=u.pending, last=_message_json(m) if m else None,
                   typing=is_live('typing', f's{u.pk}', 'user'), ringing=_ringing(u))
        rows.append(row)
    return JsonResponse({'ok': True, 'chats': rows, 'waiting': sum(1 for r in rows if r['pending'])})


def _contact(user):
    """Everything the support team sees on the member's card (same as the dashboard)."""
    data = _person(user)
    data.update({
        'email': user.email, 'phone': user.phone, 'bio': user.bio, 'city': user.city, 'state': user.state,
        'ip': user.last_ip or user.ip, 'verified': user.is_verified,
        'joined': timezone.localtime(user.created_at).strftime('%d %b %Y'),
        'cover': reverse('chats_user_cover', args=[user.pk]) if user.cover else '',
        'socials': socials_json(user, only_shown=False),
        'dashboard': reverse('dashboard_chat_thread', args=[user.pk]),
    })
    return data


def api_inbox_chat(request, pk):
    """One member's support chat: GET new messages (?after=), POST a reply."""
    me = staff_account(request)
    if not me:
        return _fail('Only the support team can open the inbox.', 403)
    user = ChatUser.objects.filter(pk=pk).exclude(pk=me.pk).first()
    if not user:
        return _fail('This chat is not available.', 404)
    touch_staff()
    unread = user.messages.filter(sender=ChatMessage.SENDER_USER, read_by_admin=False)
    if request.method == 'POST':
        if request.FILES.get('file'):
            key = upload_cid_key(request, f'sx{user.pk}')
            if key and cache.get(key):
                return JsonResponse({'ok': True, 'message': cache.get(key)})
            message, error = _message_from_upload(user, ChatMessage.SENDER_ADMIN, request)
            if error:
                return _fail(error)
            set_live('typing', f's{user.pk}', 'staff', False)
            if key:
                cache.set(key, _message_json(message), 6 * 3600)
        else:
            from .educhats_media import media_from
            data = _json_body(request)
            kind, payload = media_from(data)   # a sticker or GIF instead of text
            if kind is None:
                return _fail(payload)
            body = payload if kind else str(data.get('body', '')).strip()[:MAX_MESSAGE]
            if not body:
                return _fail('Type a reply first.')
            # The page retries unsent replies; the same client id never makes a second copy.
            cid = re.sub(r'[^A-Za-z0-9_-]', '', str(data.get('cid', '')))[:40]
            cid_key = f'chats-sxcid-{user.pk}-{cid}'
            earlier = cid and ChatMessage.objects.filter(pk=cache.get(cid_key) or 0, user=user).first()
            if earlier:
                return JsonResponse({'ok': True, 'message': _message_json(earlier)})
            message = ChatMessage.objects.create(user=user, sender=ChatMessage.SENDER_ADMIN, body=body,
                                                 kind=kind or ChatMessage.KIND_TEXT)
            set_live('typing', f's{user.pk}', 'staff', False)
            if cid:
                cache.set(cid_key, message.pk, 24 * 3600)
        unread.update(read_by_admin=True)   # replying answers everything sent so far
        return JsonResponse({'ok': True, 'message': _message_json(message)})

    try:
        after = int(request.GET.get('after') or 0)
    except ValueError:
        after = 0
    if after:
        rows = list(user.messages.filter(pk__gt=after).order_by('pk')[:200])
    else:   # first open: the latest part of the conversation
        rows = list(user.messages.order_by('-pk')[:INBOX_SIZE])[::-1]
    if request.GET.get('here'):   # this chat is the one open on the support screen
        set_live('here', f's{user.pk}', 'staff')
        unread.update(read_by_admin=True)
    data = {
        'ok': True, 'messages': [_message_json(m) for m in rows],
        'seen_upto': _read_upto(user, ChatMessage.SENDER_ADMIN) if user.read_receipts else 0,
        'person': _person(user), 'locations': _live_locations(user),
        'call': _public_call(_call_state(user), 'admin'),
        'typing': is_live('typing', f's{user.pk}', 'user'), 'here': is_live('here', f's{user.pk}', 'user'),
    }
    if not after or request.GET.get('contact'):
        data['contact'] = _contact(user)
    return JsonResponse(data)


def api_inbox_call(request, pk):
    """Voice / video calls with a member, from the support side."""
    me = staff_account(request)
    if not me:
        return _fail('Only the support team can call from the inbox.', 403)
    user = ChatUser.objects.filter(pk=pk).exclude(pk=me.pk).first()
    if not user:
        return _fail('This chat is not available.', 404)
    touch_staff()
    if request.method == 'POST':
        state, error = call_action(user, 'admin', _json_body(request))
        if error:
            return _fail(error, 409)
        return JsonResponse({'ok': True, 'call': _public_call(state, 'admin'), 'ice_servers': ice_servers()})
    return JsonResponse({'ok': True, 'call': _public_call(_call_state(user), 'admin'), 'ice_servers': ice_servers()})
