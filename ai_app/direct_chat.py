"""EduChats direct messages — signed-up chat accounts find each other by
username (the + button on /educhats/) and message one-to-one.

Text only for now. Same accounts, session and send-rate limit as the support
chat in support_chat.py; guests have to sign up first.
"""
import re
import secrets

from django.core.cache import cache
from django.db.models import Count, Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .educhats_social import SHOW_FIELDS, socials_json
from .models import ChatUser, DirectMessage, DirectThread
from .support_chat import (
    ATTEMPT_WINDOW, CALL_RING_SECONDS, CALL_STALE_SECONDS, MAX_MESSAGE, SEND_LIMIT_ERROR, clean_flags, ice_servers,
    over_send_limit, _fail,
    _json_body, _presence, current_user, is_live, set_live,
)

SEARCH_LIMIT = 300            # username searches per 15 min, per account
NEW_THREAD_LIMIT = 30         # new people messaged per hour, per account


def _me(request):
    user = current_user(request)
    if not user:
        return None, _fail('Please log in again.', 401)
    if user.is_guest:
        return None, _fail('Sign up or log in to message people by username.', 403)
    return user, None


def _peer_json(peer, shares_thread=True):
    return {
        'id': peer.pk, 'name': peer.name, 'username': peer.username or '',
        'initial': (peer.name[:1] or '?').upper(),
        # Pictures are only served to people who share a thread (see support_chat.user_photo).
        'photo': reverse('chats_user_photo', args=[peer.pk]) if shares_thread and peer.photo else '',
        'bio': peer.bio if peer.show_bio else '',
        'cover': reverse('chats_user_cover', args=[peer.pk]) if shares_thread and peer.cover else '',
        'active': peer.is_active,
        'joined': timezone.localtime(peer.created_at).strftime('%B %Y'),
    }


def _message_json(message, me):
    from .educhats_share import location_json, once_json
    data = {
        'id': message.pk, 'mine': message.sender_id == me.pk, 'body': message.body, 'kind': message.kind,
        'at': timezone.localtime(message.created_at).isoformat(), 'read': bool(message.read_at),
        **({'url': reverse('chats_dm_file', args=[message.pk]), 'name': message.attachment_name}
           if message.attachment and not message.view_once else {}),
    }
    if message.view_once:
        data.update(once_json(message, 'd', message.opened_at))
    if message.kind == 'location' and message.latitude is not None:
        data.update(location_json(message))
    return data


def _receipts(me, peer):
    """Blue ticks show only when both people have read receipts on (like WhatsApp)."""
    return me.read_receipts and peer.read_receipts


def _peer_presence(peer):
    """Online / last seen — unless they've hidden it in Privacy."""
    if not peer.show_last_seen:
        return {'online': False, 'last_seen': None, 'hidden': True}
    return _presence(peer.last_seen_at)


def _activity(thread, peer, kind):
    """Their "typing…" / "is here" in this chat, if they share it and nobody is blocked."""
    return bool(peer.show_activity and not thread.blocked_by_id and is_live(kind, f'd{thread.pk}', peer.pk))


def _thread_json(thread, me, last=None, unread=0):
    peer = thread.other(me)
    last_json = _message_json(last, me) if last else None
    if last_json and not _receipts(me, peer):
        last_json['read'] = False
    return {
        'id': thread.pk, 'peer': _peer_json(peer), 'presence': _peer_presence(peer),
        'last': last_json, 'unread': unread,
        'blocked': bool(thread.blocked_by_id), 'blocked_by_me': thread.blocked_by_id == me.pk,
        'updated_at': timezone.localtime(thread.updated_at).isoformat(),
    }


def _my_thread(me, thread_id):
    return (DirectThread.objects.filter(Q(user_a=me) | Q(user_b=me), pk=thread_id)
            .select_related('user_a', 'user_b').first())


def shares_thread(a, b):
    """True when two chat accounts have a direct thread together."""
    if not a or not b:
        return False
    low, high = sorted([a.pk, b.pk])
    return DirectThread.objects.filter(user_a_id=low, user_b_id=high).exists()


