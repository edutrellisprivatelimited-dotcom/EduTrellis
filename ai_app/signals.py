from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db.models import F
from django.dispatch import receiver

from myapp.models import StoreProfile
from .single_device import clear_active_session, register_active_session


@receiver(user_logged_in)
def claim_ai_single_device_login(sender, request, user, **kwargs):
    """Runs on every login site-wide (cheap bookkeeping — claiming the slot
    has no visible effect by itself). Only AISingleDeviceSessionMiddleware,
    scoped to /ai/ requests, ever acts on the claim by logging a stale
    session out."""
    if request is None:
        return
    if not request.session.session_key:
        request.session.save()
    register_active_session(user, request.session.session_key)
    profile, _ = StoreProfile.objects.get_or_create(user=user)
    StoreProfile.objects.filter(pk=profile.pk).update(login_count=F('login_count') + 1)


@receiver(user_logged_out)
def release_ai_single_device_login(sender, request, user, **kwargs):
    if request is None or user is None:
        return
    clear_active_session(user, request.session.session_key)
