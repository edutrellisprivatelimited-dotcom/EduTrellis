"""EduChats for the site superuser.

- The superuser (e.g. rnt@gmail.com) can log in to EduChats with their
  EduTrellis admin email + password and use it like any other member; their
  EduChats account is created and linked on first use.
- One login for the superuser across the store, EduTrellis AI and EduChats:
  signed in to the store / AI → EduChats signs in as their linked account;
  signed in to EduChats with that account → the store and AI are signed in
  too; logging out of EduChats logs out of all three. Everyone else keeps
  separate store and EduChats accounts.
- Dashboard → EduChats → Conversations: a live overview of the direct chats
  members have with each other. Superuser only.
"""
import re
from datetime import timedelta
from functools import wraps

from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import ChatUser, DirectMessage, DirectThread
from .support_chat import ONLINE_SECONDS, _presence, _sign_in, _username_error, is_live

ONGOING_MINUTES = 10   # a direct chat with a message this recent counts as "ongoing"


def superuser_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_active and request.user.is_superuser):
            return redirect('dashboard_home')
        return view_func(request, *args, **kwargs)
    return wrapper


# ── superuser ↔ EduChats account ──
def superuser_from_login(request, identifier, password):
    """The active superuser these EduTrellis admin credentials belong to, or None."""
    if not identifier or not password:
        return None
    account = (User.objects.filter(email__iexact=identifier).first()
               or User.objects.filter(username__iexact=identifier).first())
    if not account or not account.is_superuser or not account.is_active:
        return None
    user = authenticate(request, username=account.username, password=password)
    return user if user and user.is_superuser else None


def fill_from_store(account, admin):
    """Mobile number, state and city the superuser gave when signing up to the
    store, copied into their EduChats account wherever it has none (or an
    invalid one) — so the profile doesn't ask for them again."""
    from .india_locations import INDIA_LOCATIONS
    from .support_chat import _PHONE_RE
    store = getattr(admin, 'store_profile', None)
    if not store:
        return account
    changed = []
    if not _PHONE_RE.match(account.phone or ''):
        phone = _PHONE_RE.match(re.sub(r'[\s-]', '', store.phone or ''))
        if phone and not ChatUser.objects.filter(phone=phone.group(1), is_guest=False).exclude(pk=account.pk).exists():
            account.phone = phone.group(1)
            changed.append('phone')
    if account.state not in INDIA_LOCATIONS or account.city not in INDIA_LOCATIONS.get(account.state, []):
        state = next((s for s in INDIA_LOCATIONS if s.lower() == (store.state or '').strip().lower()), None)
        city = state and next((c for c in INDIA_LOCATIONS[state] if c.lower() == (store.city or '').strip().lower()), None)
        if state and city:
            account.state, account.city = state, city
            changed += ['state', 'city']
    if changed:
        account.save(update_fields=changed)
    return account


def chat_account_for(admin):
    """The superuser's own EduChats account, created on first use. Never takes
    over an existing member's account, even one using the same email."""
    account = ChatUser.objects.filter(django_user=admin).first()
    if account:
        return fill_from_store(account, admin)
    email = (admin.email or admin.username or 'admin@edutrellis.in').lower()
    if '@' not in email:
        email = f'{email}@edutrellis.in'
    if ChatUser.objects.filter(email__iexact=email).exists():
        local, domain = email.split('@', 1)
        email = f'{local}+admin@{domain}'
    base = re.sub(r'[^a-z0-9._]', '', email.split('@')[0].split('+')[0])[:24].strip('._') or 'edutrellis'
    username, n = base, 1
    while _username_error(username):
        n += 1
        username = f'{base[:22]}{n}' if len(base) >= 3 else f'edutrellis_admin{n}'
        if n > 50:
            username = None
            break
    name = admin.get_full_name().strip()
    if not name or '@' in name:
        name = 'EduTrellis Admin'
    return fill_from_store(ChatUser.objects.create(
        name=name, username=username, email=email, phone='', state='', city='',
        password=make_password(None), is_verified=True, django_user=admin,
    ), admin)


def linked_superuser(chat_user):
    """The active site superuser this EduChats account belongs to, or None."""
    admin = chat_user.django_user if chat_user and chat_user.django_user_id and not chat_user.is_guest else None
    return admin if admin and admin.is_active and admin.is_superuser else None


