from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, re_path, include
from django.contrib.sitemaps.views import sitemap
from django.views.generic import TemplateView

from myapp.sitemaps import StaticViewSitemap, ProductSitemap
from myapp.views import custom_404

sitemaps = {
    'static': StaticViewSitemap,
    'products': ProductSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),

    # Main App
    path('', include('myapp.urls')),

    # Sitemap
    path(
        'sitemap.xml',
        sitemap,
        {'sitemaps': sitemaps},
        name='django.contrib.sitemaps.views.sitemap'
    ),

    # Robots
    path(
        'robots.txt',
        TemplateView.as_view(
            template_name='robots.txt',
            content_type='text/plain'
        ),
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Catch-all: renders the custom 404 template for any unmatched URL. Django only
# consults handler404 when DEBUG=False, so with DEBUG=True it would otherwise
# show the technical debug page instead — this pattern bypasses that by
# matching (and rendering the 404 template) directly instead of raising.
urlpatterns += [re_path(r'^.*$', custom_404)]

handler404 = 'myapp.views.custom_404'
