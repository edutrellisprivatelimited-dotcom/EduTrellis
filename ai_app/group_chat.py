"""EduChats groups — like WhatsApp groups: a name, photo and description,
members found by username, admins who can add / remove people and change
the group settings, and grey "Rahul added Muskan" lines for every change.

Same accounts, send-rate limit and attachment rules as direct chats.
"""
import os
import re
import secrets

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Min
from django.http import FileResponse, Http404, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ChatGroup, ChatUser, GroupMember, GroupMessage
from .support_chat import (
    MAX_MESSAGE, SEND_LIMIT_ERROR, over_send_limit, _check_photo, _fail, _json_body, _presence, current_user, is_live, set_live,
)

MAX_MEMBERS = 256
NEW_GROUP_LIMIT = 20          # groups created per day, per account


def _me(request):
    user = current_user(request)
    if not user:
        return None, _fail('Please log in again.', 401)
    if user.is_guest:
        return None, _fail('Sign up or log in to use groups.', 403)
    return user, None


def _membership(me, group_id):
    try:
        group_id = int(group_id)
    except (TypeError, ValueError):
        return None
    return GroupMember.objects.filter(user=me, group_id=group_id).select_related('group').first()


def _first(name):
    return (name or '').split(' ')[0] or name


def _system(group, text):
    message = GroupMessage.objects.create(group=group, kind='system', body=text[:500])
    ChatGroup.objects.filter(pk=group.pk).update(updated_at=message.created_at)
    return message


def _names(users):
    names = [u.name for u in users]
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def _photo_url(group):
    if not group.photo:
        return ''
    return reverse('chats_group_photo', args=[group.pk]) + '?v=' + os.path.basename(group.photo.name)[:16]


def _message_json(message, me, names=None):
    data = {
        'id': message.pk, 'kind': message.kind, 'body': message.body,
        'mine': message.sender_id == me.pk, 'sender': message.sender_id,
        'name': (names or {}).get(message.sender_id) or (message.sender.name if message.sender_id and message.sender else ''),
        'at': timezone.localtime(message.created_at).isoformat(),
    }
    if message.attachment:
        data['url'] = reverse('chats_group_file', args=[message.pk])
        data['file'] = message.attachment_name
    return data


def _read_by_all(group, me):
    """Newest message id every other member has seen (blue ticks in a group)."""
    low = group.members.exclude(user=me).aggregate(m=Min('last_read'))['m']
    return low or 0


def _typing(group, me):
    ids = [m.user_id for m in group.members.exclude(user=me).only('user_id')]
    live = [i for i in ids if is_live('typing', f'g{group.pk}', i)]
    if not live:
        return []
    return [_first(u.name) for u in ChatUser.objects.filter(pk__in=live[:3])]


def _group_json(group, membership, last=None, unread=0, me=None):
    data = {
        'id': group.pk, 'name': group.name, 'description': group.description, 'photo': _photo_url(group),
        'initial': (group.name[:1] or '#').upper(),
        'members': getattr(group, 'n_members', None) or group.members.count(),
        'is_admin': membership.is_admin,
        'only_admins_send': group.only_admins_send, 'only_admins_edit': group.only_admins_edit,
        'can_send': membership.is_admin or not group.only_admins_send,
        'can_edit': membership.is_admin or not group.only_admins_edit,
        'unread': unread,
        'updated_at': timezone.localtime(group.updated_at).isoformat(),
        'last': None,
    }
    if last:
        data['last'] = _message_json(last, me or membership.user)
    return data


# ── list + create ────────────────────────────────────────────────────────────

def api_groups(request):
    me, error = _me(request)
    if error:
        return error
    if request.method == 'POST':
        return _create(request, me)
    rows = []
    memberships = (GroupMember.objects.filter(user=me).select_related('group')
                   .annotate(n_members=Count('group__members')).order_by('-group__updated_at')[:100])
    for ms in memberships:
        group = ms.group
        group.n_members = ms.n_members
        visible = group.messages.filter(pk__gt=ms.cleared_upto)
        last = visible.select_related('sender').order_by('-pk').first()
        unread = visible.filter(pk__gt=ms.last_read).exclude(sender=me).exclude(kind='system').count()
        data = _group_json(group, ms, last, unread, me)
        data['typing'] = _typing(group, me)
        rows.append(data)
    return JsonResponse({'ok': True, 'groups': rows})


