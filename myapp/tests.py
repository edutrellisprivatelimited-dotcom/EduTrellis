import json

from django.contrib.auth.models import User
from django.http import HttpResponse
from django.test import RequestFactory
from django.test import TestCase, override_settings

from .middleware import CanonicalHostMiddleware, PublicAssetCacheMiddleware, SiteSwitchMiddleware
from .models import Cart, Category, Product, PWASettings, SiteStatus, StoredFile


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
        self.assertContains(response, '<meta property="og:description" content="Dynamic product description. Buy at ₹99 on the official EduTrellis Store.">', html=True)

    def test_store_and_product_search_titles_never_reuse_homepage_share_text(self):
        # The dashboard's share text is for WhatsApp/Facebook previews; when the
        # store's <title> reused it, Google listed /store/ as "Your Digital
        # Growth Partner" under the homepage.
        customization = PWASettings.get_solo()
        customization.share_title = 'Homepage sharing heading'
        customization.share_description = 'Homepage sharing description.'
        customization.save()
        category = Category.objects.create(name='Seo Test', slug='seo-test')
        product = Product.objects.create(
            category=category, slug='seo-test-product', brand='EduTrellis', name='Seo Product',
            short_description='', description='<p>A long full description of this speaker.</p>',
            price='299.00', mrp='299.00', is_active=True,
        )

        store = self.client.get('/store/').content.decode()
        page = self.client.get(f'/store/product/{product.slug}/').content.decode()

        self.assertIn('<title>EduTrellis Store', store)
        self.assertNotIn('Homepage sharing', store.split('<meta property="og:')[0])
        self.assertIn('<meta name="description" content="A long full description of this speaker. Buy at ₹299 on the official EduTrellis Store.">', page)

    def test_company_schema_and_llms_txt_name_the_dashboard_founder(self):
        from .models import FounderSection
        founder = FounderSection.get_solo()
        founder.name, founder.email = 'Test Founder', 'ceo@edutrellis.in'
        founder.save()

        home = self.client.get('/').content.decode()
        llms = self.client.get('/llms.txt')

        self.assertIn('"@type": "Person", "@id": "https://www.edutrellis.in/#founder", "name": "Test Founder"', home)
        self.assertEqual(llms['Content-Type'], 'text/plain; charset=utf-8')
        self.assertContains(llms, 'Founder & CEO: Test Founder')
        self.assertContains(llms, '[EduTrellis Store](https://www.edutrellis.in/store/)')

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

        self.assertIn('max-age=86400', static_response['Cache-Control'])

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


class FriendlyErrorPageTests(TestCase):
    """DEBUG is on, yet visitors never see Django's debug page."""

    def _crash(self, path='/store/'):
        from unittest import mock
        return mock.patch('myapp.views._estore_context', side_effect=RuntimeError('boom'))

    def test_visitor_gets_something_went_wrong_page(self):
        with self._crash():
            response = self.client.get('/store/')
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, 'Something went wrong', status_code=500)
        self.assertNotContains(response, 'Traceback', status_code=500)
        self.assertNotContains(response, 'boom', status_code=500)

    def test_api_call_gets_short_json_error(self):
        from unittest import mock
        with mock.patch('myapp.views._get_or_create_cart', side_effect=RuntimeError('boom')):
            response = self.client.get('/store/api/cart/')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['status'], 'error')
        self.assertNotIn('boom', response.content.decode())

    def test_missing_product_shows_site_404_not_debug_page(self):
        response = self.client.get('/store/product/no-such-product/')
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, 'Page Not Found', status_code=404)
        self.assertNotContains(response, 'URLconf', status_code=404)

    @override_settings(DEBUG=True)
    def test_staff_get_the_debug_page_on_a_debug_server(self):
        staff = User.objects.create_user(username='dev@example.com', password='pw-123456789', is_staff=True)
        self.client.force_login(staff)
        self.client.raise_request_exception = True
        with self._crash(), self.assertRaises(RuntimeError):
            self.client.get('/store/')

    def test_staff_get_the_friendly_page_in_production(self):
        staff = User.objects.create_user(username='dev@example.com', password='pw-123456789', is_staff=True)
        self.client.force_login(staff)
        with self._crash():
            response = self.client.get('/store/')
        self.assertContains(response, 'Something went wrong', status_code=500)
        self.assertNotContains(response, 'boom', status_code=500)


