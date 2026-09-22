import json

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import TestCase

from .middleware import CanonicalHostMiddleware, PublicAssetCacheMiddleware
from .models import Cart, Category, Product, PWASettings


class PublicPagePerformanceAndSEOTests(TestCase):
    def test_customize_settings_drive_share_metadata_and_favicon(self):
        customization = PWASettings.get_solo()
        customization.share_title = 'Custom sharing heading'
        customization.share_description = 'Custom sharing description.'
        customization.share_image.name = 'customize/share-card.png'
        customization.favicon.name = 'customize/favicon.ico'
        customization.save()

        response = self.client.get('/store/')

        self.assertContains(response, '<meta property="og:title" content="Custom sharing heading">', html=True)
        self.assertContains(response, '<meta property="og:description" content="Custom sharing description.">', html=True)
        self.assertContains(response, 'https://www.edutrellis.in/media/customize/share-card.png')
        self.assertContains(response, '<link rel="icon" href="/media/customize/favicon.ico">', html=True)

    def test_product_share_metadata_takes_priority_over_store_defaults(self):
        customization = PWASettings.get_solo()
        customization.share_title = 'Store sharing heading'
        customization.share_description = 'Store sharing description.'
        customization.save()
        category = Category.objects.create(name='Share Test', slug='share-test')
        product = Product.objects.create(
            category=category, slug='share-test-product', brand='EduTrellis',
            name='Dynamic Product', short_description='Dynamic product description.',
            price='99.00', mrp='99.00', is_active=True,
        )

        response = self.client.get(f'/store/product/{product.slug}/')

        self.assertContains(response, '<meta property="og:title" content="Dynamic Product — EduTrellis Store">', html=True)
        self.assertContains(response, '<meta property="og:description" content="Dynamic product description.">', html=True)

    def test_customize_dashboard_exposes_share_and_favicon_fields(self):
        admin = User.objects.create_user(
            username='customize-admin@example.com', password='test-password-123', is_staff=True,
        )
        self.client.force_login(admin)

        response = self.client.get('/store/dashboard/customize/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="share_title"')
        self.assertContains(response, 'name="share_description"')
        self.assertContains(response, 'name="share_image"')
        self.assertContains(response, 'name="favicon"')

    def test_apex_domain_redirects_permanently_to_canonical_www_host(self):
        middleware = CanonicalHostMiddleware(lambda request: HttpResponse('page'))

        response = middleware(RequestFactory().get(
            '/store/?category=audio', HTTP_HOST='edutrellis.in', secure=True,
        ))

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response['Location'],
            'https://www.edutrellis.in/store/?category=audio',
        )

    def test_estore_alias_and_missing_slash_use_permanent_redirects(self):
        alias = self.client.get('/estore')
        missing_slash = self.client.get('/store')

        self.assertRedirects(alias, '/store/', status_code=301, fetch_redirect_response=False)
        self.assertRedirects(missing_slash, '/store/', status_code=301, fetch_redirect_response=False)

    def test_anonymous_store_view_does_not_create_an_empty_cart(self):
        response = self.client.get('/store/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Cart.objects.count(), 0)

    def test_public_assets_receive_browser_cache_headers(self):
        middleware = PublicAssetCacheMiddleware(lambda request: HttpResponse('asset'))

        static_response = middleware(RequestFactory().get('/static/style.css'))
        media_response = middleware(RequestFactory().get('/media/products/example.webp'))

        self.assertIn('max-age=86400', static_response['Cache-Control'])
        self.assertIn('max-age=604800', media_response['Cache-Control'])

    def test_product_page_has_canonical_product_structured_data(self):
        category = Category.objects.create(name='SEO Test Audio', slug='seo-test-audio')
        product = Product.objects.create(
            category=category, slug='test-speaker', brand='EduTrellis',
            name='Test Speaker', short_description='A test product.',
            price='999.00', mrp='1299.00', is_active=True,
        )

        response = self.client.get(f'/store/product/{product.slug}/')
        schema = json.loads(response.context['product_schema_json'])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(schema['@type'], 'Product')
        self.assertEqual(schema['offers']['priceCurrency'], 'INR')
        self.assertContains(
            response,
            f'<link rel="canonical" href="https://www.edutrellis.in/store/product/{product.slug}/">',
            html=True,
        )
