from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.scopes import owners
from core.models import LookupValue, NumberSequence, TimeStampedModel

OWNER_FIELDS = owners("leads.lead")


class LeadStage(TimeStampedModel):
    """Lead pipeline stages, editable in Settings. 'Won' and 'Lost' are fixed system stages."""

    name = models.CharField(max_length=60, unique=True)
    order = models.PositiveSmallIntegerField(default=0)
    is_won = models.BooleanField(default=False, editable=False)
    is_lost = models.BooleanField(default=False, editable=False)
    is_qualified = models.BooleanField(
        default=False, help_text="Leads at or after this stage count as qualified in reports.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.name

    @property
    def is_closed(self):
        return self.is_won or self.is_lost

    @classmethod
    def won(cls):
        return cls.objects.get(is_won=True)

    @classmethod
    def lost(cls):
        return cls.objects.get(is_lost=True)

    @classmethod
    def first_open(cls):
        return cls.objects.filter(is_active=True, is_won=False, is_lost=False).first()


class Lead(TimeStampedModel):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    code = models.CharField("Lead ID", max_length=20, unique=True, editable=False)
    title = models.CharField("Lead title", max_length=200)
    company_name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=150, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    city = models.CharField("Emirate / city", max_length=100, blank=True)
    source = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                               limit_choices_to={"category": "lead_source"}, verbose_name="Lead source")
    interest = models.CharField("Service / product interest", max_length=255, blank=True)
    estimated_value = models.DecimalField("Estimated opportunity value", max_digits=14, decimal_places=2,
                                          default=0, validators=[MinValueValidator(0)])
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    assigned_engineer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="leads_as_engineer")
    assigned_coordinator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="leads_as_coordinator")
    stage = models.ForeignKey(LeadStage, on_delete=models.PROTECT, related_name="leads")
    last_contact_date = models.DateField(null=True, blank=True)
    next_follow_up = models.DateField("Next follow-up date", null=True, blank=True, db_index=True)
    qualification_notes = models.TextField(blank=True)
    lost_reason = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                    limit_choices_to={"category": "lost_reason"})
    lost_notes = models.CharField(max_length=255, blank=True)
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="leads")
    converted_at = models.DateTimeField(null=True, blank=True)
    converted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    stage_changed_at = models.DateTimeField(default=timezone.now)
    is_archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} {self.title}" if self.code else self.title

    def get_absolute_url(self):
        return reverse("leads:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next_value("lead")
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_converted(self):
        return self.customer_id is not None

    @property
    def is_follow_up_overdue(self):
        return bool(self.next_follow_up and self.next_follow_up < timezone.localdate() and not self.stage.is_closed)

    # kanban card helpers
    @property
    def kanban_title(self):
        return self.title

    @property
    def kanban_subtitle(self):
        return f"{self.code} · {self.company_name}"

    @property
    def kanban_value(self):
        return self.estimated_value

    @property
    def kanban_owner(self):
        return self.assigned_engineer


class LeadAssignment(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="assignments")
    engineer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    coordinator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    assigned_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-assigned_at"]


class LeadStageHistory(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="stage_history")
    from_stage = models.ForeignKey(LeadStage, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_stage = models.ForeignKey(LeadStage, on_delete=models.PROTECT, related_name="+")
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    changed_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-changed_at", "-pk"]