class SiteSwitchTests(TestCase):
    def setUp(self):
        SiteSwitchMiddleware.refresh()

    def tearDown(self):
        SiteSwitchMiddleware.refresh()

    def _switch(self, **flags):
        SiteStatus.objects.update_or_create(pk=1, defaults=flags)
        SiteSwitchMiddleware.refresh()

    def test_disabled_ai_shows_coming_soon_at_its_own_address(self):
        self._switch(ai_disabled=True, educhats_disabled=False)
        response = self.client.get('/ai/')
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, 'Coming soon', status_code=503)
        self.assertContains(response, 'EduTrellis AI', status_code=503)
        self.assertEqual(response['Retry-After'], '3600')
        self.assertEqual(response.request['PATH_INFO'], '/ai/')

    def test_disabled_ai_api_gets_json(self):
        self._switch(ai_disabled=True, educhats_disabled=False)
        response = self.client.post('/ai/api/chat/', data='{}', content_type='application/json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['status'], 'error')

    def test_disabled_educhats_covers_every_educhats_address(self):
        self._switch(ai_disabled=False, educhats_disabled=True)
        for path in ('/educhats/', '/educhats/api/me/', '/chats/', '/chat', '/ai/chats/'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 503, path)

    def test_rest_of_site_stays_up(self):
        self._switch(ai_disabled=True, educhats_disabled=True)
        self.assertEqual(self.client.get('/store/').status_code, 200)
        self.assertNotEqual(self.client.get('/aiml-course/').status_code, 503)

    def test_dashboard_page_switches_products(self):
        staff = User.objects.create_user(username='admin@example.com', password='pw-123456789', is_staff=True)
        self.client.force_login(staff)
        self._switch(ai_disabled=False, educhats_disabled=False)
        response = self.client.post('/store/dashboard/site-status/', {'product': 'educhats', 'action': 'disable'})
        self.assertContains(response, 'EduChats is now disabled.')
        self.assertContains(response, 'Enable EduChats')
        self.assertContains(response, 'Disable EduTrellis AI')
        self.assertTrue(SiteStatus.get_solo().educhats_disabled)
        self.assertFalse(SiteStatus.get_solo().ai_disabled)
        self.assertEqual(self.client.get('/educhats/').status_code, 503)

        self.client.post('/store/dashboard/site-status/', {'product': 'educhats', 'action': 'enable'})
        self.assertFalse(SiteStatus.get_solo().educhats_disabled)
        self.assertNotEqual(self.client.get('/educhats/').status_code, 503)

    def test_dashboard_page_is_staff_only(self):
        response = self.client.post('/store/dashboard/site-status/', {'product': 'ai', 'action': 'disable'})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SiteStatus.objects.filter(ai_disabled=True).exists())


class RailwayHealthcheckTests(TestCase):
    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_health_check_gets_200_over_plain_http(self):
        for path in ('/', '/store/', '/health'):
            response = self.client.get(path, HTTP_HOST='healthcheck.railway.app')
            self.assertEqual(response.status_code, 200, path)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_other_plain_http_still_redirects(self):
        self.assertEqual(self.client.get('/store/', HTTP_HOST='www.edutrellis.in').status_code, 301)


