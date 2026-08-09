import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.core.mail import send_mail, BadHeaderError
from django.conf import settings
from myapp.forms import (
    ContactLeadForm, StoreSignupForm, StoreLoginForm, StoreContactForm,
    StoreProfileEditForm, StorePasswordChangeForm, CategoryForm, OrderStatusForm,
    ProductForm, ProductImageFormSet, ProductColorFormSet,
    AboutUsContentForm, PolicyPageForm, PaymentSettingsForm, DropboxSettingsForm,
)
from myapp.models import (
    ContactLead, StoreProfile, Cart, CartItem, Category, Order, OrderItem,
    Product, ProductImage, ProductColor, AboutUsContent, PolicyPage, PaymentSettings, Payment,
    DropboxSettings,
)
from myapp import dropbox_backup

logger = logging.getLogger(__name__)

try:
    import razorpay
except ImportError:  # pragma: no cover - optional dependency until configured
    razorpay = None

# The frontend reads these from store_boot_json (BOOT.shipping) instead of
# hardcoding its own copy, so this is the single source of truth.
FREE_SHIP_OVER = Decimal('299')
SHIP_FEE = Decimal('79')


def home(request):
    return render(request, "home.html", {"contact_form": ContactLeadForm()})


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
    return render(request, "estore.html", context)


def _estore_context(request):
    cart = _get_or_create_cart(request)
    payment_settings = PaymentSettings.get_solo()
    boot = {
        'user': None,
        'cart': _cart_payload(cart),
        'shipping': {'free_over': float(FREE_SHIP_OVER), 'fee': float(SHIP_FEE)},
        'payments': {
            'cod_enabled': payment_settings.cod_enabled,
            'razorpay_enabled': payment_settings.razorpay_ready,
            'razorpay_key_id': payment_settings.razorpay_key_id if payment_settings.razorpay_ready else '',
        },
    }
    if request.user.is_authenticated:
        boot['user'] = _user_payload(request.user)
    categories = Category.objects.filter(is_active=True)
    products = Product.objects.filter(is_active=True).select_related('category').prefetch_related('images', 'colors')
    return {
        "store_boot_json": json.dumps(boot),
        "products_json": json.dumps([_product_payload(p) for p in products]),
        "categories": categories,
        "about": AboutUsContent.get_solo(),
        "initial_product_slug": None,
        "meta_title": None,
        "meta_description": None,
    }


