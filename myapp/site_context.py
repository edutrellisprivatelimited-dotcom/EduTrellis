from .models import FounderSection, NavAISettings, PWASettings


def context_processor(request):
    """Makes share-preview/favicon, nav AI-link and founder-section
    customization available site-wide, so every template can render them
    without its view needing to pass them in explicitly."""
    return {
        'site_customization': PWASettings.get_solo(),
        'NAV_AI': NavAISettings.get_solo(),
        'FOUNDER': FounderSection.get_solo(),
    }