class MediaRedirectTests(TestCase):
    def test_redirects_to_dropbox(self):
        from unittest import mock
        with mock.patch('myapp.dropbox_storage.temporary_link', return_value='https://dl.dropboxusercontent.com/x.jpg'):
            response = self.client.get('/media/products/x.jpg')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], 'https://dl.dropboxusercontent.com/x.jpg')
        self.assertIn('max-age=3600', response['Cache-Control'])

    def test_permanent_link_is_used_when_stored(self):
        StoredFile.objects.create(name='hero/a.jpg', url='https://www.dropbox.com/scl/fi/a/a.jpg?rlkey=k&raw=1')
        from myapp import dropbox_storage
        dropbox_storage._urls.pop('hero/a.jpg', None)
        response = self.client.get('/media/hero/a.jpg')
        self.assertEqual(response['Location'], 'https://www.dropbox.com/scl/fi/a/a.jpg?rlkey=k&raw=1')

    def test_private_chat_files_are_never_handed_out(self):
        from unittest import mock
        with mock.patch('myapp.dropbox_storage.temporary_link') as link:
            for path in ('/media/educhats/dm/2026/10/a.jpg', '/media/support_chat/users/a.jpg', '/media/ai_calls/1/2.webm',
                         '/media/ai/calls/1/2.webm', '/media/ai/archive/a@b.com/x.png', '/media/educhats/users/photos/a.jpg'):
                self.assertEqual(self.client.get(path).status_code, 404, path)
        link.assert_not_called()

    def test_path_tricks_are_refused(self):
        self.assertEqual(self.client.get('/media/../db.sqlite3').status_code, 404)
        self.assertEqual(self.client.get('/media/products/%2e%2e/%2e%2e/db.sqlite3').status_code, 404)

    def test_missing_file_is_404(self):
        from unittest import mock
        with mock.patch('myapp.dropbox_storage.temporary_link', side_effect=FileNotFoundError):
            self.assertEqual(self.client.get('/media/products/none.jpg').status_code, 404)


