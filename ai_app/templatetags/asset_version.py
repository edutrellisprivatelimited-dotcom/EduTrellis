"""{% versioned_static 'chat/support_chat.js' %} → /static/chat/support_chat.js?v=<file time>

Static files are served under the same name with a long browser cache, so a
phone could keep running last week's script against today's page. The ?v=
changes whenever the file does, so browsers fetch the new copy straight away.
"""
import os

from django import template
from django.conf import settings
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()
_versions = {}


def _version(path):
    if settings.DEBUG or path not in _versions:   # a deploy restarts the server, so caching is safe there
        found = finders.find(path) or os.path.join(settings.STATIC_ROOT, path)
        try:
            _versions[path] = str(int(os.path.getmtime(found)))
        except (OSError, TypeError):
            _versions[path] = ''
    return _versions[path]


@register.simple_tag
def versioned_static(path):
    url, v = static(path), _version(path)
    return f'{url}?v={v}' if v else url
