from .models import NavAISettings, PWASettings


def context_processor(request):
    """Makes share-preview/favicon and nav AI-link customization available
    site-wide, so every template can render them without its view needing
    to pass them in explicitly."""
    return {
        'site_customization': PWASettings.get_solo(),
        'NAV_AI': NavAISettings.get_solo(),
    }
