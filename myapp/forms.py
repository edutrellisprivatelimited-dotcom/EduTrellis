from django import forms
from django.contrib.auth.models import User
from django.utils.text import slugify

from myapp.models import (
    Category, Order, Product, ProductImage, ProductColor,
    AboutUsContent, PolicyPage, PaymentSettings, DropboxSettings, EmailSettings,
)


class ContactLeadForm(forms.Form):
    name = forms.CharField(
        max_length=120,
        required=True,
        error_messages={'required': 'Full name is required.'}
    )
    phone = forms.CharField(
        max_length=20,
        required=True,
        error_messages={'required': 'Phone number is required.'}
    )
    email = forms.EmailField(
        required=True,
        error_messages={
            'required': 'Email address is required.',
            'invalid': 'Enter a valid email address.'
        }
    )
    service = forms.CharField(max_length=200, required=False)
    message = forms.CharField(required=False, widget=forms.Textarea)

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise forms.ValidationError('Full name must be at least 2 characters long.')
        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10:
            raise forms.ValidationError('Enter a valid phone number.')
        return phone

    def clean_message(self):
        return self.cleaned_data.get('message', '').strip()


class StoreSignupForm(forms.Form):
    name     = forms.CharField(max_length=120, required=True, error_messages={'required': 'Enter your full name.'})
    phone    = forms.CharField(max_length=20, required=True, error_messages={'required': 'Enter your phone number.'})
    email    = forms.EmailField(required=True, error_messages={'required': 'Enter your email address.', 'invalid': 'Enter a valid email address.'})
    password = forms.CharField(min_length=6, required=True, error_messages={'required': 'Create a password.', 'min_length': 'Password must be at least 6 characters.'})

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise forms.ValidationError('Enter your full name.')
        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10:
            raise forms.ValidationError('Enter a valid phone number.')
        return phone

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists — try logging in.')
        return email


class StoreLoginForm(forms.Form):
    identifier = forms.CharField(max_length=150, required=True, error_messages={'required': 'Enter your email or phone number.'})
    password   = forms.CharField(required=True, error_messages={'required': 'Enter your password.'})


class StoreProfileEditForm(forms.Form):
    name   = forms.CharField(max_length=120, required=True, error_messages={'required': 'Enter your full name.'})
    phone  = forms.CharField(max_length=20, required=True, error_messages={'required': 'Enter your phone number.'})
    avatar = forms.ImageField(required=False)

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise forms.ValidationError('Enter your full name.')
        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10:
            raise forms.ValidationError('Enter a valid phone number.')
        return phone


class StorePasswordChangeForm(forms.Form):
    current_password = forms.CharField(required=True, error_messages={'required': 'Enter your current password.'})
    new_password      = forms.CharField(min_length=6, required=True, error_messages={'required': 'Enter a new password.', 'min_length': 'New password must be at least 6 characters.'})


class StoreContactForm(forms.Form):
    name    = forms.CharField(max_length=120, required=True, error_messages={'required': 'Enter your full name.'})
    phone   = forms.CharField(max_length=20, required=True, error_messages={'required': 'Enter your phone number.'})
    email   = forms.EmailField(required=True, error_messages={'required': 'Enter your email address.', 'invalid': 'Enter a valid email address.'})
    topic   = forms.CharField(max_length=120, required=False)
    message = forms.CharField(required=True, error_messages={'required': 'Tell us a little more.'})

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise forms.ValidationError('Enter your full name.')
        return name

    def clean_phone(self):
        phone = self.cleaned_data['phone'].strip()
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10:
            raise forms.ValidationError('Enter a valid phone number.')
        return phone

    def clean_message(self):
        message = self.cleaned_data['message'].strip()
        if len(message) < 10:
            raise forms.ValidationError('Tell us a little more (10+ characters).')
        return message


class CheckoutAddressForm(forms.Form):
    recipient_name  = forms.CharField(max_length=120, required=True, error_messages={'required': "Enter the recipient's name."})
    recipient_phone = forms.CharField(max_length=20, required=True, error_messages={'required': 'Enter a delivery phone number.'})
    address_line1   = forms.CharField(max_length=200, required=True, error_messages={'required': 'Enter your address.'})
    address_line2   = forms.CharField(max_length=200, required=False)
    city            = forms.CharField(max_length=100, required=True, error_messages={'required': 'Enter your city.'})
    state           = forms.CharField(max_length=100, required=True, error_messages={'required': 'Enter your state.'})
    pincode         = forms.CharField(max_length=10, required=True, error_messages={'required': 'Enter your PIN code.'})

    def clean_recipient_name(self):
        name = self.cleaned_data['recipient_name'].strip()
        if len(name) < 2:
            raise forms.ValidationError("Enter the recipient's name.")
        return name

    def clean_recipient_phone(self):
        phone = self.cleaned_data['recipient_phone'].strip()
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if len(digits) < 10:
            raise forms.ValidationError('Enter a valid phone number.')
        return phone

    def clean_pincode(self):
        pincode = self.cleaned_data['pincode'].strip()
        if not pincode.isdigit() or len(pincode) != 6:
            raise forms.ValidationError('Enter a valid 6-digit PIN code.')
        return pincode


class ReviewForm(forms.Form):
    rating  = forms.IntegerField(min_value=1, max_value=5, error_messages={'required': 'Pick a star rating.'})
    comment = forms.CharField(max_length=2000, required=False, widget=forms.Textarea)

    def clean_comment(self):
        return self.cleaned_data.get('comment', '').strip()


