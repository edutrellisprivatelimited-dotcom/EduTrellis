from django.core.mail import get_connection, send_mail

from myapp.models import EmailSettings


def send_store_email(subject, body, to):
    """Sends an app email using the dashboard-configured SMTP settings.
    If SMTP hasn't been configured (or is turned off) in the dashboard,
    no email is sent. `to` is a list of recipient addresses."""
    email_settings = EmailSettings.get_solo()
    if not email_settings.ready:
        return

    connection = get_connection(
        host=email_settings.smtp_host,
        port=email_settings.smtp_port,
        username=email_settings.smtp_username,
        password=email_settings.smtp_password,
        use_tls=email_settings.use_tls,
        use_ssl=email_settings.use_ssl,
        timeout=10,
    )
    from_email = email_settings.from_email or email_settings.smtp_username

    send_mail(subject, body, from_email, to, connection=connection, fail_silently=False)


def get_notify_email():
    """Where store notifications (new orders, contact leads) should go."""
    email_settings = EmailSettings.get_solo()
    return email_settings.notify_email or email_settings.smtp_username
