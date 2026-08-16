import json
import logging
import os
import secrets
import threading
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urlencode

import requests

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.db.models import Q, F
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import resolve, Resolver404
from django.templatetags.static import static as static_url
from django.http import JsonResponse, StreamingHttpResponse
from django.core.mail import send_mail, BadHeaderError
from django.core.cache import cache
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from myapp.forms import (
    ContactLeadForm, StoreSignupForm, PhoneVerifyForm, StoreLoginForm, StoreContactForm, SignupEditForm,
    StoreProfileEditForm, StorePasswordChangeForm, CheckoutAddressForm, ReviewForm, CategoryForm, OrderStatusForm,
    ProductForm, ProductImageFormSet, ProductColorFormSet,
    AboutUsContentForm, PolicyPageForm, PaymentSettingsForm, DropboxSettingsForm, PWASettingsForm,
    FeeSettingsForm,
)
from myapp.models import (
    ContactLead, StoreProfile, Cart, CartItem, Category, Order, OrderItem,
    Product, ProductImage, ProductColor, AboutUsContent, PolicyPage, PaymentSettings, Payment,
    DropboxSettings, Review, PhoneVerification, PWASettings, FeeSettings,
    AIConversation, AIMessage, GitHubConnection,
)
from myapp import dropbox_backup
from myapp import ai_chat
from myapp import github_ops
from myapp import doc_extract
from myapp import light_mode
from myapp.emailing import send_store_email, get_notify_email
from myapp.sms import send_phone_otp, verify_phone_otp
from myapp.seed_data import seed_demo_reviews

logger = logging.getLogger(__name__)

try:
    import razorpay
except ImportError:  # pragma: no cover - optional dependency until configured
    razorpay = None


def home(request):
    trending_products = Product.objects.filter(is_active=True).select_related('category')[:8]
    return render(request, "home.html", {
        "contact_form": ContactLeadForm(),
        "trending_products": trending_products,
    })


def home2(request):
    return render(request, "home2.html", {})


def estore(request):
    return render(request, "estore.html", _estore_context(request))


def product_detail(request, slug):
    """Renders the same storefront template as estore(), pre-loaded to open
    the product detail view for `slug` on load. This gives every product a
    real, shareable, bookmarkable URL without duplicating the header, cart
    drawer, auth modals and footer into a second template."""
    product = get_object_or_404(Product, slug=slug, is_active=True)
    context = _estore_context(request)
    context['initial_product_slug'] = product.slug
    context['meta_title'] = f"{product.name} — EduTrellis Store"
    context['meta_description'] = product.short_description
    context['meta_image'] = product.image.url if product.image else ''
    return render(request, "estore.html", context)