def api_user_search(request):
    me, error = _me(request)
    if error:
        return error
    key = f'chats-usearch-{me.pk}'
    count = cache.get(key, 0)
    if count >= SEARCH_LIMIT:
        return _fail('Too many searches. Please wait a few minutes.', 429)
    cache.set(key, count + 1, ATTEMPT_WINDOW)
    q = request.GET.get('q', '').strip().lstrip('@').lower()[:30]
    if len(q) < 2:
        return JsonResponse({'ok': True, 'users': []})
    found = list(ChatUser.objects.filter(is_guest=False, is_active=True, username__istartswith=q)
                 .exclude(pk=me.pk).order_by('username')[:12])
    found.sort(key=lambda u: (u.username != q, len(u.username or '')))
    return JsonResponse({'ok': True, 'users': [
        {'name': u.name, 'username': u.username, 'initial': (u.name[:1] or '?').upper(),
         'bio': u.bio if u.show_bio else ''} for u in found
    ]})


def api_threads(request):
    me, error = _me(request)
    if error:
        return error
    threads = (DirectThread.objects.filter(Q(user_a=me) | Q(user_b=me))
               .annotate(total=Count('messages'))
               .filter(Q(total__gt=0) | Q(started_by=me))
               .select_related('user_a', 'user_b').order_by('-updated_at')[:100])
    rows = []
    for thread in threads:
        visible = thread.messages.filter(pk__gt=thread.cleared_upto(me))
        last = visible.order_by('-pk').first()
        if thread.total and not last:
            continue   # deleted for me — comes back with the next message
        unread = visible.filter(read_at__isnull=True).exclude(sender=me).count()
        row = _thread_json(thread, me, last, unread)
        row['typing'] = _activity(thread, thread.other(me), 'typing')
        rows.append(row)
    return JsonResponse({'ok': True, 'threads': rows})


@require_POST
def api_start(request):
    me, error = _me(request)
    if error:
        return error
    username = str(_json_body(request).get('username', '')).strip().lstrip('@').lower()[:30]
    peer = ChatUser.objects.filter(username__iexact=username, is_guest=False, is_active=True).first() if username else None
    if not peer:
        return _fail('No one on EduChats has that username.', 404)
    if peer.pk == me.pk:
        return _fail("That's you — pick someone else to message.")
    low, high = sorted([me.pk, peer.pk])
    thread = DirectThread.objects.filter(user_a_id=low, user_b_id=high).first()
    if not thread:
        key = f'chats-newdm-{me.pk}'
        made = cache.get(key, 0)
        if made >= NEW_THREAD_LIMIT:
            return _fail('You have started a lot of new chats. Please wait a while.', 429)
        cache.set(key, made + 1, 3600)
        thread = DirectThread.objects.create(user_a_id=low, user_b_id=high, started_by=me)
    thread = _my_thread(me, thread.pk)
    return JsonResponse({'ok': True, 'thread': _thread_json(thread, me, thread.messages.order_by('-pk').first())})


def api_thread_messages(request, thread_id):
    me, error = _me(request)
    if error:
        return error
    thread = _my_thread(me, thread_id)
    if not thread:
        return _fail('This chat is not available.', 404)
    peer = thread.other(me)
    if request.method == 'POST':
        if thread.blocked_by_id:
            return _fail('Unblock this person to send a message.' if thread.blocked_by_id == me.pk
                         else "You can't message this person.", 403)
        if not peer.is_active:
            return _fail('This account is not available any more.', 403)
        data = _json_body(request)
        from .educhats_media import media_from
        kind, payload = media_from(data)   # a sticker or GIF instead of text
        if kind is None:
            return _fail(payload)
        body = payload if kind else str(data.get('body', '')).strip()[:MAX_MESSAGE]
        if not body:
            return _fail('Type a message first.')
        # Retries of the same message (same client id) never make a second copy.
        cid = re.sub(r'[^A-Za-z0-9_-]', '', str(data.get('cid', '')))[:40]
        cid_key = f'chats-dmcid-{me.pk}-{cid}'
        if cid:
            earlier = DirectMessage.objects.filter(pk=cache.get(cid_key) or 0, sender=me).first()
            if earlier:
                return JsonResponse({'ok': True, 'message': _message_json(earlier, me)})
        if over_send_limit(me):
            return _fail(SEND_LIMIT_ERROR, 429)
        message = DirectMessage.objects.create(thread=thread, sender=me, body=body, kind=kind or 'text')
        set_live('typing', f'd{thread.pk}', me.pk, False)
        DirectThread.objects.filter(pk=thread.pk).update(updated_at=message.created_at)
        if cid:
            cache.set(cid_key, message.pk, 24 * 3600)
        return JsonResponse({'ok': True, 'message': _message_json(message, me)})
    try:
        after = int(request.GET.get('after') or 0)
    except ValueError:
        after = 0
    rows = list(thread.messages.filter(pk__gt=max(after, thread.cleared_upto(me))).order_by('pk')[:300])
    if request.GET.get('quiet') != '1':   # "Mark read" from the list doesn't count as being in the chat
        set_live('here', f'd{thread.pk}', me.pk)   # polled only while this chat is open on screen
    # The page only polls the open chat while it's on screen: loading = seeing.
    thread.messages.filter(read_at__isnull=True).exclude(sender=me).update(read_at=timezone.now())
    receipts = _receipts(me, peer)
    read_upto = (thread.messages.filter(sender=me, read_at__isnull=False)
                 .order_by('-pk').values_list('pk', flat=True).first() or 0) if receipts else 0
    messages = [_message_json(m, me) for m in rows]
    if not receipts:
        for m in messages:
            m['read'] = False
    from .educhats_share import live_locations
    return JsonResponse({
        'ok': True, 'messages': messages, 'read_upto': read_upto, 'locations': live_locations(thread.messages),
        'thread': _thread_json(thread, me),
        'peer_typing': _activity(thread, peer, 'typing'),
        'peer_here': _activity(thread, peer, 'here'),
    })


