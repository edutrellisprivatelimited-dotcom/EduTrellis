"""EduChats' Calls and Updates tabs.

Calls: your call history, read from the call lines the chats already keep
("Video call · 1:07", "Missed voice call"…) in direct chats and the support chat.

Updates: stories — a photo, a video or a coloured text card — that the people
you chat with (a direct chat neither of you has blocked) can see for 24 hours.
You can see who viewed yours, and delete them early.
"""
import os
import re
import secrets
from datetime import timedelta

from django.db.models import Count, Q
from django.http import FileResponse, Http404, JsonResponse
from django.urls import reverse
from django.utils import timezone

from .models import ChatMessage, DirectMessage, DirectThread, Story, StoryView
from .support_chat import _fail, _json_body, current_user, staff_account

STORY_HOURS = 24
STORY_MAX_MB = 25
STORY_LIMIT = 30          # active stories per person
STORY_TYPES = {
    '.jpg': ('image', 'image/jpeg'), '.jpeg': ('image', 'image/jpeg'), '.png': ('image', 'image/png'),
    '.webp': ('image', 'image/webp'), '.gif': ('image', 'image/gif'),
    '.mp4': ('video', 'video/mp4'), '.webm': ('video', 'video/webm'), '.mov': ('video', 'video/quicktime'),
}
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')


def _photo(user):
    return reverse('chats_user_photo', args=[user.pk]) if user.photo else ''


def _person(user):
    return {'id': user.pk, 'name': user.name, 'initial': (user.name[:1] or '?').upper(), 'photo': _photo(user),
            'username': user.username or ''}


# ── Calls ────────────────────────────────────────────────────────────────────

def _call_row(body, outgoing, at, chat, person):
    text = (body or '').lower()
    missed = text.startswith('missed')
    return {
        'chat': chat, 'name': person['name'], 'photo': person['photo'], 'initial': person['initial'],
        'kind': 'video' if 'video' in text else 'audio',
        'out': outgoing, 'missed': missed and not outgoing, 'unanswered': (missed and outgoing) or 'declined' in text,
        'length': (body.split('·', 1)[1].strip() if '·' in (body or '') else ''),
        'at': at.isoformat(),
    }


def call_history(me, limit=100):
    rows = []
    threads = {t.pk: t for t in DirectThread.objects.filter(Q(user_a=me) | Q(user_b=me)).select_related('user_a', 'user_b')}
    if threads:
        q = Q()
        for t in threads.values():
            q |= Q(thread_id=t.pk, pk__gt=t.cleared_upto(me))
        for m in DirectMessage.objects.filter(q, kind='call').order_by('-pk')[:limit]:
            t = threads[m.thread_id]
            rows.append(_call_row(m.body, m.sender_id == me.pk, m.created_at, str(t.pk), _person(t.other(me))))
    if staff_account(None, me):
        # the support team: calls with members, from the Support inbox
        for m in ChatMessage.objects.filter(kind=ChatMessage.KIND_CALL).exclude(user=me).select_related('user').order_by('-pk')[:limit]:
            rows.append(_call_row(m.body, m.sender == ChatMessage.SENDER_ADMIN, m.created_at, f'sx{m.user_id}',
                                  dict(_person(m.user), name=f'{m.user.name or "Guest"} · Support')))
    else:
        from .models import SupportProfile
        support = SupportProfile.load()
        person = {'name': support.display_name, 'initial': (support.display_name[:1] or 'S').upper(),
                  'photo': reverse('chats_support_photo') if support.photo else ''}
        for m in me.messages.filter(kind=ChatMessage.KIND_CALL, pk__gt=me.support_cleared_upto).order_by('-pk')[:limit]:
            rows.append(_call_row(m.body, m.sender == ChatMessage.SENDER_USER, m.created_at, 'support', person))
    rows.sort(key=lambda r: r['at'], reverse=True)
    return rows[:limit]


def api_calls(request):
    me = current_user(request)
    if not me:
        return _fail('Please log in again.', 401)
    return JsonResponse({'ok': True, 'calls': call_history(me)})


# ── Updates (stories) ────────────────────────────────────────────────────────

def contacts_of(me):
    """Everyone with a direct chat with me that neither side has blocked."""
    ids = set()
    for a, b in DirectThread.objects.filter(Q(user_a=me) | Q(user_b=me), blocked_by__isnull=True).values_list('user_a_id', 'user_b_id'):
        ids.add(b if a == me.pk else a)
    return ids


def _can_see(viewer, story):
    if not viewer or story.expires_at <= timezone.now():
        return False
    return story.user_id == viewer.pk or (story.user.is_active and story.user_id in contacts_of(viewer))


def _sweep():
    """Expired stories go, files and all (run now and then from the list)."""
    for s in Story.objects.filter(expires_at__lte=timezone.now())[:200]:
        if s.media:
            s.media.delete(save=False)
        s.delete()


