from django.shortcuts import render
from django.http import JsonResponse
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt

def home(request):
    return render(request, "home.html")

@csrf_exempt
def contact_lead(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'detail': 'POST only'}, status=405)

    name    = request.POST.get('name', '').strip()
    phone   = request.POST.get('phone', '').strip()
    email   = request.POST.get('email', '').strip()
    service = request.POST.get('service', '').strip()
    message = request.POST.get('message', '').strip()

    subject = f"New Lead from EduTrellis - {name}"
    body = f"""New Lead Received
==========================================
Name    : {name}
Phone   : {phone}
Email   : {email}
Service : {service}
Message : {message}
=========================================="""

    try:
        send_mail(
            subject,
            body,
            settings.EMAIL_HOST_USER,
            ['webdevrnt@gmail.com'],
            fail_silently=False,
        )
        return JsonResponse({'status': 'ok'})
    except Exception as ex:
        return JsonResponse({'status': 'error', 'detail': str(ex)}, status=500)
