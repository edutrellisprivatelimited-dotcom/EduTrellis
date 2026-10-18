"""Social links on EduChats profiles (Snapchat, Instagram, Facebook, LinkedIn).

People type either a username or a profile link; it's stored as a clean
https URL on that site's own domain, so a link on someone's ID card can only
ever point to the real Snapchat / Instagram / Facebook / LinkedIn.
"""
import re
from urllib.parse import parse_qs, urlsplit

SOCIALS = {
    'snapchat': {'label': 'Snapchat', 'icon': 'fa-snapchat', 'hosts': ('snapchat.com',),
                 'handle': r'[A-Za-z][A-Za-z0-9._-]{2,14}', 'url': 'https://www.snapchat.com/add/{}'},
    'instagram': {'label': 'Instagram', 'icon': 'fa-instagram', 'hosts': ('instagram.com', 'instagr.am'),
                  'handle': r'[A-Za-z0-9._]{1,30}', 'url': 'https://www.instagram.com/{}'},
    'facebook': {'label': 'Facebook', 'icon': 'fa-facebook', 'hosts': ('facebook.com', 'fb.com'),
                 'handle': r'[A-Za-z0-9.]{3,50}', 'url': 'https://www.facebook.com/{}'},
    'linkedin': {'label': 'LinkedIn', 'icon': 'fa-linkedin', 'hosts': ('linkedin.com',),
                 'handle': r'[A-Za-z0-9_%-]{3,100}', 'url': 'https://www.linkedin.com/in/{}'},
}
SOCIAL_KEYS = tuple(SOCIALS)
SHOW_FIELDS = tuple(f'show_{key}' for key in SOCIAL_KEYS)
MAX_URL = 200

_NOT_PROFILE = {'p', 'reel', 'reels', 'stories', 'explore', 'share', 'sharer', 'login', 'groups',
                'events', 'watch', 'pages', 'feed', 'jobs', 'posts', 'pulse', 'tv', 'accounts'}


def _host_ok(host, hosts):
    host = host.lower().split(':')[0]
    return any(host == h or host.endswith('.' + h) for h in hosts)


def clean_social(key, value):
    """Returns (url, error). An empty value clears the link."""
    spec = SOCIALS[key]
    value = (value or '').strip()
    if not value:
        return '', ''
    bad = f"That doesn't look like a {spec['label']} username or profile link."
    handle_re = re.compile(spec['handle'] + r'\Z')
    if key == 'linkedin' and re.match(r'(in|company|school)/', value):
        value = 'linkedin.com/' + value
    if '/' not in value and '.com' not in value.lower():
        handle = value.lstrip('@')
        if not handle_re.match(handle):
            return '', bad
        return spec['url'].format(handle), ''

    parts = urlsplit(value if '://' in value else 'https://' + value)
    if parts.scheme not in ('http', 'https') or not _host_ok(parts.netloc, spec['hosts']):
        return '', f"Please paste a link from {spec['label']} (or just your username)."
    path = [p for p in parts.path.split('/') if p]
    if key == 'facebook' and path[:1] == ['profile.php']:
        profile_id = (parse_qs(parts.query).get('id') or [''])[0]
        if not profile_id.isdigit():
            return '', bad
        return f'https://www.facebook.com/profile.php?id={profile_id}', ''
    if key == 'snapchat' and path[:1] in (['add'], ['u']):
        path = path[1:]
    if key == 'linkedin':
        if len(path) < 2 or path[0] not in ('in', 'company', 'school'):
            return '', 'Please paste your LinkedIn profile link (linkedin.com/in/…).'
        if not handle_re.match(path[1]):
            return '', bad
        return f'https://www.linkedin.com/{path[0]}/{path[1]}', ''
    if not path or path[0].lower() in _NOT_PROFILE or not handle_re.match(path[0].lstrip('@')):
        return '', bad
    url = spec['url'].format(path[0].lstrip('@'))
    return (url, '') if len(url) <= MAX_URL else ('', bad)


def social_handle(key, url):
    """What the ID card shows for a link: @username, in/slug, …"""
    parts = urlsplit(url)
    path = [p for p in parts.path.split('/') if p]
    if key == 'facebook' and path[:1] == ['profile.php']:
        return 'Facebook profile'
    if key == 'linkedin' and len(path) >= 2:
        return f'{path[0]}/{path[1]}'
    if key == 'snapchat' and path[:1] == ['add']:
        path = path[1:]
    return '@' + path[0] if path else url


def socials_json(obj, only_shown=True):
    """[{key, label, icon, url, handle, shown}] for the links obj (ChatUser or SupportProfile) has."""
    out = []
    for key in SOCIAL_KEYS:
        url = getattr(obj, key, '') or ''
        shown = getattr(obj, f'show_{key}', True)
        if not url or (only_shown and not shown):
            continue
        spec = SOCIALS[key]
        out.append({'key': key, 'label': spec['label'], 'icon': spec['icon'], 'url': url,
                    'handle': social_handle(key, url), 'shown': bool(shown)})
    return out


def save_socials(obj, data):
    """Validates and sets every social field from a form; returns (field, error) for the first bad one."""
    cleaned = {}
    for key in SOCIAL_KEYS:
        url, error = clean_social(key, data.get(key, ''))
        if error:
            return key, error
        cleaned[key] = url
    for key, url in cleaned.items():
        setattr(obj, key, url)
    return '', ''
