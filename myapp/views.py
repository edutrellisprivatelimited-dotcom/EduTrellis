import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.core.mail import send_mail, BadHeaderError
from django.conf import settings
from myapp.forms import (
    ContactLeadForm, StoreSignupForm, StoreLoginForm, StoreContactForm,
    StoreProfileEditForm, StorePasswordChangeForm, CategoryForm,
)
from myapp.models import ContactLead, StoreProfile, Cart, CartItem, Category

logger = logging.getLogger(__name__)


def home(request):
    return render(request, "home.html", {"contact_form": ContactLeadForm()})


def home2(request):
    return render(request, "home2.html", {})


def estore(request):
    cart = _get_or_create_cart(request)
    boot = {'user': None, 'cart': _cart_payload(cart)}
    if request.user.is_authenticated:
        boot['user'] = _user_payload(request.user)
    categories = Category.objects.filter(is_active=True)
    return render(request, "estore.html", {
        "store_boot_json": json.dumps(boot),
        "categories": categories,
    })


def _user_payload(user):
    profile = getattr(user, 'store_profile', None)
    return {
        'name': user.first_name or user.username,
        'email': user.email,
        'phone': profile.phone if profile else '',
        'is_staff': user.is_staff,
        'avatar_url': profile.avatar.url if (profile and profile.avatar) else None,
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


def dashboard_logout(request):
    logout(request)
    return redirect('estore')