@require_POST
def api_thread_block(request, thread_id):
    me, error = _me(request)
    if error:
        return error
    thread = _my_thread(me, thread_id)
    if not thread:
        return _fail('This chat is not available.', 404)
    if _json_body(request).get('block'):
        if not thread.blocked_by_id:
            thread.blocked_by = me
            thread.save(update_fields=['blocked_by'])
    elif thread.blocked_by_id == me.pk:
        thread.blocked_by = None
        thread.save(update_fields=['blocked_by'])
    return JsonResponse({'ok': True, 'thread': _thread_json(thread, me)})


def api_thread_contact(request, thread_id):
    """Contact info for the person in a direct chat — only what their Privacy settings share."""
    me, error = _me(request)
    if error:
        return error
    thread = _my_thread(me, thread_id)
    if not thread:
        return _fail('This chat is not available.', 404)
    peer = thread.other(me)
    return JsonResponse({'ok': True, 'contact': {
        **_peer_json(peer), 'presence': _peer_presence(peer),
        'phone': peer.phone if peer.show_phone else '',
        'email': peer.email if peer.show_email else '',
        'ip': (peer.last_ip or peer.ip) if peer.show_ip else '',
        'city': peer.city, 'state': peer.state,
        'joined': timezone.localtime(peer.created_at).strftime('%d %b %Y'),
        'socials': socials_json(peer),
    }})


PRIVACY_FIELDS = ('show_phone', 'show_email', 'show_ip', 'show_last_seen', 'show_activity', 'read_receipts') + SHOW_FIELDS


def api_privacy(request):
    """Read or save the ⋮ → Privacy switches."""
    me, error = _me(request)
    if error:
        return error
    if request.method == 'POST':
        data = _json_body(request)
        for field in PRIVACY_FIELDS:
            if field in data:
                setattr(me, field, bool(data[field]))
        if data.get('tick_style') in dict(ChatUser.TICK_CHOICES):
            me.tick_style = data['tick_style']
        me.save(update_fields=list(PRIVACY_FIELDS) + ['tick_style'])
    privacy = {field: getattr(me, field) for field in PRIVACY_FIELDS}
    privacy['tick_style'] = me.tick_style
    return JsonResponse({'ok': True, 'privacy': privacy})


