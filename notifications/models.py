from django.conf import settings
from django.db import models
from django.utils import timezone

CATEGORIES = [
    ("lead_assigned", "A lead is assigned to me"),
    ("visit_assigned", "A visit is scheduled for me"),
    ("visit_upcoming", "Reminder of my upcoming visits"),
    ("followup_overdue", "My follow-ups are overdue"),
    ("task_assigned", "A task is assigned to me"),
    ("task_comment", "Someone comments on my task"),
    ("task_due", "My tasks are due or overdue"),
    ("quotation_pending", "Quotations awaiting my approval"),
    ("quotation_decision", "My quotations are approved or rejected"),
    ("quotation_expiring", "My quotations are about to expire"),
    ("order_to_confirm", "Orders awaiting my confirmation"),
    ("order_confirmed", "Orders are confirmed"),
    ("invoice_overdue", "Invoices are overdue"),
]
CATEGORY_LABELS = dict(CATEGORIES)


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    category = models.CharField(max_length=30, choices=CATEGORIES)
    title = models.CharField(max_length=200)
    message = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    emailed = models.BooleanField(default=False)
    dedupe_key = models.CharField(max_length=120, blank=True, db_index=True,
                                  help_text="Prevents the same reminder being created twice")

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read"])]

    def __str__(self):
        return self.title


class NotificationPreference(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_prefs")
    category = models.CharField(max_length=30, choices=CATEGORIES)
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "category"], name="uniq_pref_user_category")]
