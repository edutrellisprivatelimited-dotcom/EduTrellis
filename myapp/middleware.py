class HideAdminFromNonStaffMiddleware:
    """Django's built-in admin login view tells an authenticated non-staff
    user "You are authenticated as X, but are not authorized to access this
    page" — which both confirms /admin/ exists and echoes their email back
    to them. Anyone logged in but not staff/superuser (e.g. an
    AI-premium-only account) should see the same 404 as any unknown URL
    instead, same as an anonymous visitor poking at random paths."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/') and request.user.is_authenticated and not (request.user.is_staff or request.user.is_superuser):
            from myapp.views import custom_404
            return custom_404(request)
        return self.get_response(request)
