"""Verified AI company facts supplied to chat models. Brand name comes from
AISiteSettings.ai_brand_name (dashboard EduTrellis AI > AI Settings page) — see _brand_name
below — not hardcoded, so a rename applies here immediately too."""

import re

from myapp import business_info

_DEFAULT_BRAND_NAME = 'EduTrellis'

_CONTACT_KEYWORD_RE = re.compile(
    r"\b(phone|telephone|mobile|whatsapp|what.?s ?app|call(?:ing)?|e-?mail|"
    r"contact|address|location|office|sales|support|helpline|instagram|"
    r"facebook|linkedin|social(?:\s*media|\s*handles?)?|hours|timings?)\b",
    re.IGNORECASE,
)


def _brand_name():
    from .models import AISiteSettings
    try:
        return (AISiteSettings.get_solo().ai_brand_name or '').strip() or _DEFAULT_BRAND_NAME
    except Exception:
        return _DEFAULT_BRAND_NAME


def is_company_query(text):
    text = text or ''
    brand_re = re.compile(
        rf"\b({re.escape(_brand_name())}|edutrellis|edutrellis\.in)\b", re.IGNORECASE,
    )
    return bool(brand_re.search(text) or _CONTACT_KEYWORD_RE.search(text))


def public_site_context():
    brand = _brand_name()
    return f"""VERIFIED {brand.upper()} AI DATA (authoritative):
Use only these details for company answers. Never invent a phone number,
email, address, person, statistic, social handle, product, price, or URL.
If a requested detail is absent, say so and point to edutrellis.in or
{business_info.EMAIL_SUPPORT}.

{brand} AI is an AI assistant offering chat, reasoning, coding, document
help, image understanding, image generation/editing, notes, web-assisted
answers, audio transcription, YouTube downloads, and optional GitHub
repository workflows.

Official AI pages: {business_info.WEBSITE} and {business_info.WEBSITE}ai/
Support: {business_info.EMAIL_SUPPORT}
Call/WhatsApp: {business_info.PHONE_DISPLAY}
Hours: {business_info.HOURS}
Instagram: {business_info.INSTAGRAM_URL}
LinkedIn: {business_info.LINKEDIN_COMPANY_URL}
Facebook: {business_info.FACEBOOK_URL}

There is one general support email and one phone/WhatsApp number. Never
invent a separate sales line, toll-free number, international number, or
second support address. Do not provide a physical office address.
{_founder_line()}"""


def _founder_line():
    """The founder/CEO exactly as the dashboard's Customize > Founder page has
    them (myapp.seo.founder); with no name set there, no person is named."""
    from myapp.seo import founder
    try:
        f = founder()
    except Exception:
        f = None
    if not f:
        return 'Do not name an individual as founder, owner, CEO, or creator.'
    title = f.title or 'Founder & CEO'
    return (f'{title} of EduTrellis: {f.name.strip()} (email {f.email or business_info.EMAIL_CEO}, '
            f'phone/WhatsApp {business_info.PHONE_DISPLAY}). Name no other person as founder, owner, CEO, or creator.')
