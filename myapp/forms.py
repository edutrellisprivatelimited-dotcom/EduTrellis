from django import forms
from django.contrib.auth.models import User


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
