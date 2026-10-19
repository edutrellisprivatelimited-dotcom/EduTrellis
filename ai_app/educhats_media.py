"""Stickers and GIFs in EduChats messages.

Stickers are Google's animated Noto emoji (fonts.gstatic.com, CC BY 4.0);
a sticker message stores only its code ("1f602"), so it can't point anywhere
else. GIFs come from GIPHY or Tenor through api_gifs, using the key set in
Admin → EduChats → App Settings; a GIF message stores the GIF's URL, which
must be on that service's own media server.
"""
import json
import re
import urllib.parse
import urllib.request
from urllib.parse import urlsplit

from django.core.cache import cache
from django.http import JsonResponse

from .support_chat import _fail, current_user

STICKER_RE = re.compile(r'[0-9a-f]{4,5}(?:_[0-9a-f]{4,5}){0,4}\Z')
GIF_SEARCHES_PER_MINUTE = 40


def sticker_url(code):
    return f'https://fonts.gstatic.com/s/e/notoemoji/latest/{code}/512.webp'


def gif_ok(url):
    if not isinstance(url, str) or len(url) > 500:
        return False
    parts = urlsplit(url)
    host = parts.hostname or ''
    return parts.scheme == 'https' and (host == 'media.tenor.com' or host == 'i.giphy.com' or re.fullmatch(r'media\d?\.giphy\.com', host) is not None)


def media_from(data):
    """('sticker', code) / ('gif', url) from a send request, ('', '') for a plain text message, or (None, error)."""
    kind = data.get('kind')
    if kind == 'sticker':
        code = str(data.get('code', '')).lower()
        return ('sticker', code) if STICKER_RE.match(code) else (None, 'That sticker is not available.')
    if kind == 'gif':
        url = str(data.get('url', ''))
        return ('gif', url) if gif_ok(url) else (None, 'That GIF is not available.')
    return '', ''


def summary(kind, body):
    """Line used in exports and the admin view."""
    if kind == 'sticker':
        return '[Sticker]'
    if kind == 'gif':
        return f'[GIF] {body}'
    return None


# ── GIF search (GIPHY or Tenor) ──────────────────────────────────────────────

def _giphy(key, q):
    base = 'https://api.giphy.com/v1/gifs/' + ('search' if q else 'trending')
    params = {'api_key': key, 'limit': 24, 'rating': 'pg-13', 'bundle': 'messaging_non_clips'}
    if q:
        params['q'] = q
    with urllib.request.urlopen(base + '?' + urllib.parse.urlencode(params), timeout=8) as r:
        data = json.load(r)
    out = []
    for g in data.get('data', []):
        imgs = g.get('images', {})
        full, small = imgs.get('fixed_width') or {}, imgs.get('fixed_width_small') or imgs.get('preview_gif') or {}
        url = full.get('webp') or full.get('url')
        if url and gif_ok(url.split('?')[0]):
            out.append({'url': url.split('?')[0], 'preview': (small.get('webp') or small.get('url') or url).split('?')[0],
                        'w': int(full.get('width') or 200), 'h': int(full.get('height') or 200), 'title': g.get('title', '')[:80]})
    return out


def _tenor(key, q):
    base = 'https://tenor.googleapis.com/v2/' + ('search' if q else 'featured')
    params = {'key': key, 'client_key': 'educhats', 'limit': 24, 'media_filter': 'gif,tinygif', 'contentfilter': 'medium'}
    if q:
        params['q'] = q
    with urllib.request.urlopen(base + '?' + urllib.parse.urlencode(params), timeout=8) as r:
        data = json.load(r)
    out = []
    for g in data.get('results', []):
        fmt = g.get('media_formats', {})
        full, small = fmt.get('gif') or {}, fmt.get('tinygif') or {}
        url = full.get('url')
        if url and gif_ok(url):
            dims = full.get('dims') or [200, 200]
            out.append({'url': url, 'preview': small.get('url') or url, 'w': dims[0], 'h': dims[1],
                        'title': (g.get('content_description') or '')[:80]})
    return out


def api_gifs(request):
    user = current_user(request)
    if not user:
        return _fail('Please log in again.', 401)
    from .models import EduChatsAppSettings
    app = EduChatsAppSettings.load()
    provider, key = app.gif_provider, (app.gif_api_key or '').strip()
    if not key:
        return JsonResponse({'ok': False, 'setup': True,
                             'error': "GIFs aren't switched on yet — the admin can add a GIPHY or Tenor key in App Settings."})
    throttle = f'educhats-gifq-{user.pk}'
    if cache.get(throttle, 0) >= GIF_SEARCHES_PER_MINUTE:
        return _fail('Searching a lot — please wait a few seconds.', 429)
    cache.set(throttle, cache.get(throttle, 0) + 1, 60)
    q = re.sub(r'\s+', ' ', request.GET.get('q', '')).strip()[:60]
    cache_key = f'educhats-gifs-{provider}-{q.lower()}'
    gifs = cache.get(cache_key)
    if gifs is None:
        try:
            gifs = (_tenor if provider == 'tenor' else _giphy)(key, q)
        except Exception:
            return _fail('GIFs could not be loaded right now. Please try again.', 502)
        cache.set(cache_key, gifs, 600)
    return JsonResponse({'ok': True, 'gifs': gifs, 'provider': 'Tenor' if provider == 'tenor' else 'GIPHY'})