# ⋮ → Customize. Preset keys only; a custom wallpaper photo stays on the device.
APPEARANCE_CHOICES = {
    'accent': {'red', 'blue', 'green', 'purple', 'orange', 'pink', 'teal', 'black', 'indigo', 'cyan', 'sky', 'lime', 'amber',
               'saffron', 'coral', 'crimson', 'sakura', 'magenta', 'neon', 'aurora', 'gold', 'coffee', 'slate', 'matrix'},
    'font': {'inter', 'poppins', 'nunito', 'dmsans', 'merriweather', 'mono'},
    'size': {'s', 'm', 'l'},
    'wall': {'doodle', 'plain', 'sunset', 'ocean', 'mint', 'night', 'dots', 'grid', 'custom', 'peach', 'lavender', 'paper',
             'blossom', 'waves', 'hearts', 'tiranga', 'forest', 'aurora', 'galaxy', 'carbon', 'royal', 'matrix', 'frost'},
    # ⋮ → Themes, and the message colours in Customize
    'theme': {'classic', 'ocean', 'forest', 'sunset', 'midnight', 'royal', 'neon', 'sakura', 'aurora', 'tiranga',
              'lavender', 'coffee', 'matrix', 'frost'},
    'bubble': {'theme', 'mint', 'teal', 'blue', 'purple', 'pink', 'sunset', 'gold', 'neon', 'aurora', 'saffron', 'dark', 'sky', 'lavender',
               'coffee', 'matrix', 'ice'},
    'bubble2': {'theme', 'grey', 'cream', 'mint', 'sky', 'blush', 'lilac', 'dark', 'charcoal'},
}


@require_POST
def api_appearance(request):
    me, error = _me(request)
    if error:
        return error
    data = _json_body(request)
    look = {key: data[key] for key, allowed in APPEARANCE_CHOICES.items() if data.get(key) in allowed}
    me.appearance = look
    me.save(update_fields=['appearance'])
    return JsonResponse({'ok': True, 'appearance': look})


# ── delete chat (for me) and export ──
def _chat_for(me, chat):
    """('support', None) or ('dm', thread) for a chat key from the page."""
    if chat == 'support':
        return 'support', None
    if chat == 'ai':
        return 'ai', None
    if isinstance(chat, str) and chat.startswith('g'):
        from .group_chat import _membership
        ms = _membership(me, chat[1:]) if not me.is_guest else None
        return ('group', ms) if ms else (None, None)
    try:
        thread = _my_thread(me, int(chat))
    except (TypeError, ValueError):
        thread = None
    return ('dm', thread) if thread else (None, None)


@require_POST
def api_clear(request):
    """Delete a chat for yourself: hides everything sent so far. The other
    person (or the support team) keeps their copy."""
    me = current_user(request)
    if not me:
        return _fail('Please log in again.', 401)
    kind, thread = _chat_for(me, _json_body(request).get('chat'))
    if kind == 'ai':   # your own chat with EduTrellis AI — nobody else has a copy
        me.ai_messages.all().delete()
        return JsonResponse({'ok': True})
    if kind == 'support':
        last = me.messages.order_by('-pk').values_list('pk', flat=True).first() or 0
        ChatUser.objects.filter(pk=me.pk).update(support_cleared_upto=last)
        return JsonResponse({'ok': True})
    if kind == 'group':   # thread is the membership here
        last = thread.group.messages.order_by('-pk').values_list('pk', flat=True).first() or 0
        type(thread).objects.filter(pk=thread.pk).update(cleared_upto=last, last_read=last)
        return JsonResponse({'ok': True})
    if kind != 'dm' or me.is_guest:
        return _fail('This chat is not available.', 404)
    last = thread.messages.order_by('-pk').values_list('pk', flat=True).first() or 0
    field = 'a_cleared_upto' if thread.user_a_id == me.pk else 'b_cleared_upto'
    DirectThread.objects.filter(pk=thread.pk).update(**{field: last})
    return JsonResponse({'ok': True})


def _support_line(m, me_name, support_name):
    from .models import ChatMessage
    who = me_name if m.sender == ChatMessage.SENDER_USER else support_name
    if m.kind == ChatMessage.KIND_LOCATION and m.latitude is not None:
        body = f'[Location] https://maps.google.com/?q={m.latitude},{m.longitude}'
    elif m.kind in (ChatMessage.KIND_IMAGE, ChatMessage.KIND_VIDEO, ChatMessage.KIND_FILE):
        label = {'image': 'Photo', 'video': 'Video', 'file': 'File'}[m.kind]
        body = f'[{label}{": " + m.attachment_name if m.attachment_name else ""}]' + (f' {m.body}' if m.body else '')
    elif m.kind == ChatMessage.KIND_CALL:
        body = f'[Call] {m.body}'
    elif m.kind == ChatMessage.KIND_VOICE:
        body = f'[Voice message {m.body}]'
    elif m.kind in (ChatMessage.KIND_STICKER, ChatMessage.KIND_GIF):
        body = '[Sticker]' if m.kind == ChatMessage.KIND_STICKER else f'[GIF] {m.body}'
    else:
        body = m.body
    return m.created_at, who, m.sender == ChatMessage.SENDER_USER, body


