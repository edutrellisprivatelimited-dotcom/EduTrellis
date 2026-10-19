"""EduChats as an installable app (PWA): manifest, service worker and icons,
all scoped to /educhats/ so it installs separately from the store and
EduTrellis AI apps. Name, description, colours and icon come from
Admin → EduChats → App Settings (EduChatsAppSettings)."""
import io
import os
import re
import secrets

from django.contrib import messages as flash
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from PIL import Image, ImageDraw, ImageOps

from .models import EduChatsAppSettings

ICON_SIZES = (180, 192, 512)
MAX_ICON_MB = 5
_icon_cache = {}
_HEX = re.compile(r'#[0-9a-fA-F]{6}\Z')

OFFLINE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EduChats — offline</title><style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1623;color:#e5e7eb;font-family:system-ui,sans-serif;text-align:center;padding:24px}
b{display:block;font-size:1.3rem;margin-bottom:.4rem;color:#fff}button{margin-top:1rem;padding:.7rem 1.4rem;border:none;border-radius:12px;background:#e8001e;color:#fff;font-weight:700;font-size:.95rem}</style></head>
<body><div><b>You're offline</b>EduChats needs an internet connection. Your chats will be right here when you're back.<br><button onclick="location.reload()">Try again</button></div></body></html>"""


def icon_url(size, maskable=False, app=None):
    app = app or EduChatsAppSettings.load()
    name = 'chats_icon_maskable' if maskable else 'chats_icon'
    return reverse(name, args=[size]) + f'?v={app.version}'


def manifest(request):
    app = EduChatsAppSettings.load()
    data = {
        'id': reverse('chats_page'),
        'name': app.app_name,
        'short_name': app.short_name or app.app_name,
        'description': app.description,
        'start_url': reverse('chats_page') + '?source=app',
        'scope': reverse('chats_page'),
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': app.background_color,
        'theme_color': app.status_bar_color,
        'categories': ['social', 'communication'],
        'prefer_related_applications': False,
        'icons': [
            {'src': icon_url(192, app=app), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': icon_url(512, app=app), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': icon_url(192, True, app), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'maskable'},
            {'src': icon_url(512, True, app), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    response = JsonResponse(data)
    response['Content-Type'] = 'application/manifest+json'
    response['Cache-Control'] = 'no-cache'   # so a new name / icon from App Settings is picked up
    return response


SW_JS = r"""
const OFFLINE = __OFFLINE__;
const APP = __APP__, ICON = __ICON__, BADGE = __BADGE__, BADGE_URL = __BADGE_URL__;
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});
// ── notifications + the app-icon badge ──
async function setBadge(n) {
  try { if (n > 0) await self.navigator.setAppBadge(n); else await self.navigator.clearAppBadge(); } catch (_) {}
}
// Android shows the app-icon badge from the notifications that are still in
// the tray, so a chat's notification has to go once that chat is read —
// here or on another device — or the icon keeps a stale badge.
async function tidyTray(unread) {
  const keep = new Set((unread || []).map(String));
  const list = await self.registration.getNotifications();
  list.forEach((n) => { const d = n.data || {}; if (!d.call && !keep.has(String(d.chat || ''))) n.close(); });
}
async function syncBadge() {
  try {
    const sub = await self.registration.pushManager.getSubscription();
    const r = await fetch(BADGE_URL + (sub ? '?ep=' + encodeURIComponent(sub.endpoint) : ''), { credentials: 'include', cache: 'no-store' });
    const d = await r.json();
    if (!d.ok) return;
    await setBadge(d.badge || 0);
    await tidyTray(d.chats);
  } catch (_) {}
}
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { body: e.data ? e.data.text() : '' }; }
  e.waitUntil((async () => {
    if (typeof d.badge === 'number') await setBadge(d.badge);
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    wins.forEach((c) => c.postMessage({ type: 'educhats-push', chat: d.chat || '' }));
    // EduChats is open and in front: the page shows the message itself (calls still ring)
    if (!d.call && wins.some((c) => c.focused && c.visibilityState === 'visible')) return;
    const opts = {
      body: d.body || 'New message', tag: d.tag || 'educhats', renotify: true, icon: ICON, badge: BADGE,
      data: { chat: d.chat || '', call: !!d.call, title: d.title || APP }, timestamp: d.ts || Date.now(),
      vibrate: d.call ? [400, 200, 400, 200, 400] : [120, 60, 120], requireInteraction: !!d.call, silent: false,
    };
    if (d.actions && d.chat) opts.actions = REPLY_ACTIONS(d.title);
    await self.registration.showNotification(d.title || APP, opts);
    if (Array.isArray(d.unread)) await tidyTray(d.unread.concat(d.chat ? [d.chat] : []));
  })());
});
// ── Reply / Mark as read, straight from the notification ──
// Where the browser can type into the notification (type: 'text') the reply is
// sent from here without opening EduChats; elsewhere "Reply" opens the chat
// with the keyboard up.
const REPLY_ACTIONS = (title) => [
  { action: 'reply', type: 'text', title: 'Reply', placeholder: 'Reply to ' + String(title || '').slice(0, 40) + '…' },
  { action: 'read', title: 'Mark as read' },
];
function sendPath(chat) {
  if (chat === 'support') return 'api/messages/';
  if (/^\d+$/.test(chat)) return 'api/dm/' + chat + '/';
  if (/^g\d+$/.test(chat)) return 'api/groups/' + chat.slice(1) + '/';
  if (/^sx\d+$/.test(chat)) return 'api/inbox/' + chat.slice(2) + '/';
  return '';
}
async function api(path, body) {
  const t = await (await fetch(self.registration.scope + 'api/csrf/', { credentials: 'include', cache: 'no-store' })).json();
  const r = await fetch(self.registration.scope + path, {
    method: 'POST', credentials: 'include', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': t.csrf || '' }, body: JSON.stringify(body),
  });
  let d = {};
  try { d = await r.json(); } catch (_) {}
  if (!r.ok || d.ok === false) { const err = new Error(d.error || 'HTTP ' + r.status); err.status = r.status; throw err; }
  return d;
}
async function quickReply(chat, text, title) {
  const path = sendPath(chat);
  const cid = 'nr' + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);   // a retry can't post it twice
  let error = null;
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      if (!path) throw new Error('chat');
      await api(path, { body: text, cid });
      error = null;
      break;
    } catch (err) {
      error = err;
      if (err.status && err.status < 500 && err.status !== 429) break;   // won't get better by retrying
      await new Promise((ok) => setTimeout(ok, 1200 * (attempt + 1)));
    }
  }
  if (error) {
    await self.registration.showNotification('Reply not sent', {
      body: (error.status === 401 ? 'Open EduChats to send: ' : 'Tap to try again: ') + text.slice(0, 120),
      tag: 'chat-' + chat, icon: ICON, badge: BADGE, data: { chat, draft: text, title },
    });
    return;
  }
  try { await api('api/read/', { chat }); } catch (_) {}   // answering a chat means you've read it
  await syncBadge();
}
async function openChat(chat, reply, draft) {
  const q = (chat ? '?chat=' + encodeURIComponent(chat) : '') + (chat && reply ? '&reply=1' : '');
  const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  for (const c of wins) {
    if (c.url.startsWith(self.registration.scope)) {
      try { await c.focus(); } catch (_) {}
      c.postMessage({ type: 'educhats-open', chat, reply: !!reply, draft: draft || '' });
      return;
    }
  }
  const w = await self.clients.openWindow(self.registration.scope + q);
  if (w && draft) setTimeout(() => w.postMessage({ type: 'educhats-open', chat, reply: true, draft }), 2500);
}
self.addEventListener('notificationclick', (e) => {
  const n = e.notification, data = n.data || {}, chat = data.chat || '';
  n.close();
  if (e.action === 'read') {
    e.waitUntil(api('api/read/', { chat }).catch(() => {}).then(syncBadge));
    return;
  }
  const text = typeof e.reply === 'string' ? e.reply.trim() : '';
  if (e.action === 'reply' && text) {
    e.waitUntil(quickReply(chat, text, data.title));
    return;
  }
  e.waitUntil(openChat(chat, e.action === 'reply' || !!data.draft, data.draft));
});
// the page tells the worker the badge number; on a fresh start it asks the server
self.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'educhats-badge') e.waitUntil(setBadge(+e.data.n || 0));
  else if (e.data && e.data.type === 'educhats-sync') e.waitUntil(syncBadge());
});
self.addEventListener('pushsubscriptionchange', (e) => {
  e.waitUntil(self.clients.matchAll({ type: 'window' }).then((wins) => wins.forEach((c) => c.postMessage({ type: 'educhats-resubscribe' }))));
});
"""


def service_worker(request):
    # Network first; when offline, page loads get a small "you're offline" screen.
    # Chats are personal, so nothing else is cached. It also shows notifications
    # (Web Push from educhats_push.py) and keeps the app-icon badge up to date.
    import json
    app = EduChatsAppSettings.load()
    js = (SW_JS.replace('__OFFLINE__', json.dumps(OFFLINE_HTML)).replace('__APP__', json.dumps(app.app_name))
          .replace('__ICON__', json.dumps(icon_url(192, app=app))).replace('__BADGE__', json.dumps(reverse('chats_badge_icon')))
          .replace('__BADGE_URL__', json.dumps(reverse('chats_badge'))))
    response = HttpResponse(js, content_type='application/javascript')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Service-Worker-Allowed'] = reverse('chats_page')
    return response


def badge_icon(request):
    """Android's small status-bar icon: a white chat bubble on transparent (the system tints it)."""
    if 'badge' not in _icon_cache:
        big = 96 * 4
        img = Image.new('RGBA', (big, big), (0, 0, 0, 0))
        draw, u = ImageDraw.Draw(img), big / 100
        draw.rounded_rectangle([12 * u, 16 * u, 88 * u, 70 * u], radius=18 * u, fill='white')
        draw.polygon([(24 * u, 64 * u), (20 * u, 88 * u), (44 * u, 68 * u)], fill='white')
        for cx in (32, 50, 68):
            draw.ellipse([(cx - 6) * u, (43 - 6) * u, (cx + 6) * u, (43 + 6) * u], fill=(0, 0, 0, 0))
        out = io.BytesIO()
        img.resize((96, 96), Image.Resampling.LANCZOS).save(out, 'PNG')
        _icon_cache['badge'] = out.getvalue()
    response = HttpResponse(_icon_cache['badge'], content_type='image/png')
    response['Cache-Control'] = 'public, max-age=86400'
    return response