class BackupTests(TestCase):
    """Dashboard → Backup & Restore. Dropbox itself is never called here."""

    def setUp(self):
        self.staff = User.objects.create_user(username='backup-admin@example.com', password='pw-123456789', is_staff=True)
        self.client.force_login(self.staff)

    def test_backup_names_carry_the_brand_date_and_kind(self):
        from datetime import datetime, timezone as tz
        from myapp import dropbox_backup as b
        when = datetime(2026, 11, 14, 4, 30, 15, tzinfo=tz.utc)   # 10:00:15 IST
        self.assertEqual(b.backup_filename(b.KIND_MANUAL, when), 'EduTrellis_Backup_2026-11-14_10-00-15.sqlite3')
        self.assertEqual(b.backup_filename(b.KIND_AUTO, when), 'EduTrellis_AutoBackup_2026-11-14_10-00-15.sqlite3')
        for name, kind in [('EduTrellis_BeforeRestore_2026-11-14_10-00-15.sqlite3', b.KIND_SAFETY),
                           ('EduTrellis_Uploaded_2026-11-14_10-00-15_1.sqlite3', b.KIND_UPLOAD),
                           ('db_20261113_020345_before_restore.sqlite3', b.KIND_SAFETY),
                           ('db_20261102_233956.sqlite3', b.KIND_MANUAL)]:
            self.assertTrue(b.is_backup_name(name), name)
            self.assertEqual(b.kind_of(name), kind, name)
        for name in ('EduTrellis_Latest.sqlite3', 'db_latest.sqlite3', '../db.sqlite3', 'x/db_1.sqlite3', 'notes.txt'):
            self.assertFalse(b.is_backup_name(name), name)

    def test_backup_folder_is_checked(self):
        from myapp import dropbox_backup as b
        self.assertEqual(b.clean_folder('EduTrellis Store//backups/'), '/EduTrellis Store/backups')
        for bad in ('/', '/a/../b', '/EduTrellis Site/backups', '/a/b?', ''):
            with self.assertRaises(b.BackupError, msg=bad):
                b.clean_folder(bad)

    def test_page_shows_connection_backups_and_files(self):
        from unittest import mock
        from myapp import dropbox_backup as b
        meta = mock.Mock(size=2048, client_modified=None)
        meta.name = 'EduTrellis_AutoBackup_2026-11-14_10-00-15.sqlite3'
        StoredFile.objects.create(name='website/home/hero/a.webp', size=10)
        StoredFile.objects.create(name='educhats/dm/2026/11/b.jpg', size=20)
        with override_settings(DROPBOX_REFRESH_TOKEN='t', DROPBOX_APP_KEY='k', DROPBOX_APP_SECRET='s'), \
                mock.patch.object(b, 'connection_info', return_value={'ok': True, 'name': 'Owner', 'email': 'o@x.in',
                                                                     'used': 10, 'allocated': 100, 'error': ''}), \
                mock.patch.object(b, 'list_backups', return_value=[b.BackupFile(meta)]):
            html = self.client.get('/store/dashboard/backup/').content.decode()
        self.assertIn('Connected', html)
        self.assertIn('Owner', html)
        self.assertIn('/EduTrellis Store/backups', html)
        self.assertIn('EduTrellis_AutoBackup_2026-11-14_10-00-15.sqlite3', html)
        self.assertIn('Automatic', html)
        self.assertIn('website/home/hero/a.webp', html)
        self.assertIn('fa-lock', html)   # the EduChats file is private

    def test_delete_one_and_download_go_through_dropbox_backup(self):
        from unittest import mock
        from myapp import dropbox_backup as b
        name = 'EduTrellis_Backup_2026-11-14_10-00-15.sqlite3'
        with mock.patch.object(b, 'delete_backup') as delete:
            self.client.post('/store/dashboard/backup/delete/', {'filename': name})
        self.assertEqual(delete.call_args[0][1], name)
        with mock.patch.object(b, 'download_backup', return_value=(iter([b'SQLite']), 6)):
            response = self.client.get('/store/dashboard/backup/download/', {'name': name})
        self.assertEqual(b''.join(response.streaming_content), b'SQLite')
        self.assertIn(name, response['Content-Disposition'])

    def test_uploaded_file_must_be_an_edutrellis_database(self):
        from unittest import mock
        from django.core.files.uploadedfile import SimpleUploadedFile
        from myapp import dropbox_backup as b
        with mock.patch.object(b, '_client') as client, mock.patch.object(b, 'connection_info', return_value={'ok': False, 'error': 'offline'}):
            with self.assertRaisesMessage(b.BackupError, 'not an SQLite database'):
                b.upload_database(None, SimpleUploadedFile('x.sqlite3', b'not a database'), restore=True)
            response = self.client.post('/store/dashboard/backup/upload/',
                                        {'database': SimpleUploadedFile('x.sqlite3', b'not a database'), 'then': 'restore'},
                                        follow=True)
        client.assert_not_called()   # rejected before anything reaches Dropbox
        self.assertContains(response, 'not an SQLite database')

    def test_backup_pages_are_staff_only(self):
        self.client.logout()
        for url in ('/store/dashboard/backup/', '/store/dashboard/backup/download/?live=1'):
            self.assertNotEqual(self.client.get(url).status_code, 200, url)

    def test_automatic_backup_runs_once_when_due_and_prunes(self):
        from unittest import mock
        from django.utils import timezone
        from myapp import auto_backup, dropbox_backup as b
        from myapp.models import DropboxSettings
        DropboxSettings.objects.update_or_create(pk=1, defaults={'app_key': 'k', 'app_secret': 's', 'refresh_token': 't',
                                                                 'auto_backup_enabled': True, 'auto_backup_keep': 3})
        with mock.patch.object(b, 'create_backup', return_value='EduTrellis_AutoBackup_x.sqlite3') as create, \
                mock.patch.object(b, 'prune_auto_backups') as prune:
            self.assertEqual(auto_backup.run_if_due(), 'EduTrellis_AutoBackup_x.sqlite3')
            self.assertIsNone(auto_backup.run_if_due())   # not due again for a day
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs['kind'], b.KIND_AUTO)
        self.assertEqual(prune.call_args[0][1], 3)
        self.assertLess(timezone.now() - DropboxSettings.get_solo().last_auto_backup_at, timezone.timedelta(minutes=1))

    def test_restore_keeps_the_current_dropbox_settings(self):
        from myapp import dropbox_backup as b
        from myapp.models import DropboxSettings
        DropboxSettings.objects.update_or_create(pk=1, defaults={'refresh_token': 'old', 'backup_folder': '/Old'})
        b._keep_dropbox_settings({'refresh_token': 'current', 'backup_folder': '/Current/backups'})
        row = DropboxSettings.get_solo()
        self.assertEqual((row.refresh_token, row.backup_folder), ('current', '/Current/backups'))