def _story_json(s, me, seen_ids):
    return {
        'id': s.pk, 'kind': s.kind, 'text': s.text, 'bg': s.bg,
        'url': reverse('chats_story_media', args=[s.pk]) if s.media else '',
        'at': s.created_at.isoformat(), 'seen': s.pk in seen_ids,
    }


def api_stories(request):
    """GET → my updates and the people I chat with. POST (multipart) → share one:
    {file, text?} for a photo / video, or {text, bg} for a text card."""
    me = current_user(request)
    if not me:
        return _fail('Please log in again.', 401)
    if me.is_guest:
        if request.method == 'POST':
            return _fail('Sign up or log in to share updates.', 403)
        return JsonResponse({'ok': True, 'mine': None, 'people': []})
    if request.method == 'POST':
        return _post_story(request, me)
    if secrets.randbelow(20) == 0:
        _sweep()
    now = timezone.now()
    live = Story.objects.filter(expires_at__gt=now)
    seen = set(StoryView.objects.filter(viewer=me, story__expires_at__gt=now).values_list('story_id', flat=True))
    mine = list(live.filter(user=me))
    views = {}
    for row in StoryView.objects.filter(story__in=mine).exclude(viewer=me).values('story_id').annotate(n=Count('id')):
        views[row['story_id']] = row['n']
    people = {}
    for s in live.filter(user_id__in=contacts_of(me), user__is_active=True).select_related('user'):
        entry = people.setdefault(s.user_id, {'user': _person(s.user), 'stories': []})
        entry['stories'].append(_story_json(s, me, seen))
    out = []
    for entry in people.values():
        entry['all_seen'] = all(x['seen'] for x in entry['stories'])
        entry['latest'] = entry['stories'][-1]['at']
        out.append(entry)
    out.sort(key=lambda e: e['latest'], reverse=True)
    out.sort(key=lambda e: e['all_seen'])   # new ones first, then the ones already watched
    return JsonResponse({'ok': True, 'people': out, 'mine': {
        'user': _person(me),
        'stories': [dict(_story_json(s, me, seen), views=views.get(s.pk, 0)) for s in mine],
    }})


def _post_story(request, me):
    if Story.objects.filter(user=me, expires_at__gt=timezone.now()).count() >= STORY_LIMIT:
        return _fail(f'You can have up to {STORY_LIMIT} updates at a time. Delete one to share another.')
    text = re.sub(r'[ \t]+', ' ', request.POST.get('text', '')).strip()[:700]
    upload = request.FILES.get('file')
    story = Story(user=me, text=text, expires_at=timezone.now() + timedelta(hours=STORY_HOURS))
    if upload:
        ext = os.path.splitext(upload.name)[1].lower()
        if ext not in STORY_TYPES:
            return _fail('Share a photo (JPG, PNG, WEBP, GIF) or a video (MP4, WEBM, MOV).')
        if upload.size > STORY_MAX_MB * 1024 * 1024:
            return _fail(f'Updates can be up to {STORY_MAX_MB} MB.')
        story.kind = STORY_TYPES[ext][0]
        upload.name = secrets.token_hex(12) + ext   # never trust the uploaded name on disk
        story.media = upload
    else:
        if not text:
            return _fail('Type something or choose a photo or video.')
        bg = request.POST.get('bg', '')
        story.kind, story.bg = 'text', bg if _HEX.match(bg) else '#7c3aed'
    story.save()
    return JsonResponse({'ok': True, 'story': _story_json(story, me, set())})


def api_story(request, pk, action):
    """POST seen | delete; GET viewers (your own update)."""
    me = current_user(request)
    if not me or me.is_guest:
        return _fail('Please log in again.', 401)
    story = Story.objects.filter(pk=pk).select_related('user').first()
    if not story or not _can_see(me, story):
        return _fail('This update is no longer available.', 404)
    if action == 'seen':
        if request.method != 'POST':
            return _fail('POST only.', 405)
        if story.user_id != me.pk:
            StoryView.objects.get_or_create(story=story, viewer=me)
        return JsonResponse({'ok': True})
    if story.user_id != me.pk:
        return _fail('That is not your update.', 403)
    if action == 'delete':
        if request.method != 'POST':
            return _fail('POST only.', 405)
        if story.media:
            story.media.delete(save=False)
        story.delete()
        return JsonResponse({'ok': True})
    if action == 'viewers':
        rows = StoryView.objects.filter(story=story).exclude(viewer=me).select_related('viewer').order_by('-seen_at')
        return JsonResponse({'ok': True, 'viewers': [dict(_person(v.viewer), at=v.seen_at.isoformat()) for v in rows]})
    return _fail('Unknown action.', 400)


def story_media(request, pk):
    me = current_user(request)
    story = Story.objects.filter(pk=pk).select_related('user').first()
    if not story or not story.media or not _can_see(me, story):
        raise Http404
    ext = os.path.splitext(story.media.name)[1].lower()
    if ext not in STORY_TYPES:
        raise Http404
    try:
        handle = story.media.open('rb')
    except FileNotFoundError:
        raise Http404
    response = FileResponse(handle, content_type=STORY_TYPES[ext][1])
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=3600'
    return response
