import logging

from django.http import HttpResponsePermanentRedirect


class CanonicalHostMiddleware:
    """Consolidate the bare domain onto the canonical www hostname."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.get_host().partition(':')[0].lower() == 'edutrellis.in':
            return HttpResponsePermanentRedirect(
                f'https://www.edutrellis.in{request.get_full_path()}'
            )
        return self.get_response(request)


class HideAdminFromNonStaffMiddleware:
    """Django's built-in admin login view tells an authenticated non-staff
    user "You are authenticated as X, but are not authorized to access this
    page" — which both confirms /admin/ exists and echoes their email back
    to them. Anyone logged in but not staff/superuser (e.g. an ordinary
    store customer) should see the same 404 as any unknown URL instead,
    same as an anonymous visitor poking at random paths."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/') and request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
            from myapp.views import custom_404
            return custom_404(request)
        return self.get_response(request)


class PublicAssetCacheMiddleware:
    """Give version-stable static/media files a useful browser cache.

    This middleware sits before WhiteNoise so it also wraps files served
    directly by WhiteNoise rather than only normal Django view responses.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code == 200:
            if request.path.startswith('/static/'):
                response['Cache-Control'] = 'public, max-age=86400, stale-while-revalidate=604800'
            elif request.path.startswith((
                '/media/products/', '/media/categories/', '/media/about/', '/media/pwa/',
            )):
                response['Cache-Control'] = 'public, max-age=604800, stale-while-revalidate=2592000'
        return response


class FriendlyErrorPageMiddleware:
    """DEBUG stays on (settings.py), but only staff see Django's yellow
    debug page with the code and traceback. Everyone else gets the site's
    own pages: "Something went wrong" (500.html) when a view crashes, and
    the normal 404 page for a missing product/page — or a short JSON error
    for API calls. The crash is still logged in full for us."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        from django.core.exceptions import PermissionDenied, SuspiciousOperation, BadRequest
        from django.http import Http404, JsonResponse
        from django.shortcuts import render

        user = getattr(request, 'user', None)
        if getattr(user, 'is_staff', False):
            return None   # staff: Django's full debug page
        if isinstance(exception, (PermissionDenied, SuspiciousOperation, BadRequest)):
            return None   # Django already answers these with a plain 403/400
        wants_json = '/api/' in request.path or 'application/json' in request.headers.get('Accept', '') \
            or request.content_type == 'application/json'
        if isinstance(exception, Http404):
            if wants_json:
                return JsonResponse({'ok': False, 'status': 'error', 'error': 'Not found.', 'detail': 'Not found.'}, status=404)
            return render(request, '404.html', status=404)
        logging.getLogger('myapp').exception('Unhandled error on %s %s', request.method, request.path)
        msg = 'Something went wrong on our side. Please try again in a moment.'
        if wants_json:
            return JsonResponse({'ok': False, 'status': 'error', 'error': msg, 'detail': msg}, status=500)
        return render(request, '500.html', status=500)
