from django import template
from django.templatetags.static import static
from django.utils.safestring import mark_safe

from myapp import seo

register = template.Library()


@register.simple_tag(takes_context=True)
def site_schema(context):
    """The site-wide schema.org graph (company, founder/CEO, website, main
    sections) as a ready <script type="application/ld+json"> block."""
    custom = context.get('site_customization')
    icon = getattr(custom, 'favicon', None) if custom else None
    logo = seo.SITE + (icon.url if icon else static('img/og-cover.jpg'))
    return mark_safe('<script type="application/ld+json">' + seo.to_script_json(seo.graph(logo)) + '</script>')