def _product_payload(p):
    gallery = []
    if p.image:
        gallery.append({'type': 'image', 'url': p.image.url})
    for img in p.images.all():
        gallery.append({'type': 'image', 'url': img.image.url})
    if p.video:
        gallery.append({'type': 'video', 'url': p.video.url})

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
        'rating': float(p.rating),
        'reviews': p.reviews_count,
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
    return {
        'id': order.pk,
        'status': order.status,
        'status_display': order.get_status_display(),
        'subtotal': float(order.subtotal),
        'wallet_discount': float(order.wallet_discount),
        'shipping_fee': float(order.shipping_fee),
        'total': float(order.total),
        'created_at': order.created_at.strftime('%d %b %Y, %I:%M %p'),
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
    return JsonResponse({'status': 'ok', 'user': _user_payload(auth_user or user), 'cart': _cart_payload(cart)})


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


def _razorpay_client():
    settings_obj = PaymentSettings.get_solo()
    if razorpay is None or not settings_obj.razorpay_ready:
        return None, settings_obj
    return razorpay.Client(auth=(settings_obj.razorpay_key_id, settings_obj.razorpay_key_secret)), settings_obj


def store_checkout(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'Invalid request method.'}, status=405)
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in to check out.'}, status=401)

    cart = _get_or_create_cart(request)
    items = list(cart.items.all())
    if not items:
        return JsonResponse({'status': 'error', 'detail': 'Your cart is empty.'}, status=400)

    payload = _parse_json_body(request)
    use_wallet = bool(payload.get('use_wallet'))
    payment_method = payload.get('payment_method') or Payment.METHOD_COD
    if payment_method not in (Payment.METHOD_COD, Payment.METHOD_RAZORPAY):
        payment_method = Payment.METHOD_COD

    profile, _ = StoreProfile.objects.get_or_create(user=request.user)

    subtotal = sum((i.subtotal for i in items), Decimal('0'))
    wallet_discount = min(profile.wallet_balance, subtotal) if use_wallet else Decimal('0')
    shipping_fee = Decimal('0') if subtotal == 0 or subtotal >= FREE_SHIP_OVER else SHIP_FEE
    total = max(Decimal('0'), subtotal + shipping_fee - wallet_discount)

    razorpay_client, payment_settings = (None, None)
    if payment_method == Payment.METHOD_RAZORPAY:
        razorpay_client, payment_settings = _razorpay_client()
        if razorpay_client is None:
            payment_method = Payment.METHOD_COD  # gateway not configured — fall back silently

    order = Order.objects.create(
        user=request.user, subtotal=subtotal, wallet_discount=wallet_discount,
        shipping_fee=shipping_fee, total=total,
    )
    OrderItem.objects.bulk_create([
        OrderItem(order=order, product_id=i.product_id, product_name=i.product_name,
                  price=i.price, quantity=i.quantity)
        for i in items
    ])

    if wallet_discount > 0:
        profile.wallet_balance -= wallet_discount
        profile.save(update_fields=['wallet_balance'])

    cart.items.all().delete()

    razorpay_payload = None
    if payment_method == Payment.METHOD_RAZORPAY and total > 0:
        try:
            rp_order = razorpay_client.order.create({
                'amount': int(total * 100),
                'currency': 'INR',
                'receipt': f'order_{order.pk}',
                'payment_capture': 1,
            })
            payment = Payment.objects.create(
                order=order, method=Payment.METHOD_RAZORPAY, status=Payment.STATUS_PENDING,
                amount=total, razorpay_order_id=rp_order['id'],
            )
            razorpay_payload = {
                'key_id': payment_settings.razorpay_key_id,
                'razorpay_order_id': rp_order['id'],
                'amount': int(total * 100),
                'currency': 'INR',
                'payment_pk': payment.pk,
                'name': 'EduTrellis Store',
                'description': f'Order #{order.pk}',
                'prefill': {
                    'name': request.user.get_full_name() or request.user.username,
                    'email': request.user.email,
                    'contact': profile.phone,
                },
            }
        except Exception as e:
            logger.exception("Razorpay order creation failed for Order #%s: %s", order.pk, e)
            Payment.objects.create(order=order, method=Payment.METHOD_COD, status=Payment.STATUS_COD_PENDING, amount=total)
            payment_method = Payment.METHOD_COD
    else:
        pay_status = Payment.STATUS_PAID if total <= 0 else Payment.STATUS_COD_PENDING
        Payment.objects.create(order=order, method=Payment.METHOD_COD, status=pay_status, amount=total)
        payment_method = Payment.METHOD_COD

    return JsonResponse({
        'status': 'ok',
        'order': _order_payload(order),
        'cart': _cart_payload(cart),
        'user': _user_payload(request.user),
        'payment_method': payment_method,
        'razorpay': razorpay_payload,
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
    return JsonResponse({'status': 'ok'})


def store_orders_list(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'detail': 'You need to be logged in.'}, status=401)
    orders = Order.objects.filter(user=request.user).prefetch_related('items').order_by('-created_at')
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
        service=f"Store — {form.cleaned_data.get('topic') or 'General enquiry'}",
        message=form.cleaned_data['message'],
    )
    return JsonResponse({'status': 'ok', 'message': "Thanks — your message is with our team."})


def policy_page(request, key):
    policy = get_object_or_404(PolicyPage, key=key)
    return render(request, 'policy_page.html', {'policy': policy})


def custom_404(request, exception=None):
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


# ── Custom store admin dashboard (staff-only, replaces linking to /admin/) ──

def _dashboard_guard(request):
    """Anonymous or non-staff visitors are bounced back to the storefront,
    where they can log in through the existing auth modal."""
    return request.user.is_authenticated and request.user.is_staff


def dashboard_home(request):
    if not _dashboard_guard(request):
        return redirect('estore')

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


def dashboard_signups(request):
    if not _dashboard_guard(request):
        return redirect('estore')

    q = request.GET.get('q', '').strip()
    users = User.objects.select_related('store_profile').order_by('-date_joined')
    if q:
        users = users.filter(
            Q(username__icontains=q) | Q(email__icontains=q) |
            Q(first_name__icontains=q) | Q(last_name__icontains=q) |
            Q(store_profile__phone__icontains=q)
        )
    return render(request, 'dashboard/signups.html', {'active': 'signups', 'users': users, 'q': q})


def dashboard_contacts(request):
    if not _dashboard_guard(request):
        return redirect('estore')

    q = request.GET.get('q', '').strip()
    leads = ContactLead.objects.order_by('-created_at')
    if q:
        leads = leads.filter(
            Q(name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q) |
            Q(service__icontains=q) | Q(message__icontains=q)
        )
    return render(request, 'dashboard/contacts.html', {'active': 'contacts', 'leads': leads, 'q': q})


def dashboard_contact_delete(request, pk):
    if not _dashboard_guard(request):
        return redirect('estore')
    if request.method == 'POST':
        get_object_or_404(ContactLead, pk=pk).delete()
    return redirect('dashboard_contacts')


def dashboard_categories(request):
    if not _dashboard_guard(request):
        return redirect('estore')

    q = request.GET.get('q', '').strip()
    categories = Category.objects.all()
    if q:
        categories = categories.filter(Q(name__icontains=q) | Q(slug__icontains=q))
    return render(request, 'dashboard/categories.html', {'active': 'categories', 'categories': categories, 'q': q})


