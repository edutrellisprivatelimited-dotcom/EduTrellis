from django.shortcuts import render
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.http import require_POST

def home(request):
    return render(request, "home.html")

@require_POST
def contact_lead(request):
    name    = request.POST.get('name', '').strip()
    phone   = request.POST.get('phone', '').strip()
    email   = request.POST.get('email', '').strip()
    service = request.POST.get('service', '').strip()
    message = request.POST.get('message', '').strip()

    subject = f"🔥 New Lead from EduTrellis — {name}"
    body = f"""
New Lead Received from EduTrellis Website
==========================================
Name    : {name}
Phone   : {phone}
Email   : {email}
Service : {service}
Message : {message}
==========================================
    """.strip()

    try:
        send_mail(
            subject,
            body,
            settings.DEFAULT_FROM_EMAIL,
            [settings.LEAD_RECIPIENT_EMAIL],
            fail_silently=False,
        )
        return JsonResponse({'status': 'ok'})
    except Exception as ex:
        return JsonResponse({'status': 'error', 'detail': str(ex)}, status=500)
