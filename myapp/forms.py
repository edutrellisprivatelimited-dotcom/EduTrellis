from django import forms


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
