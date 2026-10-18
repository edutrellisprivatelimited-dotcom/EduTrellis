import re

from django.db import OperationalError, ProgrammingError
from django.templatetags.static import static as static_url

# Only the EduTrellis AI pages (and the staff dashboard that manages them)
# get the AI's branding/support variables; storefront pages never see them.
AI_PATH_PREFIXES = ('/ai/', '/store/dashboard/')


def ai_site_context(request):
    """Exposes AI Settings (dashboard EduTrellis AI > AI Settings) to the AI
    templates as SITE_FAVICON_URL, SITE_AI_BRAND_NAME etc. — the same names
    Vidhyora's site-wide context processor used, scoped to /ai/ here."""
    if not request.path.startswith(AI_PATH_PREFIXES):
        return {}
    from .models import AISiteSettings
    try:
        obj = AISiteSettings.get_solo()
        whatsapp_number = obj.support_whatsapp_number or '9695953183'
        whatsapp_digits = re.sub(r'\D', '', whatsapp_number)
        if len(whatsapp_digits) == 10:
            whatsapp_digits = '91' + whatsapp_digits
        return {
            'SITE_FAVICON_URL': obj.favicon.url if obj.favicon else None,
            'SITE_AI_BRAND_NAME': obj.ai_brand_name or 'EduTrellis',
            'SITE_SOCIAL_PREVIEW_TITLE': obj.social_preview_title,
            'SITE_SOCIAL_PREVIEW_DESCRIPTION': obj.social_preview_description,
            'SITE_SOCIAL_PREVIEW_IMAGE_URL': request.build_absolute_uri(
                obj.social_preview_image.url if obj.social_preview_image else static_url('img/og-cover.jpg')
            ),
            'SITE_SUPPORT_WHATSAPP_DISPLAY': whatsapp_number,
            'SITE_SUPPORT_WHATSAPP_LINK': f'https://wa.me/{whatsapp_digits}',
            'SITE_SUPPORT_EMAIL': obj.support_email or 'support@edutrellis.in',
        }
    except (OperationalError, ProgrammingError):
        # A restored backup can predate the AISiteSettings table.
        return {
            'SITE_FAVICON_URL': None,
            'SITE_AI_BRAND_NAME': 'EduTrellis',
            'SITE_SOCIAL_PREVIEW_TITLE': 'EduTrellis AI — Free AI Chat Assistant',
            'SITE_SOCIAL_PREVIEW_DESCRIPTION': 'Chat with EduTrellis AI for quick answers, writing, images and learning support — free, right from your browser.',
            'SITE_SOCIAL_PREVIEW_IMAGE_URL': request.build_absolute_uri(static_url('img/og-cover.jpg')),
            'SITE_SUPPORT_WHATSAPP_DISPLAY': '9695953183',
            'SITE_SUPPORT_WHATSAPP_LINK': 'https://wa.me/919695953183',
            'SITE_SUPPORT_EMAIL': 'support@edutrellis.in',
        }