class CategoryForm(forms.ModelForm):
    slug = forms.CharField(
        max_length=80, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'auto-generated if left blank'}),
    )

    class Meta:
        model = Category
        fields = ['name', 'slug', 'description', 'image', 'order', 'is_active']

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise forms.ValidationError('Category name must be at least 2 characters long.')
        return name

    def clean_slug(self):
        slug = slugify(self.cleaned_data.get('slug') or self.cleaned_data.get('name', ''))
        if not slug:
            raise forms.ValidationError('Could not derive a slug — enter one manually.')
        qs = Category.objects.filter(slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('A category with this slug already exists.')
        return slug


class OrderStatusForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['status']


class ProductForm(forms.ModelForm):
    slug = forms.CharField(
        max_length=40, required=False,
        widget=forms.TextInput(attrs={'placeholder': 'auto-generated if left blank'}),
    )

    class Meta:
        model = Product
        # 'name' must precede 'slug' — clean_slug() reads self.cleaned_data['name'],
        # and Django's _clean_fields() populates cleaned_data in this field order.
        fields = [
            'category', 'brand', 'name', 'slug', 'short_description', 'description', 'specs',
            'price', 'mrp', 'image', 'video', 'icon', 'gradient', 'flag', 'stock_status', 'tags',
            'rating', 'reviews_count', 'order', 'is_active',
        ]
        widgets = {
            'short_description': forms.TextInput(),
            'description': forms.Textarea(attrs={'rows': 4}),
            'specs': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Battery: 40 hours\nConnectivity: Bluetooth 5.3'}),
        }

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if len(name) < 2:
            raise forms.ValidationError('Product name must be at least 2 characters long.')
        return name

    def clean_slug(self):
        slug = slugify(self.cleaned_data.get('slug') or self.cleaned_data.get('name', ''))
        if not slug:
            raise forms.ValidationError('Could not derive a slug — enter one manually.')
        qs = Product.objects.filter(slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('A product with this slug already exists.')
        return slug

    def clean(self):
        cleaned = super().clean()
        price, mrp = cleaned.get('price'), cleaned.get('mrp')
        if price is not None and mrp is not None and price > mrp:
            raise forms.ValidationError('Price cannot be higher than MRP.')
        return cleaned


ProductImageFormSet = forms.inlineformset_factory(
    Product, ProductImage,
    fields=['image', 'order'],
    extra=8, max_num=10, validate_max=True, can_delete=True,
)

ProductColorFormSet = forms.inlineformset_factory(
    Product, ProductColor,
    fields=['name', 'hex_code', 'image', 'order'],
    extra=6, max_num=14, validate_max=True, can_delete=True,
    widgets={
        'name': forms.TextInput(attrs={'placeholder': 'Colour name, e.g. Midnight Black'}),
        'hex_code': forms.TextInput(attrs={'type': 'color'}),
        'order': forms.NumberInput(attrs={'placeholder': 'Order'}),
    },
)


class AboutUsContentForm(forms.ModelForm):
    class Meta:
        model = AboutUsContent
        fields = [
            'photo', 'badge_title', 'badge_subtitle',
            'founder_name', 'founder_title', 'founder_email', 'founder_linkedin', 'founder_photo',
            'stat1_value', 'stat1_label', 'stat2_value', 'stat2_label',
            'stat3_value', 'stat3_label', 'stat4_value', 'stat4_label',
            'heading', 'paragraph1', 'paragraph2', 'list_heading', 'bullet_points',
        ]
        widgets = {
            'paragraph1': forms.Textarea(attrs={'rows': 4}),
            'paragraph2': forms.Textarea(attrs={'rows': 4}),
            'bullet_points': forms.Textarea(attrs={'rows': 5, 'placeholder': 'One point per line'}),
        }


class PolicyPageForm(forms.ModelForm):
    class Meta:
        model = PolicyPage
        fields = ['title', 'content']
        widgets = {
            'content': forms.Textarea(attrs={'rows': 16}),
        }


class PaymentSettingsForm(forms.ModelForm):
    razorpay_key_secret = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=True, attrs={'autocomplete': 'new-password'}),
        help_text='Found in Razorpay Dashboard → Settings → API Keys. Kept secret — never exposed to the storefront.',
    )

    class Meta:
        model = PaymentSettings
        fields = ['razorpay_key_id', 'razorpay_key_secret', 'is_razorpay_enabled', 'is_test_mode', 'cod_enabled']


class DropboxSettingsForm(forms.ModelForm):
    app_secret = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=True, attrs={'autocomplete': 'new-password'}),
        help_text='From your Dropbox App Console — kept secret, never exposed to the storefront.',
    )
    refresh_token = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=True, attrs={'autocomplete': 'new-password'}),
        help_text="A long-lived OAuth2 refresh token for your Dropbox app (doesn't expire like a short-lived access token).",
    )

    class Meta:
        model = DropboxSettings
        fields = ['app_key', 'app_secret', 'refresh_token']


class EmailSettingsForm(forms.ModelForm):
    smtp_password = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=True, attrs={'autocomplete': 'new-password'}),
        help_text='For Gmail, use a 16-character App Password, not your normal login password. Kept secret — never exposed to the storefront.',
    )

    class Meta:
        model = EmailSettings
        fields = [
            'is_enabled', 'smtp_host', 'smtp_port', 'smtp_username', 'smtp_password',
            'use_tls', 'use_ssl', 'from_email', 'notify_email',
        ]
