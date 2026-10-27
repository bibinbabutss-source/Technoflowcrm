"""
In-app notifications and optional email.

Email is sent only when (1) the Administrator turned on 'Send notification emails' in Settings,
(2) the server has SMTP settings (EMAIL_HOST), and (3) the user ticked email for that category.
Without SMTP settings, emails are written to the server log instead of being sent.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

from core.models import CompanyProfile

from .models import CATEGORY_LABELS, Notification, NotificationPreference

log = logging.getLogger("technoflow")


def _prefs(user, category):
    pref = NotificationPreference.objects.filter(user=user, category=category).first()
    return (pref.in_app, pref.email) if pref else (True, False)


def notify(users, category, title, message="", url="", *, dedupe_key=""):
    if category not in CATEGORY_LABELS:
        raise ValueError(f"Unknown notification category {category}")
    company = CompanyProfile.get()
    created = []
    seen = set()
    for user in users:
        if user is None or not user.is_active or user.pk in seen:
            continue
        seen.add(user.pk)
        if dedupe_key and Notification.objects.filter(user=user, dedupe_key=dedupe_key).exists():
            continue
        in_app, by_email = _prefs(user, category)
        n = Notification.objects.create(user=user, category=category, title=title[:200], message=message[:500],
                                        url=url[:300], dedupe_key=dedupe_key[:120], is_read=not in_app)
        if by_email and company.email_notifications_enabled and user.email:
            try:
                send_mail(subject=f"[{company.company_name} CRM] {title}"[:200],
                          message=f"{message}\n\n{_absolute(url)}", from_email=settings.DEFAULT_FROM_EMAIL,
                          recipient_list=[user.email], fail_silently=False)
                Notification.objects.filter(pk=n.pk).update(emailed=True)
            except Exception:  # never let an email problem break the business action
                log.exception("Notification email to %s failed", user.pk)
        created.append(n)
    return created


def _absolute(url):
    base = getattr(settings, "SITE_URL", "")
    return f"{base}{url}" if url and base else url


def unread_count(user):
    return Notification.objects.filter(user=user, is_read=False).count()
