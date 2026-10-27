from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import LookupValue, NumberSequence, TimeStampedModel
from core.scopes import owners

OWNER_FIELDS = owners("visits.visit")


class Visit(TimeStampedModel):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        CONFIRMED = "confirmed", "Confirmed"
        COMPLETED = "completed", "Completed"
        RESCHEDULED = "rescheduled", "Rescheduled"
        CANCELLED = "cancelled", "Cancelled"

    UPCOMING_STATUSES = (Status.SCHEDULED, Status.CONFIRMED, Status.RESCHEDULED)

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    code = models.CharField("Visit ID", max_length=20, unique=True, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="visits")
    contact = models.ForeignKey("customers.CustomerContact", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    contact_person = models.CharField(max_length=150, blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="visits",
                                    verbose_name="Assigned employee")
    opportunity = models.ForeignKey("sales.Opportunity", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="visits")
    lead = models.ForeignKey("leads.Lead", null=True, blank=True, on_delete=models.PROTECT, related_name="visits")
    site_name = models.CharField("Site / project name", max_length=200, blank=True)
    visit_date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    location = models.CharField(max_length=255)
    purpose = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                limit_choices_to={"category": "visit_purpose"}, verbose_name="Visit purpose")
    agenda = models.TextField(blank=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    # outcome (recorded when completing)
    meeting_notes = models.TextField(blank=True)
    customer_requirements = models.TextField(blank=True)
    agreed_actions = models.TextField(blank=True)
    key_developments = models.CharField(max_length=255, blank=True)
    potential_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    next_follow_up_date = models.DateField(null=True, blank=True)
    next_follow_up_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    cancel_reason = models.CharField(max_length=255, blank=True)
    previous_date = models.DateField(null=True, blank=True, help_text="Original date before rescheduling")

    class Meta:
        ordering = ["-visit_date", "-start_time"]
        indexes = [models.Index(fields=["assigned_to", "visit_date"])]

    def __str__(self):
        return f"{self.code} {self.customer.company_name}" if self.code else "New visit"

    def get_absolute_url(self):
        return reverse("visits:detail", args=[self.pk])

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({"end_time": "The end time must be after the start time."})

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next_value("visit")
        super().save(*args, **kwargs)

    @property
    def is_upcoming(self):
        return self.status in self.UPCOMING_STATUSES and self.visit_date >= timezone.localdate()

    @property
    def is_missed(self):
        """Planned but its date has passed without being completed or cancelled."""
        return self.status in self.UPCOMING_STATUSES and self.visit_date < timezone.localdate()

    @property
    def can_complete(self):
        return self.status in self.UPCOMING_STATUSES

    def tone(self):
        if self.is_missed:
            return "bad"
        return {"completed": "good", "cancelled": "neutral", "confirmed": "info", "rescheduled": "warn"}.get(
            self.status, "info")
