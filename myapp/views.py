from django.shortcuts import render
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from myapp.forms import ContactLeadForm


def home(request):
    return render(request, "home.html", {"contact_form": ContactLeadForm()})


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

    name = form.cleaned_data['name']
    phone = form.cleaned_data['phone']
    email = form.cleaned_data['email']
    service = form.cleaned_data.get('service', '')
    message = form.cleaned_data.get('message', '')

    subject = f"New Lead from EduTrellis - {name}"
    body = f"""New Lead Received from EduTrellis Website
==========================================
Name    : {name}
Phone   : {phone}
Email   : {email}
Service : {service or 'Not selected'}
Message : {message or 'No message provided'}
=========================================="""

    try:
        send_mail(
            subject,
            body,
            settings.EMAIL_HOST_USER,
            ['webdevrnt@gmail.com'],
            fail_silently=False,
        )
        return JsonResponse({'status': 'ok', 'message': 'Message sent successfully.'})
    except Exception:
        return JsonResponse(
            {
                'status': 'error',
                'detail': 'Unable to send your message right now. Please try again in a moment.'
            },
            status=500,
        )