def _create(request, me):
    key = f'chats-newgroup-{me.pk}'
    if cache.get(key, 0) >= NEW_GROUP_LIMIT:
        return _fail("You've made a lot of groups today. Please try again tomorrow.", 429)
    data = request.POST if request.content_type.startswith('multipart') else _json_body(request)
    name = re.sub(r'\s+', ' ', str(data.get('name', ''))).strip()[:100]
    if not name:
        return _fail('Give your group a name.', field='name')
    raw = data.get('members', '')
    usernames = raw if isinstance(raw, list) else re.split(r'[\s,]+', str(raw))
    usernames = list(dict.fromkeys(u.strip().lstrip('@').lower() for u in usernames if u and u.strip()))[:MAX_MEMBERS]
    people = list(ChatUser.objects.filter(username__in=usernames, is_guest=False, is_active=True).exclude(pk=me.pk))
    if not people:
        return _fail('Add at least one person to the group.', field='members')
    photo = request.FILES.get('photo')
    ext = ''
    if photo:
        ext, problem = _check_photo(photo)
        if problem:
            return _fail(problem, field='photo')
    with transaction.atomic():
        group = ChatGroup.objects.create(name=name, description=str(data.get('description', '')).strip()[:500], created_by=me)
        if photo:
            group.photo.save(secrets.token_hex(8) + ext, photo, save=True)
        GroupMember.objects.create(group=group, user=me, is_admin=True, added_by=me)
        GroupMember.objects.bulk_create([GroupMember(group=group, user=u, added_by=me) for u in people])
        _system(group, f'{me.name} created the group "{name}"')
        last = _system(group, f'{me.name} added {_names(people)}')
        GroupMember.objects.filter(group=group, user=me).update(last_read=last.pk)
    cache.set(key, cache.get(key, 0) + 1, 24 * 3600)
    ms = GroupMember.objects.select_related('group').get(group=group, user=me)
    return JsonResponse({'ok': True, 'group': _group_json(ms.group, ms, last, 0, me)})


# ── messages ─────────────────────────────────────────────────────────────────

def api_group_messages(request, group_id):
    me, error = _me(request)
    if error:
        return error
    ms = _membership(me, group_id)
    if not ms:
        return _fail("You're not in this group any more.", 404)
    group = ms.group
    if request.method == 'POST':
        if not (ms.is_admin or not group.only_admins_send):
            return _fail('Only admins can send messages in this group.', 403)
        from .educhats_media import media_from
        data = _json_body(request)
        kind, payload = media_from(data)   # a sticker or GIF instead of text
        if kind is None:
            return _fail(payload)
        body = payload if kind else str(data.get('body', '')).strip()[:MAX_MESSAGE]
        if not body:
            return _fail('Type a message first.')
        cid = re.sub(r'[^A-Za-z0-9_-]', '', str(data.get('cid', '')))[:40]
        cid_key = f'chats-gcid-{me.pk}-{cid}'
        if cid:
            earlier = GroupMessage.objects.filter(pk=cache.get(cid_key) or 0, sender=me).first()
            if earlier:
                return JsonResponse({'ok': True, 'message': _message_json(earlier, me)})
        if over_send_limit(me):
            return _fail(SEND_LIMIT_ERROR, 429)
        message = GroupMessage.objects.create(group=group, sender=me, body=body, kind=kind or 'text')
        ChatGroup.objects.filter(pk=group.pk).update(updated_at=message.created_at)
        GroupMember.objects.filter(pk=ms.pk).update(last_read=message.pk)
        set_live('typing', f'g{group.pk}', me.pk, False)
        if cid:
            cache.set(cid_key, message.pk, 24 * 3600)
        return JsonResponse({'ok': True, 'message': _message_json(message, me)})

    try:
        after = int(request.GET.get('after') or 0)
    except ValueError:
        after = 0
    rows = list(group.messages.filter(pk__gt=max(after, ms.cleared_upto)).select_related('sender').order_by('pk')[:300])
    newest = group.messages.order_by('-pk').values_list('pk', flat=True).first() or 0
    if newest > ms.last_read:
        GroupMember.objects.filter(pk=ms.pk).update(last_read=newest)
        ms.last_read = newest
    return JsonResponse({
        'ok': True, 'messages': [_message_json(m, me) for m in rows],
        'read_upto': _read_by_all(group, me), 'typing': _typing(group, me),
        'group': _group_json(group, ms, rows[-1] if rows else None, 0, me),
    })


