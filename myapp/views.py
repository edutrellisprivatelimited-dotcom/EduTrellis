import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.shortcuts import render
from django.http import JsonResponse
from django.core.mail import send_mail, BadHeaderError
from django.conf import settings
from myapp.forms import ContactLeadForm, StoreSignupForm, StoreLoginForm, StoreContactForm
from myapp.models import ContactLead, StoreProfile, Cart, CartItem

logger = logging.getLogger(__name__)


def home(request):
    return render(request, "home.html", {"contact_form": ContactLeadForm()})


def home2(request):
    return render(request, "home2.html", {})


def estore(request):
    cart = _get_or_create_cart(request)
    boot = {'user': None, 'cart': _cart_payload(cart)}
    if request.user.is_authenticated:
        boot['user'] = {'name': request.user.first_name or request.user.username}
    return render(request, "estore.html", {"store_boot_json": json.dumps(boot)})


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


# ── E-Store: auth ────────────────────────────────────────────────────────

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

    cart = _get_or_create_cart(request)
    return JsonResponse({'status': 'ok', 'name': first_name or name, 'cart': _cart_payload(cart)})


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

    cart = _get_or_create_cart(request)
    name = auth_user.first_name or auth_user.username
    return JsonResponse({'status': 'ok', 'name': name, 'cart': _cart_payload(cart)})


def store_logout(request):
    logout(request)
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
        price = Decimal(str(payload.get('price', '0')))
    except InvalidOperation:
        price = Decimal('0')
    try:
        qty = max(1, int(payload.get('qty', 1)))
    except (TypeError, ValueError):
        qty = 1

    if not product_id or not name or price <= 0:
        return JsonResponse({'status': 'error', 'detail': 'Missing product details.'}, status=400)

    cart = _get_or_create_cart(request)
    item, created = CartItem.objects.get_or_create(
        cart=cart, product_id=product_id,
        defaults={'product_name': name, 'price': price, 'quantity': qty},
    )
    if not created:
        item.quantity += qty
        item.save(update_fields=['quantity'])

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
        service=f"Store — {form.cleaned_data.get('topic') or 'General enquiry'}",
        message=form.cleaned_data['message'],
    )
    return JsonResponse({'status': 'ok', 'message': "Thanks — your message is with our team."})


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
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [settings.LEAD_RECIPIENT_EMAIL],
            fail_silently=False,
        )
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