def _hex_rgb(value, fallback=(15, 22, 35)):
    if not value or not _HEX.match(value):
        return fallback
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _draw_default(size):
    """Red gradient square with a white chat bubble and three dots, drawn at
    4x and scaled down for smooth edges. The bubble sits inside the maskable
    safe zone, so it survives Android's round/squircle crop."""
    big = size * 4
    img = Image.new('RGB', (big, big))
    top, bottom = (232, 0, 30), (110, 0, 16)
    draw = ImageDraw.Draw(img)
    for y in range(big):
        t = y / (big - 1)
        draw.line([(0, y), (big, y)], fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    u = big / 100
    draw.rounded_rectangle([24 * u, 27 * u, 76 * u, 66 * u], radius=13 * u, fill='white')
    draw.polygon([(32 * u, 62 * u), (30 * u, 76 * u), (45 * u, 64 * u)], fill='white')
    for cx in (37, 50, 63):
        draw.ellipse([(cx - 4.6) * u, (46.5 - 4.6) * u, (cx + 4.6) * u, (46.5 + 4.6) * u], fill=(232, 0, 30))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def _draw_custom(app, size, maskable):
    """The uploaded picture, cut to a square. Maskable icons get it at 80% on the
    splash colour, so Android's circle / squircle crop never clips the logo."""
    with app.icon.open('rb') as fh:
        src = Image.open(fh)
        src = ImageOps.exif_transpose(src).convert('RGBA')
    square = ImageOps.fit(src, (size, size), Image.Resampling.LANCZOS)
    background = _hex_rgb(app.background_color)
    canvas = Image.new('RGBA', (size, size), background + (255,))
    if maskable:
        inner = int(size * 0.8)
        logo = ImageOps.fit(src, (inner, inner), Image.Resampling.LANCZOS)
        canvas.alpha_composite(logo, ((size - inner) // 2, (size - inner) // 2))
    else:
        canvas.alpha_composite(square)
    return canvas.convert('RGB')


def _icon_png(size, maskable):
    app = EduChatsAppSettings.load()
    key = (size, maskable, app.version, app.icon.name if app.icon else '')
    if key not in _icon_cache:
        img = None
        if app.icon:
            try:
                img = _draw_custom(app, size, maskable)
            except (OSError, ValueError):
                img = None   # file missing / unreadable — fall back to the built-in icon
        img = img or _draw_default(size)
        out = io.BytesIO()
        img.save(out, format='PNG', optimize=True)
        if len(_icon_cache) > 40:
            _icon_cache.clear()
        _icon_cache[key] = out.getvalue()
    return _icon_cache[key]


def _icon_response(size, maskable):
    if size not in ICON_SIZES:
        raise Http404
    response = HttpResponse(_icon_png(size, maskable), content_type='image/png')
    response['Cache-Control'] = 'public, max-age=86400'
    return response


def icon(request, size):
    return _icon_response(size, False)


def icon_maskable(request, size):
    return _icon_response(size, True)


# ── Admin → EduChats → App Settings ──────────────────────────────────────────

def dashboard_app_settings(request):
    app = EduChatsAppSettings.load()
    if request.method == 'POST':
        data = request.POST
        name = re.sub(r'\s+', ' ', data.get('app_name', '')).strip()[:45]
        short = re.sub(r'\s+', ' ', data.get('short_name', '')).strip()[:24]
        if len(name) < 2:
            flash.error(request, 'Please enter an app name of at least 2 letters.')
            return redirect('dashboard_educhats_app')
        theme, background = data.get('theme_color', '').strip(), data.get('background_color', '').strip()
        if not _HEX.match(theme) or not _HEX.match(background):
            flash.error(request, 'Please pick the colours with the colour boxes.')
            return redirect('dashboard_educhats_app')
        upload = request.FILES.get('icon')
        if upload:
            ext = os.path.splitext(upload.name)[1].lower()
            if ext not in ('.png', '.jpg', '.jpeg', '.webp'):
                flash.error(request, 'Please upload the icon as a PNG, JPG or WEBP picture.')
                return redirect('dashboard_educhats_app')
            if upload.size > MAX_ICON_MB * 1024 * 1024:
                flash.error(request, f'The icon must be smaller than {MAX_ICON_MB} MB.')
                return redirect('dashboard_educhats_app')
            try:
                with Image.open(upload) as probe:
                    probe.verify()
                upload.seek(0)
                with Image.open(upload) as probe:
                    width, height = probe.size
                upload.seek(0)
            except Exception:
                flash.error(request, 'That file does not look like a picture. Please try another one.')
                return redirect('dashboard_educhats_app')
            if min(width, height) < 192:
                flash.error(request, f'The icon is too small ({width}×{height}). Please use a square picture of at least 512×512.')
                return redirect('dashboard_educhats_app')
        if (upload or data.get('remove_icon')) and app.icon:
            try:
                app.icon.delete(save=False)
            except OSError:
                app.icon = None
        if upload:
            app.icon.save(secrets.token_hex(8) + os.path.splitext(upload.name)[1].lower(), upload, save=False)
        app.app_name, app.short_name = name, short or name
        app.description = data.get('description', '').strip()[:200]
        app.theme_color, app.background_color = theme.lower(), background.lower()
        if data.get('bars_mode') in dict(EduChatsAppSettings.BARS_MODES):
            app.bars_mode = data['bars_mode']
        nav = data.get('nav_color', '').strip()
        if _HEX.match(nav):
            app.nav_color = nav.lower()
        turn = ' '.join(u for u in re.split(r'[\s,]+', data.get('turn_url', '')) if re.match(r'^turns?:[\w.\-\[\]:]+(\?transport=(udp|tcp))?$', u))
        if data.get('turn_url', '').strip() and not turn:
            flash.error(request, 'The TURN address should look like turn:relay.example.com:3478 (several can be separated by spaces).')
            return redirect('dashboard_educhats_app')
        app.turn_url = turn[:300]
        app.turn_username = data.get('turn_username', '').strip()[:120]
        if data.get('turn_credential', '').strip():   # empty = keep the saved password
            app.turn_credential = data['turn_credential'].strip()[:200]
        if not turn:
            app.turn_username = app.turn_credential = ''
        if data.get('gif_provider') in dict(EduChatsAppSettings.GIF_PROVIDERS):
            app.gif_provider = data['gif_provider']
        if data.get('remove_gif_key'):
            app.gif_api_key = ''
        elif data.get('gif_api_key', '').strip():   # empty = keep the saved key
            app.gif_api_key = re.sub(r'[^A-Za-z0-9_\-]', '', data['gif_api_key'])[:120]
        app.save()
        _icon_cache.clear()
        flash.success(request, 'App settings saved. New installs use them right away; installed apps update within a day or so.')
        return redirect('dashboard_educhats_app')
    return render(request, 'dashboard/educhats_app.html', {
        'active': 'educhats_app', 'app': app,
        'icon_192': icon_url(192, app=app), 'icon_maskable': icon_url(512, True, app),
        'chats_url': request.build_absolute_uri(reverse('chats_page')),
    })