def api_group_upload(request, group_id):
    from .support_chat import MAX_UPLOAD_MB, upload_cid_key, upload_kind
    if request.method != 'POST':
        return _fail('Send a file.', 405)
    me, error = _me(request)
    if error:
        return error
    ms = _membership(me, group_id)
    if not ms:
        return _fail("You're not in this group any more.", 404)
    if not (ms.is_admin or not ms.group.only_admins_send):
        return _fail('Only admins can send messages in this group.', 403)
    key = upload_cid_key(request, f'g{ms.group_id}-{me.pk}')
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
    message = GroupMessage(group=ms.group, sender=me, kind=kind, body=caption,
                           attachment_name=('Voice message' + ext) if kind == 'voice' else os.path.basename(upload.name)[:200])
    upload.name = secrets.token_hex(12) + ext
    message.attachment = upload
    message.save()
    ChatGroup.objects.filter(pk=ms.group_id).update(updated_at=message.created_at)
    GroupMember.objects.filter(pk=ms.pk).update(last_read=message.pk)
    data = {'ok': True, 'message': _message_json(message, me)}
    if key:
        cache.set(key, data['message'], 6 * 3600)
    return JsonResponse(data)


# ── info, settings, members ──────────────────────────────────────────────────

def _member_json(m, me):
    u = m.user
    return {
        'id': u.pk, 'name': u.name, 'username': u.username or '', 'initial': (u.name[:1] or '?').upper(),
        'photo': reverse('chats_user_photo', args=[u.pk]) if u.photo else '',
        'bio': u.bio if u.show_bio else '', 'admin': m.is_admin, 'me': u.pk == me.pk,
        'online': bool(u.show_last_seen and _presence(u.last_seen_at)['online']),
    }


def _info(ms, me):
    group = ms.group
    members = list(group.members.select_related('user').order_by('-is_admin', 'joined_at'))
    members.sort(key=lambda m: (not m.user_id == me.pk, not m.is_admin))
    data = _group_json(group, ms, None, 0, me)
    data.update({
        'created_by': group.created_by.name if group.created_by_id and group.created_by else '',
        'created_at': timezone.localtime(group.created_at).strftime('%d %b %Y'),
        'member_list': [_member_json(m, me) for m in members],
    })
    return data


def api_group_info(request, group_id):
    me, error = _me(request)
    if error:
        return error
    ms = _membership(me, group_id)
    if not ms:
        return _fail("You're not in this group any more.", 404)
    return JsonResponse({'ok': True, 'group': _info(ms, me)})


@require_POST
def api_group_update(request, group_id):
    """Name / description / photo (admins, or everyone unless "only admins edit"), and the two settings (admins)."""
    me, error = _me(request)
    if error:
        return error
    ms = _membership(me, group_id)
    if not ms:
        return _fail("You're not in this group any more.", 404)
    group, data = ms.group, request.POST
    can_edit = ms.is_admin or not group.only_admins_edit
    notes = []
    if 'name' in data or 'description' in data or 'photo' in request.FILES or data.get('remove_photo'):
        if not can_edit:
            return _fail('Only admins can change the group info.', 403)
    if 'name' in data:
        name = re.sub(r'\s+', ' ', data.get('name', '')).strip()[:100]
        if not name:
            return _fail('Give your group a name.', field='name')
        if name != group.name:
            group.name = name
            notes.append(f'{me.name} changed the group name to "{name}"')
    if 'description' in data:
        description = data.get('description', '').strip()[:500]
        if description != group.description:
            group.description = description
            notes.append(f'{me.name} changed the group description')
    photo = request.FILES.get('photo')
    if photo:
        ext, problem = _check_photo(photo)
        if problem:
            return _fail(problem, field='photo')
    if (photo or data.get('remove_photo')) and group.photo:
        try:
            group.photo.delete(save=False)
        except OSError:
            group.photo = None
        if not photo:
            notes.append(f"{me.name} removed the group photo")
    if photo:
        group.photo.save(secrets.token_hex(8) + ext, photo, save=False)
        notes.append(f'{me.name} changed the group photo')
    for field, on_text, off_text in (
            ('only_admins_send', 'only admins can send messages', 'all members can send messages'),
            ('only_admins_edit', 'only admins can edit the group info', 'all members can edit the group info')):
        if field in data:
            if not ms.is_admin:
                return _fail('Only admins can change group settings.', 403)
            value = data.get(field) in ('1', 'true', 'on')
            if value != getattr(group, field):
                setattr(group, field, value)
                notes.append(f'{me.name} changed this group\'s settings so {on_text if value else off_text}')
    group.updated_at = timezone.now()
    group.save()
    for note in notes:
        _system(group, note)
    ms.group = group
    return JsonResponse({'ok': True, 'group': _info(ms, me)})