def dashboard_category_add(request):
    if not _dashboard_guard(request):
        return redirect('estore')

    form = CategoryForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('dashboard_categories')
    return render(request, 'dashboard/category_form.html', {'active': 'categories', 'form': form, 'category': None})


def dashboard_category_edit(request, pk):
    if not _dashboard_guard(request):
        return redirect('estore')

    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, request.FILES or None, instance=category)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('dashboard_categories')
    return render(request, 'dashboard/category_form.html', {'active': 'categories', 'form': form, 'category': category})


def dashboard_category_delete(request, pk):
    if not _dashboard_guard(request):
        return redirect('estore')
    if request.method == 'POST':
        get_object_or_404(Category, pk=pk).delete()
    return redirect('dashboard_categories')


def dashboard_orders(request):
    if not _dashboard_guard(request):
        return redirect('estore')

    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    orders = Order.objects.select_related('user').prefetch_related('items').order_by('-created_at')
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


def dashboard_order_status_update(request, pk):
    if not _dashboard_guard(request):
        return redirect('estore')
    order = get_object_or_404(Order, pk=pk)
    if request.method == 'POST':
        form = OrderStatusForm(request.POST, instance=order)
        if form.is_valid():
            form.save()
            order.maybe_credit_wallet()
    return redirect('dashboard_orders')


def dashboard_products(request):
    if not _dashboard_guard(request):
        return redirect('estore')

    q = request.GET.get('q', '').strip()
    products = Product.objects.select_related('category').all()
    if q:
        products = products.filter(
            Q(name__icontains=q) | Q(brand__icontains=q) | Q(slug__icontains=q) | Q(tags__icontains=q)
        )
    return render(request, 'dashboard/products.html', {'active': 'products', 'products': products, 'q': q})


def dashboard_product_add(request):
    if not _dashboard_guard(request):
        return redirect('estore')

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


def dashboard_product_edit(request, pk):
    if not _dashboard_guard(request):
        return redirect('estore')

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


def dashboard_product_delete(request, pk):
    if not _dashboard_guard(request):
        return redirect('estore')
    if request.method == 'POST':
        get_object_or_404(Product, pk=pk).delete()
    return redirect('dashboard_products')


def dashboard_about(request):
    if not _dashboard_guard(request):
        return redirect('estore')

    about = AboutUsContent.get_solo()
    form = AboutUsContentForm(request.POST or None, request.FILES or None, instance=about)
    saved = False
    if request.method == 'POST' and form.is_valid():
        form.save()
        saved = True
        form = AboutUsContentForm(instance=about)
    return render(request, 'dashboard/about_form.html', {'active': 'about', 'form': form, 'about': about, 'saved': saved})


def dashboard_policies(request):
    if not _dashboard_guard(request):
        return redirect('estore')

    policies = PolicyPage.objects.all()
    return render(request, 'dashboard/policies.html', {'active': 'policies', 'policies': policies})


def dashboard_policy_edit(request, pk):
    if not _dashboard_guard(request):
        return redirect('estore')

    policy = get_object_or_404(PolicyPage, pk=pk)
    form = PolicyPageForm(request.POST or None, instance=policy)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('dashboard_policies')
    return render(request, 'dashboard/policy_form.html', {'active': 'policies', 'form': form, 'policy': policy})


def dashboard_payment_settings(request):
    if not _dashboard_guard(request):
        return redirect('estore')

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


def dashboard_payments(request):
    if not _dashboard_guard(request):
        return redirect('estore')

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


def dashboard_backup(request):
    if not _dashboard_guard(request):
        return redirect('estore')

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


def dashboard_backup_settings(request):
    if not _dashboard_guard(request):
        return redirect('estore')

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


def dashboard_backup_run(request):
    if not _dashboard_guard(request):
        return redirect('estore')
    if request.method == 'POST':
        settings_obj = DropboxSettings.get_solo()
        try:
            filename = dropbox_backup.create_backup(settings_obj)
            messages.success(request, f'Backup saved to Dropbox as "{filename}".')
        except dropbox_backup.BackupError as exc:
            messages.error(request, str(exc))
    return redirect('dashboard_backup')


def dashboard_backup_restore(request):
    if not _dashboard_guard(request):
        return redirect('estore')
    if request.method == 'POST':
        settings_obj = DropboxSettings.get_solo()
        filename = request.POST.get('filename', '').strip()
        if not filename:
            messages.error(request, 'Choose a backup to restore first.')
        else:
            try:
                dropbox_backup.restore_backup(settings_obj, filename)
                messages.success(request, f'Database restored from "{filename}". Restart the app if you notice anything odd.')
            except dropbox_backup.BackupError as exc:
                messages.error(request, str(exc))
    return redirect('dashboard_backup')


def dashboard_logout(request):
    logout(request)
    return redirect('estore')
