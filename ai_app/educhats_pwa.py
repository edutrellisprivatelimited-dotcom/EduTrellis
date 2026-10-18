"""EduChats as an installable app (PWA): manifest, service worker and a
generated icon, all scoped to /educhats/ so it installs separately from the
store and EduTrellis AI apps."""
import io

from django.http import Http404, HttpResponse, JsonResponse
from django.urls import reverse
from PIL import Image, ImageDraw

ICON_SIZES = (180, 192, 512)
_icon_cache = {}

OFFLINE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EduChats — offline</title><style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0f1623;color:#e5e7eb;font-family:system-ui,sans-serif;text-align:center;padding:24px}
b{display:block;font-size:1.3rem;margin-bottom:.4rem;color:#fff}button{margin-top:1rem;padding:.7rem 1.4rem;border:none;border-radius:12px;background:#e8001e;color:#fff;font-weight:700;font-size:.95rem}</style></head>
<body><div><b>You're offline</b>EduChats needs an internet connection. Your chats will be right here when you're back.<br><button onclick="location.reload()">Try again</button></div></body></html>"""


def manifest(request):
    data = {
        'id': reverse('chats_page'),
        'name': 'EduChats',
        'short_name': 'EduChats',
        'description': 'Chat with the EduTrellis support team and people you know.',
        'start_url': reverse('chats_page') + '?source=app',
        'scope': reverse('chats_page'),
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#0f1623',
        'theme_color': '#0f1623',
        'icons': [
            {'src': reverse('chats_icon', args=[192]), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': reverse('chats_icon', args=[512]), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': reverse('chats_icon', args=[512]), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    response = JsonResponse(data)
    response['Content-Type'] = 'application/manifest+json'
    response['Cache-Control'] = 'public, max-age=3600'
    return response


def service_worker(request):
    # Network first; when offline, page loads get a small "you're offline" screen.
    # Chats are personal, so nothing else is cached.
    js = (
        "const OFFLINE = " + repr(OFFLINE_HTML).replace('\n', '\n') + ";\n"
        "self.addEventListener('install', () => self.skipWaiting());\n"
        "self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));\n"
        "self.addEventListener('fetch', (e) => {\n"
        "  if (e.request.mode !== 'navigate') return;\n"
        "  e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));\n"
        "});\n"
    )
    response = HttpResponse(js, content_type='application/javascript')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Service-Worker-Allowed'] = reverse('chats_page')
    return response


def _draw_icon(size):
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
    draw = ImageDraw.Draw(img)
    u = big / 100
    draw.rounded_rectangle([24 * u, 27 * u, 76 * u, 66 * u], radius=13 * u, fill='white')
    draw.polygon([(32 * u, 62 * u), (30 * u, 76 * u), (45 * u, 64 * u)], fill='white')
    for cx in (37, 50, 63):
        draw.ellipse([(cx - 4.6) * u, (46.5 - 4.6) * u, (cx + 4.6) * u, (46.5 + 4.6) * u], fill=(232, 0, 30))
    out = io.BytesIO()
    img.resize((size, size), Image.Resampling.LANCZOS).save(out, format='PNG', optimize=True)
    return out.getvalue()


def icon(request, size):
    if size not in ICON_SIZES:
        raise Http404
    if size not in _icon_cache:
        _icon_cache[size] = _draw_icon(size)
    response = HttpResponse(_icon_cache[size], content_type='image/png')
    response['Cache-Control'] = 'public, max-age=86400'
    return response