@require_POST
def api_group_members(request, group_id):
    """{action: add|remove|admin|dismiss, usernames: [...]} or {action, user: id} — admins only."""
    me, error = _me(request)
    if error:
        return error
    ms = _membership(me, group_id)
    if not ms:
        return _fail("You're not in this group any more.", 404)
    if not ms.is_admin:
        return _fail('Only group admins can do that.', 403)
    group, data = ms.group, _json_body(request)
    action = data.get('action')
    if action == 'add':
        usernames = [str(u).strip().lstrip('@').lower() for u in (data.get('usernames') or [])][:MAX_MEMBERS]
        already = set(group.members.values_list('user_id', flat=True))
        people = [u for u in ChatUser.objects.filter(username__in=usernames, is_guest=False, is_active=True) if u.pk not in already]
        if not people:
            return _fail('Those people are already in the group.')
        if len(already) + len(people) > MAX_MEMBERS:
            return _fail(f'Groups can have up to {MAX_MEMBERS} members.')
        GroupMember.objects.bulk_create([GroupMember(group=group, user=u, added_by=me) for u in people])
        _system(group, f'{me.name} added {_names(people)}')
    else:
        target = group.members.select_related('user').filter(user_id=data.get('user')).first()
        if not target:
            return _fail('That person is not in this group.', 404)
        if target.user_id == me.pk:
            return _fail('Use "Exit group" to leave.', 400)
        if action == 'remove':
            target.delete()
            _system(group, f'{me.name} removed {target.user.name}')
        elif action in ('admin', 'dismiss'):
            target.is_admin = action == 'admin'
            target.save(update_fields=['is_admin'])
            if action == 'admin':
                _system(group, f'{me.name} made {target.user.name} a group admin')
        else:
            return _fail('Unknown action.', 400)
    return JsonResponse({'ok': True, 'group': _info(ms, me)})


@require_POST
def api_group_leave(request, group_id):
    me, error = _me(request)
    if error:
        return error
    ms = _membership(me, group_id)
    if not ms:
        return JsonResponse({'ok': True})
    group = ms.group
    with transaction.atomic():
        ms.delete()
        rest = group.members.order_by('joined_at')
        if not rest.exists():
            _delete_group(group)
            return JsonResponse({'ok': True})
        _system(group, f'{me.name} left')
        if ms.is_admin and not rest.filter(is_admin=True).exists():   # never leave a group without an admin
            heir = rest.select_related('user').first()
            heir.is_admin = True
            heir.save(update_fields=['is_admin'])
            _system(group, f'{heir.user.name} is now an admin')
    return JsonResponse({'ok': True})


def _delete_group(group):
    for m in group.messages.exclude(attachment=''):
        try:
            m.attachment.delete(save=False)
        except OSError:
            pass
    if group.photo:
        try:
            group.photo.delete(save=False)
        except OSError:
            pass
    group.delete()


# ── files ────────────────────────────────────────────────────────────────────

def _member_or_admin(request, group_id):
    me = current_user(request)
    if request.user.is_authenticated and request.user.is_superuser:
        return True
    return bool(me and GroupMember.objects.filter(group_id=group_id, user=me).exists())


def group_photo(request, group_id):
    from .support_chat import PHOTO_TYPES
    group = ChatGroup.objects.filter(pk=group_id).first()
    if not group or not group.photo or not _member_or_admin(request, group.pk):
        raise Http404
    ext = os.path.splitext(group.photo.name)[1].lower()
    try:
        handle = group.photo.open('rb')
    except FileNotFoundError:
        raise Http404
    response = FileResponse(handle, content_type=PHOTO_TYPES.get(ext, 'image/jpeg'))
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=3600'
    return response


def group_file(request, pk):
    import mimetypes
    from .support_chat import _INLINE_TYPES
    message = GroupMessage.objects.filter(pk=pk).first()
    if not message or not message.attachment or not _member_or_admin(request, message.group_id):
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


def shares_group(a, b):
    """True when two chat accounts are in a group together (they can see each other's photos)."""
    if not a or not b:
        return False
    return GroupMember.objects.filter(user=a, group__members__user=b).exists()