def superuser_sso(request):
    """Superuser signed in to the store / AI with no EduChats account open here
    (or only a guest chat): open their own EduChats account. It isn't unlocked —
    with an app lock on, the lock screen still asks for the PIN."""
    from .support_chat import SESSION_KEY, current_user
    admin = request.user
    if not (admin.is_authenticated and admin.is_active and admin.is_superuser):
        return
    me = current_user(request, allow_locked=True)
    if me and not me.is_guest:
        return   # someone chose to log in to a particular account here: leave it
    account = chat_account_for(admin)
    if account.is_active:
        request.session[SESSION_KEY] = account.pk


def store_sso(request, chat_user):
    """Signed in to EduChats with the superuser's account: sign in to the store and AI too."""
    admin = linked_superuser(chat_user)
    if admin and not request.user.is_authenticated:
        auth_login(request, admin, backend='django.contrib.auth.backends.ModelBackend')


def admin_login(request):
    """Dashboard → "Open EduChats as you": signs the superuser straight in."""
    if not (request.user.is_authenticated and request.user.is_superuser):
        return redirect('chats_page')
    account = chat_account_for(request.user)
    if account.is_active:
        _sign_in(request, account)
    return redirect('chats_page')


# ── Conversations overview ──
def _thread_rows(threads, now):
    rows = []
    for t in threads:
        last = t.messages.order_by('-pk').select_related('sender').first()
        a, b = t.user_a, t.user_b
        rows.append({
            'thread': t, 'a': a, 'b': b, 'last': last, 'total': t.total, 'last_at': t.last_at,
            'ongoing': bool(t.last_at and now - t.last_at <= timedelta(minutes=ONGOING_MINUTES)),
            'a_online': _presence(a.last_seen_at)['online'], 'b_online': _presence(b.last_seen_at)['online'],
            'typing': is_live('typing', f'd{t.pk}', a.pk) or is_live('typing', f'd{t.pk}', b.pk),
            'here': is_live('here', f'd{t.pk}', a.pk) and is_live('here', f'd{t.pk}', b.pk),
        })
    return rows


@superuser_required
def dashboard_dm_conversations(request):
    now = timezone.now()
    today = timezone.localdate()
    q = request.GET.get('q', '').strip()[:60]
    tab = request.GET.get('tab', 'all')
    base = (DirectThread.objects.annotate(total=Count('messages'), last_at=Max('messages__created_at'))
            .filter(total__gt=0).select_related('user_a', 'user_b'))
    stats = {
        'threads': base.count(),
        'ongoing': base.filter(last_at__gte=now - timedelta(minutes=ONGOING_MINUTES)).count(),
        'today': base.filter(last_at__date=today).count(),
        'messages_today': DirectMessage.objects.filter(created_at__date=today).count(),
        'blocked': base.filter(blocked_by__isnull=False).count(),
        'online': ChatUser.objects.filter(
            Q(dm_threads_a__isnull=False) | Q(dm_threads_b__isnull=False),
            last_seen_at__gte=now - timedelta(seconds=ONLINE_SECONDS), is_active=True).distinct().count(),
    }
    threads = base
    if tab == 'ongoing':
        threads = threads.filter(last_at__gte=now - timedelta(minutes=ONGOING_MINUTES))
    elif tab == 'today':
        threads = threads.filter(last_at__date=today)
    elif tab == 'blocked':
        threads = threads.filter(blocked_by__isnull=False)
    else:
        tab = 'all'
    if q:
        who = q.lstrip('@')
        threads = threads.filter(
            Q(user_a__name__icontains=who) | Q(user_a__username__icontains=who) | Q(user_a__email__icontains=who)
            | Q(user_b__name__icontains=who) | Q(user_b__username__icontains=who) | Q(user_b__email__icontains=who)
            | Q(messages__body__icontains=q)).distinct()
    rows = _thread_rows(threads.order_by('-last_at')[:200], now)
    return render(request, 'dashboard/dm_conversations.html', {
        'active': 'dm_conversations', 'rows': rows, 'stats': stats, 'q': q, 'tab': tab,
        'ongoing_minutes': ONGOING_MINUTES,
    })


@superuser_required
def dashboard_dm_thread(request, pk):
    thread = get_object_or_404(DirectThread.objects.select_related('user_a', 'user_b', 'blocked_by'), pk=pk)
    messages = list(thread.messages.select_related('sender').order_by('-pk')[:1000])[::-1]
    return render(request, 'dashboard/dm_thread.html', {
        'active': 'dm_conversations', 'thread': thread, 'a': thread.user_a, 'b': thread.user_b,
        'messages': messages, 'a_presence': _presence(thread.user_a.last_seen_at),
        'b_presence': _presence(thread.user_b.last_seen_at),
    })