def api_export(request):
    """Download a chat as a .txt file, or open a print-ready page (Save as PDF)."""
    from django.http import HttpResponse
    from django.shortcuts import render
    from .models import SupportProfile
    me = current_user(request)
    if not me:
        return _fail('Please log in again.', 401)
    kind, thread = _chat_for(me, request.GET.get('chat'))
    if kind == 'support':
        support_name = SupportProfile.load().display_name
        title = f'Chat with {support_name}'
        lines = [_support_line(m, me.name, support_name)
                 for m in me.messages.filter(pk__gt=me.support_cleared_upto).order_by('pk')]
    elif kind == 'ai':
        title = 'Chat with EduTrellis AI'
        lines = [(m.created_at, me.name if m.role == 'user' else 'EduTrellis AI', m.role == 'user',
                  m.body + (f' [Picture: {request.build_absolute_uri(m.image_url)}]' if m.image_url else ''))
                 for m in me.ai_messages.order_by('pk')]
    elif kind == 'dm' and not me.is_guest:
        peer = thread.other(me)
        title = f'Chat with {peer.name} (@{peer.username})'
        lines = [(m.created_at, me.name if m.sender_id == me.pk else peer.name, m.sender_id == me.pk, m.summary)
                 for m in thread.messages.filter(pk__gt=thread.cleared_upto(me)).order_by('pk')]
    elif kind == 'group':
        group = thread.group
        title = f'Group: {group.name}'
        lines = [(m.created_at, (m.sender.name if m.sender_id and m.sender else 'EduChats'), m.sender_id == me.pk,
                  m.summary if m.kind != 'system' else f'— {m.body} —')
                 for m in group.messages.filter(pk__gt=thread.cleared_upto).select_related('sender').order_by('pk')]
    else:
        return _fail('This chat is not available.', 404)
    now = timezone.localtime()
    rows = [{'at': timezone.localtime(at), 'who': who, 'mine': mine, 'body': body} for at, who, mine, body in lines]
    stamp = now.strftime('%Y-%m-%d')
    slug = re.sub(r'[^A-Za-z0-9]+', '-', title).strip('-')[:60] or 'chat'
    if request.GET.get('format') == 'txt':
        out = [f'EduChats — {title}', f'Exported {now.strftime("%d %b %Y, %I:%M %p")} · {len(rows)} message{"" if len(rows) == 1 else "s"}', '']
        out += [f'[{r["at"].strftime("%d/%m/%Y, %I:%M %p")}] {r["who"]}: {r["body"]}' for r in rows]
        response = HttpResponse('\n'.join(out) + '\n', content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="EduChats-{slug}-{stamp}.txt"'
        return response
    return render(request, 'chats_export.html', {'title': title, 'rows': rows, 'now': now, 'me': me})


# ── voice / video calls in a direct chat ─────────────────────────────────────
# Same WebRTC flow as the support chat (support_chat.call_action): the server
# only passes offer / answer / ICE between the two browsers through the cache.
# A side is the chat user's pk as a string; the person being called finds out
# from a short-lived "ring" key that their chat list checks every few seconds.

def _dm_call_key(thread_id):
    return f'dmcall-{thread_id}'


def _ring_key(user_id):
    return f'dmring-{user_id}'


def _dm_call_state(thread):
    state = cache.get(_dm_call_key(thread.pk))
    if state and state['status'] == 'ringing' and timezone.now().timestamp() - state['started'] > CALL_RING_SECONDS:
        state = _dm_end_call(thread, state, 'missed')
    return state


def _dm_end_call(thread, state, reason):
    if state['status'] == 'ended':
        return state
    state.update(status='ended', reason=reason, ended=timezone.now().timestamp())
    cache.set(_dm_call_key(thread.pk), state, 120)
    if cache.get(_ring_key(state['callee'])) == thread.pk:
        cache.delete(_ring_key(state['callee']))
    label = 'Video call' if state['kind'] == 'video' else 'Voice call'
    if state.get('answered'):
        seconds = int(state['ended'] - state['answered'])
        body = f'{label} · {seconds // 60}:{seconds % 60:02d}'
    elif reason in ('missed', 'cancelled'):
        body = f'Missed {label.lower()}'
    else:
        body = f'{label} declined'
    message = DirectMessage.objects.create(thread=thread, sender_id=int(state['caller']), kind='call', body=body)
    DirectThread.objects.filter(pk=thread.pk).update(updated_at=message.created_at)
    return state


def _dm_public_call(state, me):
    if not state:
        return None
    side = str(me.pk)
    other = state['callee'] if side == state['caller'] else state['caller']
    return {
        'id': state['id'], 'kind': state['kind'], 'caller': state['caller'], 'status': state['status'],
        'reason': state.get('reason', ''),
        'offer': state.get('offer') if side != state['caller'] else None,
        'answer': state.get('answer') if side == state['caller'] else None,
        'ice': cache.get(f"{_dm_call_key(state['thread'])}-ice-{other}-{state['id']}", []),
        'answered': state.get('answered'),
        'callee': state['callee'], 'room': state.get('room', ''),
        'peer_flags': state.get('flags', {}).get(other, {}),
    }


def api_thread_call(request, thread_id):
    """GET: the call in this chat (if any). POST {action: start|answer|ice|end|decline}."""
    me, error = _me(request)
    if error:
        return error
    thread = _my_thread(me, thread_id)
    if not thread:
        return _fail('This chat is not available.', 404)
    if request.method != 'POST':
        return JsonResponse({'ok': True, 'call': _dm_public_call(_dm_call_state(thread), me), 'ice_servers': ice_servers()})

    data, side = _json_body(request), str(me.pk)
    peer = thread.other(me)
    action, state, now = data.get('action'), _dm_call_state(thread), timezone.now().timestamp()
    if action == 'start':
        if thread.blocked_by_id:
            return _fail("You can't call in this chat.", 403)
        if not peer.is_active:
            return _fail('This account is not available any more.', 403)
        if state and state['status'] in ('ringing', 'active'):
            return _fail('A call is already in progress.', 409)
        ringing_elsewhere = cache.get(_ring_key(peer.pk))
        if ringing_elsewhere and ringing_elsewhere != thread.pk:
            return _fail(f'{peer.name.split(" ")[0]} is getting another call. Please try again in a bit.', 409)
        offer = data.get('offer')
        if not isinstance(offer, dict) or offer.get('type') != 'offer':
            return _fail('Could not start the call.', 409)
        state = {'id': secrets.token_hex(6), 'thread': thread.pk, 'caller': side, 'callee': str(peer.pk),
                 'status': 'ringing', 'kind': 'video' if data.get('kind') == 'video' else 'audio',
                 'offer': offer, 'started': now}
        cache.set(_dm_call_key(thread.pk), state, CALL_STALE_SECONDS)
        cache.set(_ring_key(peer.pk), thread.pk, CALL_RING_SECONDS + 5)
        from .educhats_push import ring
        ring(peer, str(thread.pk), me.name, state['kind'])
    elif not state or state.get('id') != data.get('id'):
        return _fail('This call has ended.', 409)
    elif action == 'answer':
        answer = data.get('answer')
        if state['status'] != 'ringing' or side == state['caller'] or not isinstance(answer, dict):
            return _fail('This call can no longer be answered.', 409)
        state.update(status='active', answer=answer, answered=now)
        cache.set(_dm_call_key(thread.pk), state, CALL_STALE_SECONDS)
        cache.delete(_ring_key(me.pk))
    elif action == 'ice':
        key = f"{_dm_call_key(thread.pk)}-ice-{side}-{state['id']}"
        candidates = cache.get(key, [])
        if isinstance(data.get('candidate'), dict) and len(candidates) < 100:
            candidates.append(data['candidate'])
            cache.set(key, candidates, CALL_STALE_SECONDS)
    elif action == 'flag':   # muted / camera off / recording, shown on the other side
        state.setdefault('flags', {})[side] = clean_flags(data)
        cache.set(_dm_call_key(thread.pk), state, CALL_STALE_SECONDS)
    elif action in ('end', 'decline'):
        reason = ('cancelled' if side == state['caller'] else 'declined') if state['status'] == 'ringing' else 'ended'
        state = _dm_end_call(thread, state, reason)
    else:
        return _fail('Unknown call action.', 400)
    return JsonResponse({'ok': True, 'call': _dm_public_call(state, me), 'ice_servers': ice_servers()})


def api_ring(request):
    """Is anyone calling me right now? The chat list asks every few seconds."""
    me, error = _me(request)
    if error:
        return error
    thread_id = cache.get(_ring_key(me.pk))
    if thread_id:
        thread = _my_thread(me, thread_id)
        state = _dm_call_state(thread) if thread else None
        if state and state['status'] == 'ringing' and state['callee'] == str(me.pk):
            peer = thread.other(me)
            return JsonResponse({'ok': True, 'ring': {'thread': thread.pk, 'kind': state['kind'], 'name': peer.name,
                                                      'photo': _peer_json(peer)['photo']}})
    from .call_rooms import ringing_room
    room = ringing_room(me)   # someone added me to a call with more people
    return JsonResponse({'ok': True, 'ring': room})


# ── photos, videos and files in a direct chat ────────────────────────────────

def api_thread_upload(request, thread_id):
    """POST multipart {file, body?}: same types and 25 MB limit as the support chat."""
    import os
    from .support_chat import MAX_UPLOAD_MB, upload_cid_key, upload_kind
    if request.method != 'POST':
        return _fail('Send a file.', 405)
    me, error = _me(request)
    if error:
        return error
    thread = _my_thread(me, thread_id)
    if not thread:
        return _fail('This chat is not available.', 404)
    if thread.blocked_by_id:
        return _fail("You can't message this person.", 403)
    if not thread.other(me).is_active:
        return _fail('This account is not available any more.', 403)
    key = upload_cid_key(request, f'd{thread.pk}-{me.pk}')
    if key and cache.get(key):
        return JsonResponse({'ok': True, 'message': cache.get(key)})
    if over_send_limit(me):
        return _fail(SEND_LIMIT_ERROR, 429)
    upload = request.FILES.get('file')
    if not upload:
        return _fail('Choose a file to send.')
    ext = os.path.splitext(upload.name)[1].lower()
    kind, caption, error = upload_kind(request, upload)
    if error:
        return _fail(error)
    if upload.size > MAX_UPLOAD_MB * 1024 * 1024:
        return _fail(f'Files can be up to {MAX_UPLOAD_MB} MB.')
    from .educhats_share import wants_once
    message = DirectMessage(thread=thread, sender=me, kind=kind, body=caption, view_once=wants_once(request, kind),
                            attachment_name=('Voice message' + ext) if kind == 'voice' else os.path.basename(upload.name)[:200])
    upload.name = secrets.token_hex(12) + ext   # never trust the uploaded name on disk
    message.attachment = upload
    message.save()
    set_live('typing', f'd{thread.pk}', me.pk, False)
    DirectThread.objects.filter(pk=thread.pk).update(updated_at=message.created_at)
    data = {'ok': True, 'message': _message_json(message, me)}
    if key:
        cache.set(key, data['message'], 6 * 3600)
    return JsonResponse(data)


def dm_attachment(request, pk):
    """Streams a direct-chat attachment to the two people in that chat (or the superuser)."""
    import mimetypes
    import os
    from django.http import FileResponse, Http404
    from .support_chat import _INLINE_TYPES
    message = DirectMessage.objects.filter(pk=pk).select_related('thread').first()
    me = current_user(request)
    admin = request.user.is_authenticated and request.user.is_superuser
    member = me and message and me.pk in (message.thread.user_a_id, message.thread.user_b_id)
    if not message or not message.attachment or not (member or admin):
        raise Http404
    if message.view_once:
        from .educhats_share import once_link_ok
        if not once_link_ok(request, 'd', message.pk):
            raise Http404
    ext = os.path.splitext(message.attachment.name)[1].lower()
    try:
        handle = message.attachment.open('rb')
    except FileNotFoundError:
        raise Http404
    inline = ext in _INLINE_TYPES and not request.GET.get('download')
    response = FileResponse(
        handle, as_attachment=not inline, filename=message.attachment_name or f'file{ext}',
        content_type=_INLINE_TYPES.get(ext) or mimetypes.guess_type(message.attachment_name)[0] or 'application/octet-stream',
    )
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=3600'
    response['Content-Security-Policy'] = "default-src 'none'; img-src 'self'; media-src 'self'; style-src 'unsafe-inline'"
    return response
