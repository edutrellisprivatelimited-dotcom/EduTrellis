from django.db import models


class ContactLead(models.Model):
    """Persists every contact / lead-form submission.

    Saving to the database happens *before* the email is attempted, so
    no inquiry is ever lost even if SMTP is unavailable.
    """
    name       = models.CharField(max_length=120)
    phone      = models.CharField(max_length=20)
    email      = models.EmailField()
    service    = models.CharField(max_length=200, blank=True)
    message    = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name      = 'Contact Lead'
        verbose_name_plural = 'Contact Leads'

    def __str__(self):
        return f"{self.name} — {self.phone} ({self.created_at:%d %b %Y %H:%M})"