def product_reviews(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    reviews = product.reviews.select_related('user').all()
    return JsonResponse({
        'status': 'ok',
        'can_review': _user_can_review(request.user, product),
        'reviews': [_review_payload(r, request.user) for r in reviews],
    })


def product_review_submit(request, slug):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in to review a product.'}, status=401)

    product = get_object_or_404(Product, slug=slug, is_active=True)
    if not _user_can_review(request.user, product):
        return JsonResponse(
            {'status': 'error', 'detail': "You can review this product once your delivered order for it arrives."},
            status=403,
        )

    form = ReviewForm(_parse_json_body(request))
    if not form.is_valid():
        return JsonResponse(
            {'status': 'validation_error', 'errors': {k: v[0] for k, v in form.errors.items()}},
            status=400,
        )

    review, _created = Review.objects.update_or_create(
        product=product, user=request.user,
        defaults={'rating': form.cleaned_data['rating'], 'comment': form.cleaned_data['comment']},
    )
    rating, count = product.review_stats
    return JsonResponse({
        'status': 'ok',
        'review': _review_payload(review, request.user),
        'review_stats': {'rating': rating, 'count': count},
    })


_ICON_MIME_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml'}


def pwa_manifest(request):
    settings_obj = PWASettings.get_solo()
    icon_url = request.build_absolute_uri(settings_obj.icon.url) if settings_obj.icon else None
    icon_type = 'image/png'
    if settings_obj.icon:
        ext = os.path.splitext(settings_obj.icon.name)[1].lower()
        icon_type = _ICON_MIME_TYPES.get(ext, 'image/png')

    manifest = {
        'name': settings_obj.app_name,
        'short_name': settings_obj.short_name,
        'description': settings_obj.description,
        'start_url': '/store/',
        'scope': '/store/',
        'display': 'standalone',
        'background_color': settings_obj.background_color,
        'theme_color': settings_obj.theme_color,
        'icons': [
            {'src': icon_url, 'sizes': '192x192', 'type': icon_type, 'purpose': 'any maskable'},
            {'src': icon_url, 'sizes': '512x512', 'type': icon_type, 'purpose': 'any maskable'},
        ] if icon_url else [],
    }
    return JsonResponse(manifest, content_type='application/manifest+json')


def pwa_service_worker(request):
    return render(request, 'sw.js', content_type='application/javascript')


def _estore_context(request):
    cart = _get_or_create_cart(request)
    payment_settings = PaymentSettings.get_solo()
    pwa_settings = PWASettings.get_solo()
    fee_settings = FeeSettings.get_solo()
    if fee_settings.delivery_fee <= 0:
        delivery_copy = 'Free delivery on all orders'
    elif fee_settings.free_delivery_over > 0:
        delivery_copy = f'Free delivery over ₹{fee_settings.free_delivery_over:.0f}'
    else:
        delivery_copy = f'Delivery ₹{fee_settings.delivery_fee:.0f} per order'
    boot = {
        'user': None,
        'cart': _cart_payload(cart),
        'shipping': {
            'free_over': float(fee_settings.free_delivery_over),
            'fee': float(fee_settings.delivery_fee),
            'handling_fee': float(fee_settings.handling_fee),
            'copy': delivery_copy,
        },
        'payments': {
            'cod_enabled': payment_settings.cod_enabled,
            'razorpay_enabled': payment_settings.razorpay_ready,
            'razorpay_key_id': payment_settings.razorpay_key_id if payment_settings.razorpay_ready else '',
        },
        'pwa': {'enabled': pwa_settings.ready},
    }
    if request.user.is_authenticated:
        boot['user'] = _user_payload(request.user)
    categories = Category.objects.filter(is_active=True)
    products = Product.objects.filter(is_active=True).select_related('category').prefetch_related('images', 'colors', 'reviews')
    return {
        "store_boot_json": json.dumps(boot),
        "products_json": json.dumps([_product_payload(p) for p in products]),
        "categories": categories,
        "about": AboutUsContent.get_solo(),
        "pwa": pwa_settings,
        "delivery_copy": delivery_copy,
        "initial_product_slug": None,
        "meta_title": None,
        "meta_description": None,
        "meta_image": None,
    }


def _user_can_review(user, product):
    """A shopper may review a product once they have a Delivered order
    containing it — this is the sole gate, checked fresh on every request
    rather than cached on the Review row."""
    if not user.is_authenticated:
        return False
    return OrderItem.objects.filter(
        order__user=user, order__status=Order.STATUS_DELIVERED, product_id=product.slug,
    ).exists()


def _review_payload(r, viewer=None):
    return {
        'id': r.pk,
        'name': r.user.first_name or 'Verified Buyer',
        'rating': r.rating,
        'comment': r.comment,
        'created_at': timezone.localtime(r.created_at).strftime('%d %b %Y'),
        'mine': bool(viewer and viewer.is_authenticated and r.user_id == viewer.pk),
    }


def _product_payload(p):
    gallery = []
    if p.video:
        gallery.append({'type': 'video', 'url': p.video.url})
    if p.image:
        gallery.append({'type': 'image', 'url': p.image.url})
    for img in p.images.all():
        gallery.append({'type': 'image', 'url': img.image.url})

    return {
        'id': p.slug,
        'cat': p.category.slug,
        'brand': p.brand,
        'name': p.name,
        'desc': p.short_description,
        'description': p.description or p.short_description,
        'specs': p.spec_list,
        'price': float(p.price),
        'mrp': float(p.mrp),
        'icon': p.icon,
        'grad': p.gradient,
        'image': p.image.url if p.image else None,
        'gallery': gallery,
        'colors': [
            {'name': c.name, 'hex': c.hex_code, 'image': c.image.url if c.image else None}
            for c in p.colors.all()
        ],
        'flag': p.flag,
        'stock': p.stock_status,
        'tags': p.tag_list,
        'rating': p.review_stats[0],
        'reviews': p.review_stats[1],
    }


def _user_payload(user):
    profile = getattr(user, 'store_profile', None)
    return {
        'name': user.first_name or user.username,
        'email': user.email,
        'phone': profile.phone if profile else '',
        'is_staff': user.is_staff,
        'avatar_url': profile.avatar.url if (profile and profile.avatar) else None,
        'wallet_balance': float(profile.wallet_balance) if profile else 0.0,
        'phone_verified': bool(profile and profile.phone_verified),
    }


# ── E-Store: cart helpers ────────────────────────────────────────────────

def _get_or_create_cart(request):
    if not request.session.session_key:
        request.session.create()
    session_key = request.session.session_key

    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        if not cart:
            cart = Cart.objects.create(user=request.user, session_key=session_key)

        # Merge in any cart built while the visitor was still anonymous
        anon_cart = Cart.objects.filter(session_key=session_key, user__isnull=True).first()
        if anon_cart and anon_cart.pk != cart.pk:
            for item in anon_cart.items.all():
                existing = cart.items.filter(product_id=item.product_id).first()
                if existing:
                    existing.quantity += item.quantity
                    existing.save(update_fields=['quantity'])
                else:
                    item.pk = None
                    item.cart = cart
                    item.save()
            anon_cart.delete()
        return cart

    cart = Cart.objects.filter(session_key=session_key, user__isnull=True).first()
    if not cart:
        cart = Cart.objects.create(session_key=session_key)
    return cart


def _merge_session_cart_into_user(user, session_key):
    """Folds an anonymous cart into the user's cart using the session key
    captured *before* login() — login() rotates the session key, so looking
    it up afterwards via request.session would miss the pre-login cart."""
    if not session_key:
        return
    anon_cart = Cart.objects.filter(session_key=session_key, user__isnull=True).first()
    if not anon_cart:
        return
    cart, _ = Cart.objects.get_or_create(user=user, defaults={'session_key': session_key})
    for item in anon_cart.items.all():
        existing = cart.items.filter(product_id=item.product_id).first()
        if existing:
            existing.quantity += item.quantity
            existing.save(update_fields=['quantity'])
        else:
            item.pk = None
            item.cart = cart
            item.save()
    anon_cart.delete()


def _merge_session_ai_chats_into_user(user, session_key):
    """Same idea as _merge_session_cart_into_user: any /AI/ conversations a
    guest started before logging in are tied to their pre-login session_key,
    not to a User row yet. Hand them over on login/signup instead of
    stranding them as an orphaned anonymous chat."""
    if not session_key:
        return
    AIConversation.objects.filter(session_key=session_key, user__isnull=True).update(user=user, session_key='')


def _cart_payload(cart):
    items = list(cart.items.all())
    subtotal = sum((i.subtotal for i in items), Decimal('0'))
    return {
        'items': [
            {
                'product_id': i.product_id,
                'name': i.product_name,
                'price': float(i.price),
                'quantity': i.quantity,
                'subtotal': float(i.subtotal),
            }
            for i in items
        ],
        'count': sum(i.quantity for i in items),
        'subtotal': float(subtotal),
    }


def _parse_json_body(request):
    try:
        return json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return {}


def _order_payload(order):
    # payments is prefetched/ordered newest-first (Payment.Meta.ordering) —
    # the latest attempt is what decides whether a "Pay now" retry applies.
    payments = list(order.payments.all())
    latest_payment = payments[0] if payments else None
    can_retry_payment = bool(
        latest_payment and latest_payment.method == Payment.METHOD_RAZORPAY
        and latest_payment.status in (Payment.STATUS_FAILED, Payment.STATUS_PENDING)
        and order.status not in (Order.STATUS_CANCELLED, Order.STATUS_DELIVERED)
    )
    return {
        'id': order.pk,
        'status': order.status,
        'status_display': order.get_status_display(),
        'subtotal': float(order.subtotal),
        'wallet_discount': float(order.wallet_discount),
        'shipping_fee': float(order.shipping_fee),
        'handling_fee': float(order.handling_fee),
        'total': float(order.total),
        'created_at': timezone.localtime(order.created_at).strftime('%d %b %Y, %I:%M %p'),
        'payment_status': latest_payment.status if latest_payment else None,
        'payment_status_display': latest_payment.get_status_display() if latest_payment else None,
        'can_retry_payment': can_retry_payment,
        'address': {
            'recipient_name': order.recipient_name,
            'recipient_phone': order.recipient_phone,
            'full_address': order.full_address,
        },
        'items': [
            {
                'product_id': i.product_id,
                'name': i.product_name,
                'price': float(i.price),
                'quantity': i.quantity,
                'subtotal': float(i.subtotal),
            }
            for i in order.items.all()
        ],
    }


def _send_order_confirmation_email(order, payment_method, paid):
    """Emails the customer their order confirmation and notifies the store
    of a new order. Best-effort — failures are logged, never raised, so a
    flaky SMTP connection can't fail an already-placed/paid order."""
    items_lines = "\n".join(
        f"  {i.product_name} x{i.quantity} — Rs.{i.subtotal}"
        for i in order.items.all()
    )
    payment_line = "Paid online via Razorpay" if paid else "Cash on Delivery — pay when your order arrives"

    customer_body = (
        f"Hi {order.recipient_name or order.user.get_full_name() or order.user.username},\n\n"
        f"Thanks for your order — here's your confirmation.\n\n"
        f"Order #{order.pk}\n"
        "==========================================\n"
        f"{items_lines}\n"
        "------------------------------------------\n"
        f"Subtotal      : Rs.{order.subtotal}\n"
        f"Shipping      : Rs.{order.shipping_fee}\n"
        f"Handling fee  : Rs.{order.handling_fee}\n"
        + (f"Wallet credit : -Rs.{order.wallet_discount}\n" if order.wallet_discount else "")
        + f"Total         : Rs.{order.total}\n"
        "==========================================\n\n"
        f"Payment: {payment_line}\n\n"
        f"Delivering to:\n{order.recipient_name}, {order.recipient_phone}\n{order.full_address}\n\n"
        "We'll notify you as your order ships. Track it anytime from My Orders on the store.\n\n"
        "— Team EduTrellis"
    )

    try:
        send_store_email(
            f"Order #{order.pk} confirmed — EduTrellis Store",
            customer_body,
            [order.user.email],
        )
    except Exception as e:
        logger.exception("Order confirmation email failed for Order #%s: %s", order.pk, e)

    admin_body = (
        f"New order placed on the store.\n\n"
        f"Order #{order.pk}\n"
        f"Customer : {order.user.get_full_name() or order.user.username} ({order.user.email})\n"
        f"{items_lines}\n"
        f"Total    : Rs.{order.total}\n"
        f"Payment  : {payment_line}\n"
        f"Deliver to: {order.recipient_name}, {order.recipient_phone}\n{order.full_address}"
    )
    try:
        send_store_email(
            f"New Order #{order.pk} — Rs.{order.total}",
            admin_body,
            [get_notify_email()],
        )
    except Exception as e:
        logger.exception("Order admin-notification email failed for Order #%s: %s", order.pk, e)


def _send_order_confirmation_email_async(order, payment_method, paid):
    """Fires the confirmation + admin-notification emails on a background
    thread instead of blocking the request. Each send_store_email() call is
    a real SMTP round trip (up to EMAIL_TIMEOUT=10s, twice) — doing that
    inline was what made the Thank You page appear "very late" after
    checkout, since the frontend only shows it once this response lands."""
    threading.Thread(
        target=_send_order_confirmation_email, args=(order, payment_method, paid), daemon=True,
    ).start()


# ── E-Store: auth ────────────────────────────────────────────────────────

PHONE_VERIFY_OTP_TTL_MINUTES = 10
PHONE_VERIFY_RESEND_COOLDOWN_SECONDS = 45
PHONE_VERIFY_MAX_ATTEMPTS = 5


def _new_phone_verification(user, phone, now):
    """Sends a fresh OTP via 2Factor and records the resulting session so
    a later confirm can check the code against it. The OTP digits
    themselves live at 2Factor, not here."""
    session_id = send_phone_otp(phone)
    pending, _created = PhoneVerification.objects.update_or_create(
        user=user,
        defaults={
            'session_id': session_id, 'phone': phone, 'attempts': 0, 'last_sent_at': now,
            'expires_at': now + timedelta(minutes=PHONE_VERIFY_OTP_TTL_MINUTES),
        },
    )
    if settings.DEBUG:
        # Local/dev visibility — the OTP itself isn't known to us (2Factor
        # generates and checks it), but this confirms the SMS send attempt
        # ran and which phone/session it's tied to.
        print(f"\n{'='*60}\nPhone OTP sent to {phone} (2Factor session {session_id})\n{'='*60}\n")
    return pending


def store_signup(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    form = StoreSignupForm(_parse_json_body(request))
    if not form.is_valid():
        return JsonResponse(
            {'status': 'validation_error', 'errors': {k: v[0] for k, v in form.errors.items()}},
            status=400,
        )

    name = form.cleaned_data['name']
    phone = form.cleaned_data['phone']
    email = form.cleaned_data['email']
    password = form.cleaned_data['password']
    first_name, _, last_name = name.partition(' ')

    user = User.objects.create_user(
        username=email, email=email, password=password,
        first_name=first_name, last_name=last_name,
    )
    StoreProfile.objects.create(user=user, phone=phone)

    if not request.session.session_key:
        request.session.create()
    pre_login_session_key = request.session.session_key

    auth_user = authenticate(request, username=email, password=password)
    if auth_user:
        login(request, auth_user)
        _merge_session_cart_into_user(auth_user, pre_login_session_key)
        _merge_session_ai_chats_into_user(auth_user, pre_login_session_key)

    # Best-effort — the account is already created and the shopper is
    # already logged in above, so a slow/flaky SMS send (or none configured
    # at all) can never fail or delay signup itself. They can verify anytime
    # from Edit Profile.
    try:
        _new_phone_verification(auth_user or user, phone, timezone.now())
        print(f"[signup sms] OTP SMS SENT via 2Factor to {phone}")
    except Exception as e:
        import traceback
        print(f"[signup sms] OTP SMS FAILED to send via 2Factor to {phone}: {e!r}")
        traceback.print_exc()
        logger.warning("Signup verification SMS failed for %s: %s", phone, e)

    cart = _get_or_create_cart(request)
    return JsonResponse({'status': 'ok', 'user': _user_payload(auth_user or user), 'cart': _cart_payload(cart)})


def store_phone_verify_send(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)

    profile, _ = StoreProfile.objects.get_or_create(user=request.user)
    if profile.phone_verified:
        return JsonResponse({'status': 'error', 'detail': 'Your phone number is already verified.'}, status=400)
    if not profile.phone:
        return JsonResponse({'status': 'error', 'detail': 'Add a phone number to your profile first.'}, status=400)

    now = timezone.now()
    existing = PhoneVerification.objects.filter(user=request.user).first()
    if existing and (now - existing.last_sent_at).total_seconds() < PHONE_VERIFY_RESEND_COOLDOWN_SECONDS:
        wait = PHONE_VERIFY_RESEND_COOLDOWN_SECONDS - int((now - existing.last_sent_at).total_seconds())
        return JsonResponse({'status': 'error', 'detail': f'Please wait {wait}s before requesting another code.'}, status=429)

    try:
        _new_phone_verification(request.user, profile.phone, now)
    except Exception as e:
        logger.exception("Phone verification SMS failed for %s: %s", profile.phone, e)
        return JsonResponse({'status': 'error', 'detail': 'Could not send the verification code. Please try again shortly.'}, status=502)

    return JsonResponse({'status': 'ok'})


def store_phone_verify_confirm(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)

    form = PhoneVerifyForm(_parse_json_body(request))
    if not form.is_valid():
        return JsonResponse({'status': 'validation_error', 'errors': {k: v[0] for k, v in form.errors.items()}}, status=400)

    otp = form.cleaned_data['otp']
    pending = PhoneVerification.objects.filter(user=request.user).first()
    if not pending:
        return JsonResponse({'status': 'error', 'detail': 'No pending verification — send a new code first.'}, status=404)

    if pending.is_expired:
        pending.delete()
        return JsonResponse({'status': 'error', 'detail': 'That code has expired — send a new one.'}, status=400)

    if pending.attempts >= PHONE_VERIFY_MAX_ATTEMPTS:
        pending.delete()
        return JsonResponse({'status': 'error', 'detail': 'Too many incorrect attempts — send a new code.'}, status=400)

    try:
        matched = verify_phone_otp(pending.session_id, otp)
    except Exception as e:
        logger.exception("2Factor verify call failed for %s: %s", pending.phone, e)
        return JsonResponse({'status': 'error', 'detail': 'Could not verify that code right now. Please try again shortly.'}, status=502)

    if not matched:
        pending.attempts += 1
        pending.save(update_fields=['attempts'])
        left = PHONE_VERIFY_MAX_ATTEMPTS - pending.attempts
        return JsonResponse({'status': 'error', 'detail': f'Incorrect code — {left} attempt{"s" if left != 1 else ""} left.'}, status=400)

    profile, _ = StoreProfile.objects.get_or_create(user=request.user)
    profile.phone_verified = True
    profile.save(update_fields=['phone_verified'])
    pending.delete()

    return JsonResponse({'status': 'ok', 'user': _user_payload(request.user)})


def store_login(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    form = StoreLoginForm(_parse_json_body(request))
    if not form.is_valid():
        return JsonResponse(
            {'status': 'validation_error', 'errors': {k: v[0] for k, v in form.errors.items()}},
            status=400,
        )

    identifier = form.cleaned_data['identifier'].strip()
    password = form.cleaned_data['password']

    user_obj = User.objects.filter(email__iexact=identifier).first()
    if not user_obj:
        profile = StoreProfile.objects.filter(phone=identifier).first()
        user_obj = profile.user if profile else None

    if not user_obj:
        return JsonResponse({'status': 'error', 'detail': 'No account found with that email or phone.'}, status=400)

    auth_user = authenticate(request, username=user_obj.username, password=password)
    if not auth_user:
        return JsonResponse({'status': 'error', 'detail': 'Incorrect password.'}, status=400)

    if not request.session.session_key:
        request.session.create()
    pre_login_session_key = request.session.session_key

    login(request, auth_user)
    _merge_session_cart_into_user(auth_user, pre_login_session_key)
    _merge_session_ai_chats_into_user(auth_user, pre_login_session_key)

    cart = _get_or_create_cart(request)
    return JsonResponse({'status': 'ok', 'user': _user_payload(auth_user), 'cart': _cart_payload(cart)})


def store_logout(request):
    logout(request)
    return JsonResponse({'status': 'ok'})


def store_profile_update(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)

    form = StoreProfileEditForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse(
            {'status': 'validation_error', 'errors': {k: v[0] for k, v in form.errors.items()}},
            status=400,
        )

    name = form.cleaned_data['name']
    first_name, _, last_name = name.partition(' ')
    request.user.first_name = first_name
    request.user.last_name = last_name
    request.user.save(update_fields=['first_name', 'last_name'])

    profile, _ = StoreProfile.objects.get_or_create(user=request.user)
    profile.phone = form.cleaned_data['phone']
    if form.cleaned_data.get('avatar'):
        profile.avatar = form.cleaned_data['avatar']
    profile.save()

    return JsonResponse({'status': 'ok', 'user': _user_payload(request.user)})


def store_password_change(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)

    form = StorePasswordChangeForm(_parse_json_body(request))
    if not form.is_valid():
        return JsonResponse(
            {'status': 'validation_error', 'errors': {k: v[0] for k, v in form.errors.items()}},
            status=400,
        )

    if not request.user.check_password(form.cleaned_data['current_password']):
        return JsonResponse({'status': 'error', 'detail': 'Current password is incorrect.'}, status=400)

    request.user.set_password(form.cleaned_data['new_password'])
    request.user.save(update_fields=['password'])
    update_session_auth_hash(request, request.user)  # keep the session logged in
    return JsonResponse({'status': 'ok'})


# ── E-Store: cart ────────────────────────────────────────────────────────

def store_cart_get(request):
    cart = _get_or_create_cart(request)
    return JsonResponse(_cart_payload(cart))


def store_cart_add(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    payload = _parse_json_body(request)
    product_id = str(payload.get('product_id', '')).strip()
    name = str(payload.get('name', '')).strip()
    try:
        qty = max(1, int(payload.get('qty', 1)))
    except (TypeError, ValueError):
        qty = 1

    if not product_id or not name:
        return JsonResponse({'status': 'error', 'detail': 'Missing product details.'}, status=400)

    # Price is always taken from the catalogue, never trusted from the
    # client — the JS also sends a `price` for its optimistic UI update, but
    # it's ignored here so a tampered request can't check out at a
    # fabricated price for real inventory.
    product = Product.objects.filter(slug=product_id, is_active=True).first()
    if not product:
        return JsonResponse({'status': 'error', 'detail': 'That product is no longer available.'}, status=404)
    price = product.price

    cart = _get_or_create_cart(request)
    item, created = CartItem.objects.get_or_create(
        cart=cart, product_id=product_id,
        defaults={'product_name': name, 'price': price, 'quantity': qty},
    )
    if not created:
        # Re-adding the same product_id (e.g. after picking a different
        # colour on the detail page) must still update the stored name —
        # otherwise a colour picked on a later add silently never reaches
        # the order, since only the first add's name was ever saved.
        item.quantity += qty
        item.product_name = name
        item.price = price
        item.save(update_fields=['quantity', 'product_name', 'price'])

    return JsonResponse(_cart_payload(cart))


def store_cart_update(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    payload = _parse_json_body(request)
    product_id = str(payload.get('product_id', '')).strip()
    try:
        qty = int(payload.get('qty', 0))
    except (TypeError, ValueError):
        qty = 0

    cart = _get_or_create_cart(request)
    item = cart.items.filter(product_id=product_id).first()
    if item:
        if qty <= 0:
            item.delete()
        else:
            item.quantity = qty
            item.save(update_fields=['quantity'])

    return JsonResponse(_cart_payload(cart))


def store_cart_remove(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    payload = _parse_json_body(request)
    product_id = str(payload.get('product_id', '')).strip()
    cart = _get_or_create_cart(request)
    cart.items.filter(product_id=product_id).delete()
    return JsonResponse(_cart_payload(cart))


def _razorpay_client():
    settings_obj = PaymentSettings.get_solo()
    if razorpay is None or not settings_obj.razorpay_ready:
        return None, settings_obj
    return razorpay.Client(auth=(settings_obj.razorpay_key_id, settings_obj.razorpay_key_secret)), settings_obj


def _create_razorpay_payment_payload(order, amount, razorpay_client, payment_settings, user, profile):
    """Creates a fresh Razorpay order + Payment row for `order` (used both
    at checkout and when retrying a failed/abandoned payment from My
    Orders) and returns what the frontend's Razorpay widget needs. Raises
    on failure — callers decide how to handle that."""
    rp_order = razorpay_client.order.create({
        'amount': int(amount * 100),
        'currency': 'INR',
        'receipt': f'order_{order.pk}_{int(timezone.now().timestamp())}',
        'payment_capture': 1,
    })
    payment = Payment.objects.create(
        order=order, method=Payment.METHOD_RAZORPAY, status=Payment.STATUS_PENDING,
        amount=amount, razorpay_order_id=rp_order['id'],
    )
    return {
        'key_id': payment_settings.razorpay_key_id,
        'razorpay_order_id': rp_order['id'],
        'amount': int(amount * 100),
        'currency': 'INR',
        'payment_pk': payment.pk,
        'name': 'EduTrellis Store',
        'description': f'Order #{order.pk}',
        'prefill': {
            'name': user.get_full_name() or user.username,
            'email': user.email,
            'contact': profile.phone,
        },
    }


def store_checkout(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in to check out.'}, status=401)

    profile, _ = StoreProfile.objects.get_or_create(user=request.user)
    if not profile.phone_verified:
        return JsonResponse({
            'status': 'phone_unverified',
            'detail': 'Please verify your phone number before placing an order.',
        }, status=403)

    cart = _get_or_create_cart(request)
    items = list(cart.items.all())
    if not items:
        return JsonResponse({'status': 'error', 'detail': 'Your cart is empty.'}, status=400)

    payload = _parse_json_body(request)
    use_wallet = bool(payload.get('use_wallet'))
    payment_method = payload.get('payment_method') or Payment.METHOD_COD
    if payment_method not in (Payment.METHOD_COD, Payment.METHOD_RAZORPAY):
        payment_method = Payment.METHOD_COD

    address_form = CheckoutAddressForm(payload)
    if not address_form.is_valid():
        return JsonResponse(
            {'status': 'validation_error', 'errors': {k: v[0] for k, v in address_form.errors.items()}},
            status=400,
        )
    address = address_form.cleaned_data

    fee_settings = FeeSettings.get_solo()
    subtotal = sum((i.subtotal for i in items), Decimal('0'))
    wallet_discount = min(profile.wallet_balance, subtotal) if use_wallet else Decimal('0')
    free_delivery = fee_settings.free_delivery_over > 0 and subtotal >= fee_settings.free_delivery_over
    shipping_fee = Decimal('0') if subtotal == 0 or free_delivery else fee_settings.delivery_fee
    handling_fee = Decimal('0') if subtotal == 0 else fee_settings.handling_fee
    total = max(Decimal('0'), subtotal + shipping_fee + handling_fee - wallet_discount)

    razorpay_client, payment_settings = (None, None)
    if payment_method == Payment.METHOD_RAZORPAY:
        razorpay_client, payment_settings = _razorpay_client()
        if razorpay_client is None:
            payment_method = Payment.METHOD_COD  # gateway not configured — fall back silently

    order = Order.objects.create(
        user=request.user, subtotal=subtotal, wallet_discount=wallet_discount,
        shipping_fee=shipping_fee, handling_fee=handling_fee, total=total,
        recipient_name=address['recipient_name'], recipient_phone=address['recipient_phone'],
        address_line1=address['address_line1'], address_line2=address.get('address_line2', ''),
        city=address['city'], state=address['state'], pincode=address['pincode'],
    )
    OrderItem.objects.bulk_create([
        OrderItem(order=order, product_id=i.product_id, product_name=i.product_name,
                  price=i.price, quantity=i.quantity)
        for i in items
    ])

    if wallet_discount > 0:
        # Guarded atomic UPDATE instead of a Python-level read-modify-write —
        # a double-submitted checkout can't debit the same balance twice or
        # drive it negative, since the second UPDATE simply matches 0 rows
        # once the balance has already dropped below wallet_discount.
        debited = StoreProfile.objects.filter(
            pk=profile.pk, wallet_balance__gte=wallet_discount,
        ).update(wallet_balance=F('wallet_balance') - wallet_discount)
        if not debited:
            logger.warning(
                "Wallet debit skipped for Order #%s — balance changed concurrently for user %s",
                order.pk, request.user.pk,
            )

    cart.items.all().delete()

    razorpay_payload = None
    payment_fallback = False
    if payment_method == Payment.METHOD_RAZORPAY and total > 0:
        try:
            razorpay_payload = _create_razorpay_payment_payload(
                order, total, razorpay_client, payment_settings, request.user, profile,
            )
        except Exception as e:
            logger.exception("Razorpay order creation failed for Order #%s: %s", order.pk, e)
            Payment.objects.create(order=order, method=Payment.METHOD_COD, status=Payment.STATUS_COD_PENDING, amount=total)
            payment_method = Payment.METHOD_COD
            payment_fallback = True
            _send_order_confirmation_email_async(order, payment_method, paid=False)
    else:
        pay_status = Payment.STATUS_PAID if total <= 0 else Payment.STATUS_COD_PENDING
        Payment.objects.create(order=order, method=Payment.METHOD_COD, status=pay_status, amount=total)
        payment_method = Payment.METHOD_COD
        _send_order_confirmation_email_async(order, payment_method, paid=(total <= 0))

    return JsonResponse({
        'status': 'ok',
        'order': _order_payload(order),
        'cart': _cart_payload(cart),
        'user': _user_payload(request.user),
        'payment_method': payment_method,
        'razorpay': razorpay_payload,
        'payment_fallback': payment_fallback,
    })


def store_razorpay_verify(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)

    payload = _parse_json_body(request)
    payment = Payment.objects.filter(
        pk=payload.get('payment_pk'), order__user=request.user, method=Payment.METHOD_RAZORPAY,
    ).first()
    if not payment:
        return JsonResponse({'status': 'error', 'detail': 'Payment record not found.'}, status=404)
    if payment.status == Payment.STATUS_PAID:
        # Already verified — a double-submit (double-click, or Razorpay's
        # handler firing twice) would otherwise re-verify and re-send the
        # order confirmation/admin-notification emails a second time.
        return JsonResponse({'status': 'ok'})

    client, _ = _razorpay_client()
    if not client:
        return JsonResponse({'status': 'error', 'detail': 'Payment gateway is not configured.'}, status=400)

    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': payload.get('razorpay_order_id', ''),
            'razorpay_payment_id': payload.get('razorpay_payment_id', ''),
            'razorpay_signature': payload.get('razorpay_signature', ''),
        })
    except Exception as e:
        logger.warning("Razorpay signature verification failed for Payment #%s: %s", payment.pk, e)
        payment.status = Payment.STATUS_FAILED
        payment.save(update_fields=['status'])
        return JsonResponse({'status': 'error', 'detail': 'Payment verification failed.'}, status=400)

    payment.status = Payment.STATUS_PAID
    payment.razorpay_payment_id = payload.get('razorpay_payment_id', '')
    payment.razorpay_signature = payload.get('razorpay_signature', '')
    payment.save(update_fields=['status', 'razorpay_payment_id', 'razorpay_signature'])
    _send_order_confirmation_email_async(payment.order, Payment.METHOD_RAZORPAY, paid=True)
    return JsonResponse({'status': 'ok'})


def store_order_retry_payment(request, order_id):
    """Lets a shopper pay again for an order whose Razorpay attempt failed
    or was abandoned (closed the popup) — the order and cart items are
    already committed at checkout time, so this just opens a fresh Razorpay
    order for the same total instead of requiring a whole new checkout."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)

    order = Order.objects.filter(pk=order_id, user=request.user).prefetch_related('payments').first()
    if not order:
        return JsonResponse({'status': 'error', 'detail': 'Order not found.'}, status=404)
    if order.status in (Order.STATUS_CANCELLED, Order.STATUS_DELIVERED):
        return JsonResponse({'status': 'error', 'detail': 'This order can no longer be paid online.'}, status=400)

    latest_payment = order.payments.all()[0] if order.payments.all() else None
    if not latest_payment or latest_payment.method != Payment.METHOD_RAZORPAY or latest_payment.status not in (
        Payment.STATUS_FAILED, Payment.STATUS_PENDING,
    ):
        return JsonResponse({'status': 'error', 'detail': 'This order does not have a pending online payment.'}, status=400)

    razorpay_client, payment_settings = _razorpay_client()
    if not razorpay_client:
        return JsonResponse({'status': 'error', 'detail': 'Payment gateway is not configured.'}, status=400)

    profile, _ = StoreProfile.objects.get_or_create(user=request.user)
    try:
        razorpay_payload = _create_razorpay_payment_payload(
            order, order.total, razorpay_client, payment_settings, request.user, profile,
        )
    except Exception as e:
        logger.exception("Razorpay retry-payment order creation failed for Order #%s: %s", order.pk, e)
        return JsonResponse({'status': 'error', 'detail': 'Could not start payment right now — please try again shortly.'}, status=502)

    return JsonResponse({'status': 'ok', 'razorpay': razorpay_payload})


def store_orders_list(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)
    orders = Order.objects.filter(user=request.user).prefetch_related('items', 'payments').order_by('-created_at')
    return JsonResponse({'status': 'ok', 'orders': [_order_payload(o) for o in orders]})


def store_wallet_get(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)
    profile, _ = StoreProfile.objects.get_or_create(user=request.user)
    return JsonResponse({'status': 'ok', 'wallet_balance': float(profile.wallet_balance)})


# ── E-Store: contact ─────────────────────────────────────────────────────

def store_contact(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    form = StoreContactForm(_parse_json_body(request))
    if not form.is_valid():
        return JsonResponse(
            {'status': 'validation_error', 'errors': {k: v[0] for k, v in form.errors.items()}},
            status=400,
        )

    ContactLead.objects.create(
        name=form.cleaned_data['name'],
        phone=form.cleaned_data['phone'],
        email=form.cleaned_data['email'],
        service=form.cleaned_data.get('topic') or 'General enquiry',
        message=form.cleaned_data['message'],
        source=ContactLead.SOURCE_STORE,
    )
    return JsonResponse({'status': 'ok', 'message': "Thanks — your message is with our team."})


def policy_page(request, key):
    policy = get_object_or_404(PolicyPage, key=key)
    return render(request, 'policy_page.html', {'policy': policy})


def custom_404(request, exception=None):
    # edutrellis/urls.py adds a catch-all pattern (matching every path, with
    # or without a trailing slash) so this view renders even with DEBUG=True.
    # That catch-all is itself a URL match, though, so it silently defeats
    # Django's normal APPEND_SLASH redirect (which only fires when the
    # un-slashed path doesn't resolve to anything). Reimplement that check
    # here against myapp.urls directly (which has no catch-all) so e.g.
    # /store and /store/ both work instead of the former 404ing.
    path = request.path
    # Only redirect safe methods — a 302 on POST/PUT/etc. gets turned into a
    # GET by the browser, silently dropping the request body.
    if request.method in ('GET', 'HEAD') and not path.endswith('/'):
        try:
            resolve(path + '/', urlconf='myapp.urls')
            query = f'?{request.META["QUERY_STRING"]}' if request.META.get('QUERY_STRING') else ''
            return redirect(path + '/' + query)
        except Resolver404:
            pass
    return render(request, '404.html', status=404)


def contact_lead(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    form = ContactLeadForm(request.POST)

    if not form.is_valid():
        return JsonResponse(
            {
                'status': 'validation_error',
                'errors': {key: value[0] for key, value in form.errors.items()}
            },
            status=400,
        )

    name    = form.cleaned_data['name']
    phone   = form.cleaned_data['phone']
    email   = form.cleaned_data['email']
    service = form.cleaned_data.get('service', '')
    message = form.cleaned_data.get('message', '')

    # ── Always save the lead to the database first so no inquiry is ever lost ──
    try:
        ContactLead.objects.create(
            name=name,
            phone=phone,
            email=email,
            service=service or '',
            message=message or '',
            source=ContactLead.SOURCE_EDUTRELLIS,
        )
    except Exception as db_err:
        logger.exception("DB save failed for lead from %s: %s", email, db_err)
        # Continue — we still attempt the email even if DB write fails

    subject = f"New Lead from EduTrellis \u2014 {name}"
    body = (
        "New Lead Received from EduTrellis Website\n"
        "==========================================\n"
        f"Name    : {name}\n"
        f"Phone   : {phone}\n"
        f"Email   : {email}\n"
        f"Service : {service or 'Not selected'}\n"
        f"Message : {message or 'No message provided'}\n"
        "=========================================="
    )

    try:
        send_store_email(subject, body, [get_notify_email()])
    except BadHeaderError:
        logger.error("BadHeaderError: possible header injection from %s", email)
        return JsonResponse(
            {'status': 'error', 'detail': 'Invalid data in form fields.'},
            status=400,
        )
    except TimeoutError as te:
        logger.error("SMTP timeout for lead from %s: %s", email, te)
        return JsonResponse(
            {
                'status': 'error',
                'detail': (
                    'Your message was saved but the email notification timed out. '
                    'Our team will still see your inquiry — we\'ll contact you soon!'
                )
            },
            status=200,
        )
    except Exception as e:
        logger.exception("SMTP send_mail failed for lead from %s: %s", email, e)
        return JsonResponse(
            {
                'status': 'error',
                'detail': (
                    'Your inquiry has been saved. However the email notification '
                    'failed (%s). Our team will follow up shortly!' % type(e).__name__
                )
            },
            status=200,
        )

    return JsonResponse({'status': 'ok', 'message': 'Message sent successfully.'})


def websitecreation_contact(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    form = ContactLeadForm(_parse_json_body(request))
    if not form.is_valid():
        return JsonResponse(
            {'status': 'validation_error', 'errors': {k: v[0] for k, v in form.errors.items()}},
            status=400,
        )

    ContactLead.objects.create(
        name=form.cleaned_data['name'],
        phone=form.cleaned_data['phone'],
        email=form.cleaned_data['email'],
        service=form.cleaned_data.get('service', ''),
        message=form.cleaned_data.get('message', ''),
        source=ContactLead.SOURCE_WEBSITECREATION,
    )
    return JsonResponse({'status': 'ok', 'message': "Thanks — we'll get back to you within 24 hours."})


# ── Custom store admin dashboard (staff-only, replaces linking to /admin/) ──

def _dashboard_guard(request):
    """Anonymous or non-staff visitors are bounced back to the storefront,
    where they can log in through the existing auth modal."""
    return request.user.is_authenticated and request.user.is_staff


def dashboard_staff_required(view_func):
    """Every dashboard_* view needs this same staff-only check — used to be
    copy-pasted as the first two lines of each one (easy to forget on a new
    view, silently exposing a staff-only page). Applying this decorator
    instead makes the guard structurally impossible to skip."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _dashboard_guard(request):
            return redirect('estore')
        return view_func(request, *args, **kwargs)
    return wrapper


@dashboard_staff_required
def dashboard_home(request):
    context = {
        'active': 'home',
        'total_users': User.objects.count(),
        'total_leads': ContactLead.objects.count(),
        'total_carts': Cart.objects.count(),
        'cart_items': CartItem.objects.count(),
        'total_orders': Order.objects.count(),
        'total_products': Product.objects.count(),
        'total_payments': Payment.objects.count(),
        'recent_users': User.objects.select_related('store_profile').order_by('-date_joined')[:5],
        'recent_leads': ContactLead.objects.order_by('-created_at')[:5],
    }
    return render(request, 'dashboard/home.html', context)


@dashboard_staff_required
def dashboard_signups(request):
    q = request.GET.get('q', '').strip()
    users = User.objects.select_related('store_profile').order_by('-date_joined')
    if q:
        users = users.filter(
            Q(username__icontains=q) | Q(email__icontains=q) |
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(store_profile__phone__icontains=q)
        )
    return render(request, 'dashboard/signups.html', {'active': 'signups', 'users': users, 'q': q})


@dashboard_staff_required
def dashboard_signup_edit(request, pk):
    edited_user = get_object_or_404(User, pk=pk)
    profile, _ = StoreProfile.objects.get_or_create(user=edited_user)
    form = SignupEditForm(
        request.POST or None, instance=edited_user,
        initial={'phone': profile.phone, 'wallet_balance': profile.wallet_balance},
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        profile.phone = form.cleaned_data['phone']
        profile.wallet_balance = form.cleaned_data['wallet_balance']
        profile.save(update_fields=['phone', 'wallet_balance'])
        return redirect('dashboard_signups')
    return render(request, 'dashboard/signup_form.html', {'active': 'signups', 'form': form, 'edited_user': edited_user})


@dashboard_staff_required
def dashboard_signup_delete(request, pk):
    if request.method == 'POST':
        target = get_object_or_404(User, pk=pk)
        if target.pk == request.user.pk:
            messages.error(request, "You can't delete your own account from here.")
        elif target.is_staff or target.is_superuser:
            messages.error(request, "Staff and admin accounts can't be deleted from here — use Django admin if you're sure.")
        elif Order.objects.filter(user=target).exists():
            # Deleting the User cascades and wipes their Order/OrderItem/
            # Payment rows — real financial records, not just a login.
            messages.error(request, "This customer has order history — deleting the account would erase those orders and payment records. Use Django admin if you're sure.")
        else:
            target.delete()
            messages.success(request, 'Customer account deleted.')
    return redirect('dashboard_signups')


@dashboard_staff_required
def dashboard_contacts(request):
    q = request.GET.get('q', '').strip()
    leads = ContactLead.objects.order_by('-created_at')
    if q:
        leads = leads.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q) |
            Q(service__icontains=q) | Q(message__icontains=q)
        )

    all_leads = list(leads)
    groups = [
        {'source': value, 'label': label, 'leads': [l for l in all_leads if l.source == value]}
        for value, label in ContactLead.SOURCE_CHOICES
    ]
    return render(request, 'dashboard/contacts.html', {
        'active': 'contacts', 'leads': all_leads, 'groups': groups, 'q': q,
    })


@dashboard_staff_required
def dashboard_contact_delete(request, pk):
    if request.method == 'POST':
        get_object_or_404(ContactLead, pk=pk).delete()
    return redirect('dashboard_contacts')


@dashboard_staff_required
def dashboard_categories(request):
    q = request.GET.get('q', '').strip()
    categories = Category.objects.all()
    if q:
        categories = categories.filter(Q(name__icontains=q) | Q(slug__icontains=q))
    return render(request, 'dashboard/categories.html', {'active': 'categories', 'categories': categories, 'q': q})


@dashboard_staff_required
def dashboard_category_add(request):
    form = CategoryForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('dashboard_categories')
    return render(request, 'dashboard/category_form.html', {'active': 'categories', 'form': form, 'category': None})


@dashboard_staff_required
def dashboard_category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, request.FILES or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('dashboard_categories')
    return render(request, 'dashboard/category_form.html', {'active': 'categories', 'form': form, 'category': category})


@dashboard_staff_required
def dashboard_category_delete(request, pk):
    if request.method == 'POST':
        get_object_or_404(Category, pk=pk).delete()
    return redirect('dashboard_categories')


@dashboard_staff_required
def dashboard_orders(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    orders = Order.objects.select_related('user').prefetch_related('items', 'payments').order_by('-created_at')
    if q:
        orders = orders.filter(
            Q(user__username__icontains=q) | Q(user__email__icontains=q) |
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q)
        )
    if status:
        orders = orders.filter(status=status)
    return render(request, 'dashboard/orders.html', {
        'active': 'orders', 'orders': orders, 'q': q, 'status': status,
        'status_choices': Order.STATUS_CHOICES,
    })


@dashboard_staff_required
def dashboard_delivery(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    orders = Order.objects.select_related('user').prefetch_related('payments').filter(recipient_name__gt='').order_by('-created_at')
    if q:
        orders = orders.filter(
            Q(recipient_name__icontains=q) | Q(recipient_phone__icontains=q) |
            Q(city__icontains=q) | Q(pincode__icontains=q)
        )
    if status:
        orders = orders.filter(status=status)
    return render(request, 'dashboard/delivery.html', {
        'active': 'delivery', 'orders': orders, 'q': q, 'status': status,
        'status_choices': Order.STATUS_CHOICES,
    })


@dashboard_staff_required
def dashboard_order_status_update(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if request.method == 'POST':
        form = OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            order.maybe_credit_wallet()
    return redirect('dashboard_orders')


@dashboard_staff_required
def dashboard_products(request):
    q = request.GET.get('q', '').strip()
    products = Product.objects.select_related('category').all()
    if q:
        products = products.filter(
            Q(name__icontains=q) | Q(brand__icontains=q) | Q(slug__icontains=q) | Q(tags__icontains=q)
        )
    return render(request, 'dashboard/products.html', {'active': 'products', 'products': products, 'q': q})


@dashboard_staff_required
def dashboard_product_add(request):
    form = ProductForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        product = form.save()
        # Images/video/colors are added on the edit page, once the product
        # (and therefore the FK the image/color formsets need) exists.
        return redirect('dashboard_product_edit', pk=product.pk)
    return render(request, 'dashboard/product_form.html', {
        'active': 'products', 'form': form, 'product': None,
        'image_formset': None, 'color_formset': None,
    })


@dashboard_staff_required
def dashboard_product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, request.FILES or None, instance=product)
    image_formset = ProductImageFormSet(request.POST or None, request.FILES or None, instance=product, prefix='images')
    color_formset = ProductColorFormSet(request.POST or None, request.FILES or None, instance=product, prefix='colors')
    if request.method == 'POST' and form.is_valid() and image_formset.is_valid() and color_formset.is_valid():
        form.save()
        image_formset.save()
        color_formset.save()
        return redirect('dashboard_products')
    return render(request, 'dashboard/product_form.html', {
        'active': 'products', 'form': form, 'product': product,
        'image_formset': image_formset, 'color_formset': color_formset,
    })


@dashboard_staff_required
def dashboard_product_delete(request, pk):
    if request.method == 'POST':
        get_object_or_404(Product, pk=pk).delete()
    return redirect('dashboard_products')


@dashboard_staff_required
def dashboard_seed_reviews(request):
    if request.method == 'POST':
        messages.success(request, seed_demo_reviews())
    return redirect('dashboard_products')


@dashboard_staff_required
def dashboard_about(request):
    about = AboutUsContent.get_solo()
    form = AboutUsContentForm(request.POST or None, request.FILES or None, instance=about)
    saved = False
    if request.method == 'POST' and form.is_valid():
        form.save()
        saved = True
        form = AboutUsContentForm(instance=about)
    return render(request, 'dashboard/about_form.html', {'active': 'about', 'form': form, 'about': about, 'saved': saved})


@dashboard_staff_required
def dashboard_policies(request):
    policies = PolicyPage.objects.all()
    return render(request, 'dashboard/policies.html', {'active': 'policies', 'policies': policies})


@dashboard_staff_required
def dashboard_policy_edit(request, pk):
    policy = get_object_or_404(PolicyPage, pk=pk)
    form = PolicyPageForm(request.POST or None, instance=policy)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('dashboard_policies')
    return render(request, 'dashboard/policy_form.html', {'active': 'policies', 'form': form, 'policy': policy})


@dashboard_staff_required
def dashboard_payment_settings(request):
    settings_obj = PaymentSettings.get_solo()
    form = PaymentSettingsForm(request.POST or None, instance=settings_obj)
    saved = False
    if request.method == 'POST' and form.is_valid():
        form.save()
        saved = True
        form = PaymentSettingsForm(instance=settings_obj)
    return render(request, 'dashboard/payment_settings.html', {
        'active': 'payment_settings', 'form': form, 'settings_obj': settings_obj,
        'razorpay_installed': razorpay is not None, 'saved': saved,
    })


@dashboard_staff_required
def dashboard_email_settings(request):
    return render(request, 'dashboard/email_settings.html', {
        'active': 'email_settings',
        'smtp_host': settings.EMAIL_HOST,
        'smtp_user': settings.EMAIL_HOST_USER,
        'notify_email': settings.LEAD_RECIPIENT_EMAIL,
    })


@dashboard_staff_required
def dashboard_email_settings_test(request):
    if request.method == 'POST':
        try:
            send_store_email(
                'EduTrellis Store — test email',
                'This is a test email from your store\'s Email Settings page. If you received this, SMTP is configured correctly.',
                [get_notify_email()],
            )
            messages.success(request, f'Test email sent to {get_notify_email()}.')
        except Exception as exc:
            logger.exception("Test email failed: %s", exc)
            messages.error(request, f'Could not send test email: {exc}')
    return redirect('dashboard_email_settings')


@dashboard_staff_required
def dashboard_pwa_settings(request):
    settings_obj = PWASettings.get_solo()
    form = PWASettingsForm(request.POST or None, request.FILES or None, instance=settings_obj)
    saved = False
    if request.method == 'POST' and form.is_valid():
        form.save()
        saved = True
        form = PWASettingsForm(instance=settings_obj)
    return render(request, 'dashboard/pwa_settings.html', {
        'active': 'pwa_settings', 'form': form, 'settings_obj': settings_obj, 'saved': saved,
    })


@dashboard_staff_required
def dashboard_fee_settings(request):
    settings_obj = FeeSettings.get_solo()
    form = FeeSettingsForm(request.POST or None, instance=settings_obj)
    saved = False
    if request.method == 'POST' and form.is_valid():
        form.save()
        saved = True
        form = FeeSettingsForm(instance=settings_obj)
    return render(request, 'dashboard/fee_settings.html', {
        'active': 'fee_settings', 'form': form, 'settings_obj': settings_obj, 'saved': saved,
    })


@dashboard_staff_required
def dashboard_payments(request):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    payments = Payment.objects.select_related('order', 'order__user').order_by('-created_at')
    if q:
        payments = payments.filter(
            Q(order__id__icontains=q) | Q(order__user__username__icontains=q) |
            Q(order__user__email__icontains=q) | Q(razorpay_order_id__icontains=q) |
            Q(razorpay_payment_id__icontains=q)
        )
    if status:
        payments = payments.filter(status=status)
    return render(request, 'dashboard/payments.html', {
        'active': 'payments', 'payments': payments, 'q': q, 'status': status,
        'status_choices': Payment.STATUS_CHOICES,
    })


@dashboard_staff_required
def dashboard_backup(request):
    settings_obj = DropboxSettings.get_solo()
    backups = []
    list_error = None
    if settings_obj.is_configured:
        try:
            backups = dropbox_backup.list_backups(settings_obj)
        except dropbox_backup.BackupError as exc:
            list_error = str(exc)

    return render(request, 'dashboard/backup.html', {
        'active': 'backup', 'settings_obj': settings_obj, 'backups': backups,
        'list_error': list_error, 'dropbox_installed': dropbox_backup.dropbox is not None,
        'backup_folder': dropbox_backup.BACKUP_FOLDER,
    })


@dashboard_staff_required
def dashboard_backup_settings(request):
    settings_obj = DropboxSettings.get_solo()
    form = DropboxSettingsForm(request.POST or None, instance=settings_obj)
    saved = False
    if request.method == 'POST' and form.is_valid():
        form.save()
        saved = True
        form = DropboxSettingsForm(instance=settings_obj)
    return render(request, 'dashboard/backup_settings.html', {
        'active': 'backup', 'form': form, 'settings_obj': settings_obj, 'saved': saved,
        'dropbox_installed': dropbox_backup.dropbox is not None,
    })


@dashboard_staff_required
def dashboard_backup_run(request):
    if request.method == 'POST':
        settings_obj = DropboxSettings.get_solo()
        try:
            filename = dropbox_backup.create_backup(settings_obj)
            messages.success(request, f'Backup saved to Dropbox as "{filename}".')
        except dropbox_backup.BackupError as exc:
            messages.error(request, str(exc))
    return redirect('dashboard_backup')


@dashboard_staff_required
def dashboard_backup_restore(request):
    if request.method == 'POST':
        settings_obj = DropboxSettings.get_solo()
        filename = request.POST.get('filename', '').strip()
        if not filename:
            messages.error(request, 'Choose a backup to restore first.')
        else:
            try:
                dropbox_backup.restore_backup(settings_obj, filename)
                # restore_backup just swapped out db.sqlite3 from under this
                # very request, taking the django_session table — and this
                # request's own session row — with it. Without recreating it,
                # SessionMiddleware's save() at the end of the request can't
                # find the row to UPDATE and raises SessionInterrupted.
                # must_create=True forces an INSERT into the freshly-restored
                # table instead, so the admin doesn't get logged out or hit
                # an error page by restoring a backup.
                request.session.save(must_create=True)
                messages.success(request, f'Database restored from "{filename}". Restart the app if you notice anything odd.')
            except dropbox_backup.BackupError as exc:
                messages.error(request, str(exc))
    return redirect('dashboard_backup')


def dashboard_logout(request):
    logout(request)
    return redirect('estore')


# ── AI Chat (/AI/, uses the same store account as /store/) ─────────────────

AI_CHAT_RATE_LIMIT = 20           # messages
AI_CHAT_RATE_WINDOW = 10 * 60     # per 10 minutes, per IP
AI_CHAT_MAX_MESSAGE_CHARS = 4000
AI_CHAT_MAX_HISTORY = 20          # most recent saved messages sent to the model as context
AI_CONVERSATION_TITLE_CHARS = 60
AI_GUEST_MESSAGE_LIMIT = 6        # free messages before a guest must log in/sign up
# ~1.5MB of raw image data as a base64 data: URI (~2M chars) — well under
# Django's default 2.5MB DATA_UPLOAD_MAX_MEMORY_SIZE for the whole request
# body, so an oversized image gets our own clean error instead of Django's
# generic one. The client also resizes/compresses before ever uploading.
AI_IMAGE_MAX_DATA_URI_CHARS = 2_000_000
AI_ACCOUNT_CART_ITEM_LIMIT = 10
AI_ACCOUNT_ORDER_LIMIT = 5
AI_LIGHT_SEARCH_RATE_LIMIT = 20   # live web searches per IP per AI_CHAT_RATE_WINDOW — the paid/metered part of Light mode


def _ai_account_context(user):
    """A compact, bounded snapshot of the logged-in user's own store data —
    cart contents and recent orders — so the assistant can actually answer
    'what's in my cart' / 'where's my order' instead of only explaining how
    to go check. Always scoped to `user` (the authenticated request.user),
    so there's no path here that can pull another shopper's data. Computed
    fresh on every request rather than cached, so it can't go stale mid-
    conversation if the cart or an order status changes."""
    lines = [f"Logged in as: {user.first_name or user.username}."]

    profile = getattr(user, 'store_profile', None)
    if profile:
        lines.append(f"Wallet balance: Rs {profile.wallet_balance}.")

    cart = Cart.objects.filter(user=user).first()
    cart_items = list(cart.items.all()[:AI_ACCOUNT_CART_ITEM_LIMIT]) if cart else []
    if cart_items:
        total_qty = sum(i.quantity for i in cart_items)
        subtotal = sum((i.subtotal for i in cart_items), Decimal('0'))
        lines.append(f"Current cart ({total_qty} item(s), Rs {subtotal} subtotal):")
        for i in cart_items:
            lines.append(f"- {i.product_name} x{i.quantity} — Rs {i.subtotal}")
    else:
        lines.append("Current cart: empty.")

    orders = list(
        Order.objects.filter(user=user).prefetch_related('items').order_by('-created_at')[:AI_ACCOUNT_ORDER_LIMIT]
    )
    if orders:
        lines.append(f"Recent orders (most recent {len(orders)}):")
        for o in orders:
            item_summary = ', '.join(f"{it.product_name} x{it.quantity}" for it in list(o.items.all())[:5])
            lines.append(
                f"- Order #{o.pk}: {o.get_status_display()}, placed "
                f"{timezone.localtime(o.created_at):%d %b %Y}, total Rs {o.total}, "
                f"payment: {o.payment_label or 'pending'}. Items: {item_summary}"
            )
    else:
        lines.append("Orders: none placed yet.")

    return '\n'.join(lines)


def _ai_owner_filter(request):
    """Logged-in users own conversations by user FK; guests own them by the
    session_key their browser already carries (same session used for the
    anonymous cart) — that's what lets a guest's chat survive a page reload
    and then get handed to their account the moment they log in. Deliberately
    does NOT create a session for a guest that doesn't have one yet — a plain
    page view or list/read call has no conversation to attach to anyway, and
    forcing a new database-backed session row on every cookie-less visit is
    an easy way to grow django_session unbounded. Only ai_chat_send (which
    actually needs a stable key to save a message under) creates one."""
    if request.user.is_authenticated:
        return Q(user=request.user)
    session_key = request.session.session_key
    if not session_key:
        return Q(pk__in=[])
    return Q(user__isnull=True, session_key=session_key)


def ai_manifest(request):
    # Same brand red as the rest of edutrellis.in's favicon, but as real
    # 192x192/512x512 PNGs rather than the site's actual favicon.ico (which
    # is only 48x48). Android Chrome checks the real pixel dimensions of a
    # manifest icon against its declared size before it'll consider the app
    # installable — a declared-but-not-actual 192/512 icon is why the
    # install prompt was never firing on Android at all (desktop Chrome is
    # more lenient about it, which is why it could look fine there).
    icon_192 = request.build_absolute_uri(static_url('ai-icon-192.png'))
    icon_512 = request.build_absolute_uri(static_url('ai-icon-512.png'))
    manifest = {
        'name': 'EduTrellis AI',
        'short_name': 'EduTrellis AI',
        'description': 'Chat with EduTrellis AI about our services, your store account, and more.',
        'start_url': '/AI/',
        'scope': '/AI/',
        'display': 'standalone',
        'background_color': '#ffffff',
        'theme_color': '#e8001e',
        'icons': [
            {'src': icon_192, 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': icon_512, 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': icon_512, 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    return JsonResponse(manifest, content_type='application/manifest+json')


def ai_page(request):
    conversations = list(
        AIConversation.objects.filter(_ai_owner_filter(request))
        .values('id', 'title', 'updated_at').order_by('-updated_at')[:100]
    )
    for c in conversations:
        c['updated_at'] = timezone.localtime(c['updated_at']).isoformat()
    models = [
        {'key': key, 'label': cfg['label'], 'description': cfg['description']}
        for key, cfg in ai_chat.MODELS.items() if key != 'vision'
    ]
    model_labels = {key: cfg['label'] for key, cfg in ai_chat.MODELS.items()}
    return render(request, 'ai.html', {
        'ai_authenticated': request.user.is_authenticated,
        'ai_user': _user_payload(request.user) if request.user.is_authenticated else None,
        'ai_conversations': conversations,
        'ai_guest_limit': AI_GUEST_MESSAGE_LIMIT,
        'ai_guest_used': 0 if request.user.is_authenticated else request.session.get('ai_guest_msg_count', 0),
        'ai_models': models,
        'ai_default_model': ai_chat.DEFAULT_MODEL_KEY,
        'ai_default_model_label': model_labels[ai_chat.DEFAULT_MODEL_KEY],
        'ai_model_labels': model_labels,
        'ai_github_oauth_available': bool(settings.GITHUB_OAUTH_CLIENT_ID),
    })


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    return forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR', 'unknown')


def ai_chat_send(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    # A real, billable API key sits behind this — a basic per-IP rate limit
    # is the brake against an account (or a guest, or a script cycling
    # through either) hammering it. Uses Django's cache, which on a
    # single-process dev server is exact; under multiple gunicorn workers
    # each worker has its own count, so the effective ceiling is
    # (limit × worker count) — a soft brake, not a hard guarantee.
    ip = _client_ip(request)
    cache_key = f'ai_chat_rate:{ip}'
    count = cache.get(cache_key, 0)
    if count >= AI_CHAT_RATE_LIMIT:
        return JsonResponse(
            {'status': 'error', 'detail': "You're sending messages too quickly — please wait a bit and try again."},
            status=429,
        )
    # Counted immediately, before any further validation — a request that
    # gets rejected downstream (bad payload, guest cap, etc.) still cost a
    # request and should still count against the brake, otherwise a blocked
    # guest can hit this endpoint an unlimited number of times for free.
    cache.set(cache_key, count + 1, AI_CHAT_RATE_WINDOW)

    payload = _parse_json_body(request)
    if not isinstance(payload, dict):
        return JsonResponse({'status': 'error', 'detail': 'Invalid request body.'}, status=400)
    message = str(payload.get('message', ''))[:AI_CHAT_MAX_MESSAGE_CHARS].strip()

    image_data = payload.get('image')
    if not isinstance(image_data, str) or not image_data.startswith('data:image/'):
        image_data = ''
    if image_data and len(image_data) > AI_IMAGE_MAX_DATA_URI_CHARS:
        return JsonResponse({'status': 'error', 'detail': 'That image is too large — please use a smaller one.'}, status=400)

    # document_text/document_name come from a prior call to /AI/api/extract/
    # (the raw file itself is never sent here) — re-capped defensively since
    # the client is untrusted, even though it already capped it once too.
    document_text = payload.get('document_text')
    document_name = payload.get('document_name')
    if isinstance(document_text, str) and document_text.strip() and isinstance(document_name, str) and document_name.strip():
        document_text = document_text.strip()[:doc_extract.MAX_CHARS]
        document_name = document_name.strip()[:255]
    else:
        document_text = ''
        document_name = ''

    if not message and not image_data and not document_text:
        return JsonResponse({'status': 'error', 'detail': 'No message provided.'}, status=400)

    requested_language = payload.get('language')
    language = requested_language if requested_language in ai_chat.LANGUAGES else ai_chat.DEFAULT_LANGUAGE

    # An attached image can only be understood by the vision model —
    # whatever the user had selected, this specific turn is auto-routed
    # there. Otherwise use their chosen model, falling back to the default
    # for anything unrecognized (stale client, tampered value, etc.).
    if image_data:
        model_key = 'vision'
    else:
        requested_model_key = payload.get('model')
        model_key = requested_model_key if requested_model_key in ai_chat.MODELS else ai_chat.DEFAULT_MODEL_KEY

    if not request.user.is_authenticated:
        if not request.session.session_key:
            request.session.create()
        guest_count = request.session.get('ai_guest_msg_count', 0)
        if guest_count >= AI_GUEST_MESSAGE_LIMIT:
            return JsonResponse({
                'status': 'login_required',
                'detail': "You've reached the free message limit — log in or sign up to keep chatting. Your conversation is saved and will carry over.",
            }, status=403)

    owner_filter = _ai_owner_filter(request)
    conversation_id = payload.get('conversation_id')
    conversation = None
    if conversation_id:
        # payload is untrusted JSON — conversation_id could be a string, a
        # float, a list/dict, etc. Casting explicitly here means a malformed
        # value is just "not found" instead of an unhandled TypeError from
        # the ORM's pk lookup (which, with DEBUG on, would otherwise hand
        # back a full stack trace to whoever sent it).
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return JsonResponse({'status': 'error', 'detail': 'Conversation not found.'}, status=404)
        conversation = AIConversation.objects.filter(owner_filter, pk=conversation_id).first()
        if not conversation:
            return JsonResponse({'status': 'error', 'detail': 'Conversation not found.'}, status=404)
    if conversation is None:
        title = message[:AI_CONVERSATION_TITLE_CHARS] if message else (document_name or 'Image')
        if request.user.is_authenticated:
            conversation = AIConversation.objects.create(user=request.user, title=title)
        else:
            conversation = AIConversation.objects.create(session_key=request.session.session_key, title=title)

    AIMessage.objects.create(
        conversation=conversation, role=AIMessage.ROLE_USER, content=message,
        image_data=image_data, document_name=document_name,
    )
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=['updated_at'])

    if not request.user.is_authenticated:
        request.session['ai_guest_msg_count'] = request.session.get('ai_guest_msg_count', 0) + 1

    model_cfg = ai_chat.MODELS[model_key]
    recent = list(
        conversation.messages.order_by('-created_at')
        .values('role', 'content', 'image_data', 'document_name')[:AI_CHAT_MAX_HISTORY]
    )
    recent.reverse()
    clean_history = []
    for m in recent:
        if m['image_data'] and model_cfg['vision']:
            content = [
                {'type': 'text', 'text': m['content'] or 'Describe this image.'},
                {'type': 'image_url', 'image_url': {'url': m['image_data']}},
            ]
        elif m['image_data']:
            # Model can't see images (a different mode is now selected) —
            # degrade to a plain-text note instead of sending it multimodal
            # content it can't parse.
            content = (m['content'] + ' [image attached]').strip()
        elif m['document_name']:
            # Only the filename was kept for older turns — the extracted
            # text itself is never persisted, so re-sending history doesn't
            # re-transmit a whole document on every follow-up message. The
            # full text for THIS turn gets spliced in below instead.
            content = (m['content'] + f" [Attached document: {m['document_name']}]").strip()
        else:
            content = m['content']
        clean_history.append({'role': m['role'], 'content': content})

    # Splice the freshly-extracted full document text into this turn only —
    # the placeholder above (from the DB) is what gets replayed on future
    # turns instead, keeping per-message token cost bounded.
    if document_text and clean_history and clean_history[-1]['role'] == AIMessage.ROLE_USER:
        clean_history[-1]['content'] = (
            f"[Attached document: {document_name}]\n{document_text}\n\n---\n"
            f"{message or 'Please review the attached document.'}"
        )

    account_context = _ai_account_context(request.user) if request.user.is_authenticated else None

    # Once the secret phrase has appeared anywhere in this conversation, the
    # warm/personal tone stays on for the rest of it rather than resetting
    # every message. The greeting/introduction itself, though, should only
    # happen on the message where she actually said the phrase — not be
    # repeated on every later message just because the tone stays on.
    is_sumudrika = any(
        m['role'] == AIMessage.ROLE_USER and ai_chat.is_sumudrika_trigger(m['content'])
        for m in recent
    )
    is_sumudrika_greet = bool(recent) and recent[-1]['role'] == AIMessage.ROLE_USER \
        and ai_chat.is_sumudrika_trigger(recent[-1]['content'])

    # EduTrellis Light: check the saved knowledge base first (free, no
    # external call); only fall back to a live web search — rate-limited
    # separately since it's the one path here that costs real search-API
    # quota — when nothing relevant is already saved.
    retrieved_context = retrieved_source = None
    if model_key == 'light' and message:
        kb_entries = light_mode.search_knowledge_base(
            message,
            user=request.user if request.user.is_authenticated else None,
            session_key=request.session.session_key or '',
        )
        if kb_entries:
            retrieved_context = light_mode.context_from_entries(kb_entries)
            retrieved_source = 'knowledge_base'
        else:
            search_cache_key = f'ai_light_search_rate:{ip}'
            search_count = cache.get(search_cache_key, 0)
            if search_count < AI_LIGHT_SEARCH_RATE_LIMIT:
                cache.set(search_cache_key, search_count + 1, AI_CHAT_RATE_WINDOW)
                retrieved_context, retrieved_source = light_mode.web_search_and_save(message)

    def event_stream():
        full_reply = ''
        had_error = False
        try:
            for chunk in ai_chat.stream_chat(
                clean_history, model_key=model_key, account_context=account_context,
                retrieved_context=retrieved_context, retrieved_source=retrieved_source,
                sumudrika=is_sumudrika, sumudrika_greet=is_sumudrika_greet, language=language,
            ):
                full_reply += chunk
                yield chunk
        except Exception as e:
            # ai_chat.stream_chat already retries transient failures on its
            # own before ever raising here — reaching this point means every
            # retry failed (or a real answer had already started streaming
            # when it broke, so a clean retry wasn't possible). Either way,
            # what's in full_reply (if anything) is not a complete, trustworthy
            # answer, so it must never be saved as one.
            logger.exception("AI chat stream failed after retries: %s", e)
            had_error = True
            yield "\n\n[Something went wrong on our end — please try again.]"
        finally:
            # The conversation can have been deleted (by this same user, in
            # another tab, or via the sidebar delete button) while this reply
            # was still streaming — check it still exists before trying to
            # attach a message to it, instead of letting that blow up here.
            if full_reply.strip() and not had_error:
                try:
                    if AIConversation.objects.filter(pk=conversation.pk).exists():
                        AIMessage.objects.create(
                            conversation=conversation, role=AIMessage.ROLE_ASSISTANT,
                            content=full_reply, model_key=model_key,
                        )
                except Exception:
                    logger.exception("Failed to save AI assistant reply for conversation %s", conversation.pk)

                # Every real question+answer, from any model, from any user
                # (guest or logged in) — feeds EduTrellis Light's knowledge
                # base, not just Light's own conversations. A turn with a
                # file/image attached, or whose answer touched this user's
                # own account details, is still saved — just scoped private
                # to them (see light_mode.save_from_chat) instead of shared.
                # Skipped for the sumudrika easter egg — that reply is warm,
                # personal content about Rudra and his wife, never something
                # worth remembering as a reusable "fact". Never blocks or
                # fails the actual chat reply if this errors.
                if not is_sumudrika:
                    try:
                        light_mode.save_from_chat(
                            message, full_reply, account_context=account_context,
                            had_attachment=bool(image_data or document_text),
                            user=request.user if request.user.is_authenticated else None,
                            session_key=request.session.session_key or '',
                        )
                    except Exception:
                        logger.exception("Failed to save chat turn to the Light knowledge base")

    response = StreamingHttpResponse(event_stream(), content_type='text/plain; charset=utf-8')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    response['X-Conversation-Id'] = str(conversation.id)
    response['X-Model-Key'] = model_key
    return response


AI_DOC_RATE_LIMIT = 15
AI_DOC_MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # raw file cap, before extraction


def ai_extract_document(request):
    """Extracts text from an uploaded PDF/DOCX/CSV and hands it back to the
    browser — the raw file is never stored or forwarded anywhere else, and
    the caller sends the returned text back in the next /AI/api/send/ call
    (see ai_chat_send's document_text/document_name handling)."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    ip = _client_ip(request)
    cache_key = f'ai_doc_rate:{ip}'
    count = cache.get(cache_key, 0)
    if count >= AI_DOC_RATE_LIMIT:
        return JsonResponse(
            {'status': 'error', 'detail': "You're uploading files too quickly — please wait a bit and try again."},
            status=429,
        )
    cache.set(cache_key, count + 1, AI_CHAT_RATE_WINDOW)

    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'status': 'error', 'detail': 'No file provided.'}, status=400)
    if f.size > AI_DOC_MAX_UPLOAD_BYTES:
        return JsonResponse({'status': 'error', 'detail': 'That file is too large — please use one under 8MB.'}, status=400)

    try:
        text, truncated = doc_extract.extract(f.name, f.read())
    except doc_extract.ExtractError as e:
        return JsonResponse({'status': 'error', 'detail': str(e)}, status=400)
    except Exception:
        logger.exception("Document extraction failed for %s", f.name)
        return JsonResponse({'status': 'error', 'detail': "Couldn't read that file — please try a different one."}, status=400)

    return JsonResponse({'status': 'ok', 'filename': f.name, 'text': text, 'truncated': truncated})


def ai_conversations_list(request):
    conversations = list(
        AIConversation.objects.filter(_ai_owner_filter(request))
        .values('id', 'title', 'updated_at').order_by('-updated_at')[:100]
    )
    for c in conversations:
        c['updated_at'] = timezone.localtime(c['updated_at']).isoformat()
    return JsonResponse({'status': 'ok', 'conversations': conversations})


def ai_conversation_messages(request, conversation_id):
    conversation = AIConversation.objects.filter(_ai_owner_filter(request), pk=conversation_id).first()
    if not conversation:
        return JsonResponse({'status': 'error', 'detail': 'Conversation not found.'}, status=404)
    messages_qs = list(conversation.messages.order_by('created_at').values('role', 'content', 'image_data', 'document_name', 'model_key'))
    return JsonResponse({'status': 'ok', 'title': conversation.title, 'messages': messages_qs})


def ai_conversation_delete(request, conversation_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    conversation = AIConversation.objects.filter(_ai_owner_filter(request), pk=conversation_id).first()
    if not conversation:
        return JsonResponse({'status': 'error', 'detail': 'Conversation not found.'}, status=404)
    conversation.delete()
    return JsonResponse({'status': 'ok'})


# ── AI GitHub mode: connect a repo, let the AI CRUD + push to it on prompt ──
# Staff-only end to end (every view here starts with the same guard) — this
# is real write/push access to a real repo, and /AI/ itself is a page any
# logged-in store customer (or, briefly, a guest) can reach. Each staff user
# has their own connection/token; nothing here is shared across accounts.

AI_GITHUB_RATE_LIMIT = 10
AI_GITHUB_MAX_FILE_CHARS = 60_000  # skip pulling absurdly large files into the prompt


def _github_guard(request):
    return request.user.is_authenticated and request.user.is_staff


def _github_forbidden():
    return JsonResponse({'status': 'error', 'detail': 'Forbidden.'}, status=403)


def github_status(request):
    if not _github_guard(request):
        return _github_forbidden()
    conn = GitHubConnection.objects.filter(user=request.user).first()
    if not conn:
        return JsonResponse({'status': 'ok', 'connected': False})
    return JsonResponse({
        'status': 'ok', 'connected': True, 'github_username': conn.github_username,
        'repo': conn.repo_full_name, 'branch': conn.default_branch,
    })


def _github_oauth_redirect_uri(request):
    return request.build_absolute_uri('/AI/api/github/oauth/callback/')


def github_oauth_start(request):
    # A redirect, not a JSON endpoint — the browser navigates here directly
    # (window.location.href), so an unauthorized visit bounces to the
    # storefront instead of showing a raw 403 JSON body.
    if not _github_guard(request):
        return redirect('estore')
    if not settings.GITHUB_OAUTH_CLIENT_ID:
        return redirect('/AI/?github_error=not_configured')
    state = secrets.token_urlsafe(24)
    request.session['github_oauth_state'] = state
    params = {
        'client_id': settings.GITHUB_OAUTH_CLIENT_ID,
        'redirect_uri': _github_oauth_redirect_uri(request),
        # 'repo' grants full read/write on both private and public repos —
        # the closest standard GitHub OAuth scope to "all permission on the
        # repo", without also requesting unrelated org/user-admin scopes.
        'scope': 'repo',
        'state': state,
    }
    return redirect('https://github.com/login/oauth/authorize?' + urlencode(params))


def github_oauth_callback(request):
    if not _github_guard(request):
        return redirect('estore')
    expected_state = request.session.pop('github_oauth_state', None)
    state = request.GET.get('state')
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return redirect('/AI/?github_error=state')
    code = request.GET.get('code')
    if not code:
        return redirect('/AI/?github_error=denied')
    try:
        token_resp = requests.post(
            'https://github.com/login/oauth/access_token',
            data={
                'client_id': settings.GITHUB_OAUTH_CLIENT_ID,
                'client_secret': settings.GITHUB_OAUTH_CLIENT_SECRET,
                'code': code,
                'redirect_uri': _github_oauth_redirect_uri(request),
            },
            headers={'Accept': 'application/json'},
            timeout=20,
        )
        token = token_resp.json().get('access_token')
        if not token:
            return redirect('/AI/?github_error=token')
        gh_user = github_ops.get_authenticated_user(token)
        repos = github_ops.list_user_repos(token)
    except Exception:
        logger.exception("GitHub OAuth callback failed")
        return redirect('/AI/?github_error=1')

    conn, _created = GitHubConnection.objects.update_or_create(
        user=request.user,
        defaults={'access_token': token, 'github_username': gh_user.get('login', '')},
    )
    if not conn.repo_full_name and repos:
        preferred = next((r for r in repos if 'edutrellis' in r['full_name'].lower()), repos[0])
        conn.repo_full_name = preferred['full_name']
        conn.default_branch = preferred['default_branch']
        conn.save(update_fields=['repo_full_name', 'default_branch'])
    return redirect('/AI/?github_connected=1')


def github_connect(request):
    if not _github_guard(request):
        return _github_forbidden()
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    payload = _parse_json_body(request)
    if not isinstance(payload, dict):
        return JsonResponse({'status': 'error', 'detail': 'Invalid request body.'}, status=400)
    token = str(payload.get('token', '')).strip()
    if not token:
        return JsonResponse({'status': 'error', 'detail': 'Token required.'}, status=400)
    try:
        gh_user = github_ops.get_authenticated_user(token)
        repos = github_ops.list_user_repos(token)
    except github_ops.GitHubAPIError as e:
        return JsonResponse({'status': 'error', 'detail': f"Couldn't connect: {e}"}, status=400)
    conn, _created = GitHubConnection.objects.update_or_create(
        user=request.user,
        defaults={'access_token': token, 'github_username': gh_user.get('login', '')},
    )
    if not conn.repo_full_name and repos:
        preferred = next((r for r in repos if 'edutrellis' in r['full_name'].lower()), repos[0])
        conn.repo_full_name = preferred['full_name']
        conn.default_branch = preferred['default_branch']
        conn.save(update_fields=['repo_full_name', 'default_branch'])
    return JsonResponse({
        'status': 'ok', 'github_username': conn.github_username, 'repos': repos,
        'repo': conn.repo_full_name, 'branch': conn.default_branch,
    })


def github_repos(request):
    if not _github_guard(request):
        return _github_forbidden()
    conn = GitHubConnection.objects.filter(user=request.user).first()
    if not conn:
        return JsonResponse({'status': 'error', 'detail': 'Not connected.'}, status=400)
    try:
        repos = github_ops.list_user_repos(conn.access_token)
    except github_ops.GitHubAPIError as e:
        return JsonResponse({'status': 'error', 'detail': str(e)}, status=400)
    return JsonResponse({'status': 'ok', 'repos': repos})


def github_set_repo(request):
    if not _github_guard(request):
        return _github_forbidden()
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    conn = GitHubConnection.objects.filter(user=request.user).first()
    if not conn:
        return JsonResponse({'status': 'error', 'detail': 'Not connected.'}, status=400)
    payload = _parse_json_body(request)
    repo = str(payload.get('repo', '')).strip() if isinstance(payload, dict) else ''
    if '/' not in repo:
        return JsonResponse({'status': 'error', 'detail': 'Invalid repo.'}, status=400)
    owner, _, name = repo.partition('/')
    try:
        info = github_ops.get_repo(conn.access_token, owner, name)
    except github_ops.GitHubAPIError as e:
        return JsonResponse({'status': 'error', 'detail': str(e)}, status=400)
    conn.repo_full_name = info['full_name']
    conn.default_branch = info['default_branch']
    conn.save(update_fields=['repo_full_name', 'default_branch'])
    return JsonResponse({'status': 'ok', 'repo': conn.repo_full_name, 'branch': conn.default_branch})


def github_disconnect(request):
    if not _github_guard(request):
        return _github_forbidden()
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    GitHubConnection.objects.filter(user=request.user).delete()
    return JsonResponse({'status': 'ok'})


def ai_github_send(request):
    if not _github_guard(request):
        return _github_forbidden()
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)

    cache_key = f'ai_github_rate:{request.user.pk}'
    count = cache.get(cache_key, 0)
    if count >= AI_GITHUB_RATE_LIMIT:
        return JsonResponse({'status': 'error', 'detail': 'Too many GitHub requests — please wait a bit.'}, status=429)
    cache.set(cache_key, count + 1, AI_CHAT_RATE_WINDOW)

    conn = GitHubConnection.objects.filter(user=request.user).first()
    if not conn or not conn.repo_full_name:
        return JsonResponse({'status': 'error', 'detail': 'Connect a GitHub repo first.'}, status=400)

    payload = _parse_json_body(request)
    if not isinstance(payload, dict):
        return JsonResponse({'status': 'error', 'detail': 'Invalid request body.'}, status=400)
    message = str(payload.get('message', ''))[:AI_CHAT_MAX_MESSAGE_CHARS].strip()
    if not message:
        return JsonResponse({'status': 'error', 'detail': 'No instruction provided.'}, status=400)

    owner, _, repo = conn.repo_full_name.partition('/')
    branch = conn.default_branch or 'main'

    owner_filter = _ai_owner_filter(request)
    conversation_id = payload.get('conversation_id')
    conversation = AIConversation.objects.filter(owner_filter, pk=conversation_id).first() if conversation_id else None
    if conversation is None:
        conversation = AIConversation.objects.create(user=request.user, title=message[:AI_CONVERSATION_TITLE_CHARS])
    AIMessage.objects.create(conversation=conversation, role=AIMessage.ROLE_USER, content=message)
    conversation.updated_at = timezone.now()
    conversation.save(update_fields=['updated_at'])

    def finish(reply_text):
        AIMessage.objects.create(conversation=conversation, role=AIMessage.ROLE_ASSISTANT, content=reply_text, model_key='github')
        return JsonResponse({'status': 'ok', 'reply': reply_text, 'conversation_id': conversation.id})

    try:
        file_paths = github_ops.get_tree(conn.access_token, owner, repo, branch)
    except github_ops.GitHubAPIError as e:
        return finish(f"Couldn't read the repository: {e}")

    wanted = ai_chat.github_select_files(message, file_paths)
    file_contents, file_shas = {}, {}
    for path in wanted:
        try:
            content, sha = github_ops.get_file(conn.access_token, owner, repo, path, branch)
        except github_ops.GitHubAPIError:
            continue
        if len(content) > AI_GITHUB_MAX_FILE_CHARS:
            content = content[:AI_GITHUB_MAX_FILE_CHARS] + '\n...[truncated]'
        file_contents[path] = content
        file_shas[path] = sha

    try:
        plan = ai_chat.github_plan_changes(message, file_paths, file_contents)
    except Exception as e:
        logger.exception("GitHub plan generation failed: %s", e)
        return finish("Something went wrong while planning the change — please try again or rephrase your request.")

    if not isinstance(plan, dict):
        return finish("The AI's response wasn't understood — please try rephrasing your request.")

    summary = str(plan.get('summary') or 'No changes were made.')
    commit_message = str(plan.get('commit_message') or message)[:200] or message[:200]
    operations = plan.get('operations') or []

    applied, skipped = [], []
    for op in operations[:20]:
        if not isinstance(op, dict):
            continue
        action = op.get('action')
        path = str(op.get('path', '')).strip()
        if not path or github_ops.is_path_blocked(path):
            skipped.append(f"{path or '(blank path)'} — blocked")
            continue
        try:
            if action in ('update', 'create'):
                content = op.get('content')
                if not isinstance(content, str):
                    skipped.append(f"{path} — no content given")
                    continue
                sha = file_shas.get(path)
                if sha is None and action == 'update':
                    try:
                        _, sha = github_ops.get_file(conn.access_token, owner, repo, path, branch)
                    except github_ops.GitHubAPIError:
                        sha = None
                github_ops.upsert_file(conn.access_token, owner, repo, path, content, commit_message, branch, sha=sha)
                applied.append(path)
            elif action == 'delete':
                sha = file_shas.get(path)
                if sha is None:
                    try:
                        _, sha = github_ops.get_file(conn.access_token, owner, repo, path, branch)
                    except github_ops.GitHubAPIError:
                        sha = None
                if sha is None:
                    skipped.append(f"{path} — not found")
                    continue
                github_ops.delete_file(conn.access_token, owner, repo, path, commit_message, branch, sha)
                applied.append(path)
            else:
                skipped.append(f"{path} — unknown action '{action}'")
        except github_ops.GitHubAPIError as e:
            skipped.append(f"{path} — {e}")

    lines = [summary]
    if applied:
        lines.append(f"\n**Pushed to {conn.repo_full_name}@{branch}:**")
        lines.extend(f"- {p}" for p in applied)
    if skipped:
        lines.append("\n**Skipped:**")
        lines.extend(f"- {s}" for s in skipped)
    if not applied and not skipped and not plan.get('summary'):
        lines.append("\nNo file changes were made.")
    return finish('\n'.join(lines))
