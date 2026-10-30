from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import LookupValue, NumberSequence, TimeStampedModel
from core.scopes import owners

OWNER_FIELDS = owners("sales.opportunity")
PROJECT_OWNER_FIELDS = owners("sales.project")


def weighted(value, probability):
    """Weighted Forecast = Estimated Value × Closing Probability % (rounded to 2 decimals)."""
    return (Decimal(value or 0) * Decimal(probability or 0) / Decimal(100)).quantize(Decimal("0.01"), ROUND_HALF_UP)


class OpportunityStage(TimeStampedModel):
    name = models.CharField(max_length=60, unique=True)
    order = models.PositiveSmallIntegerField(default=0)
    default_probability = models.PositiveSmallIntegerField(default=10, validators=[MaxValueValidator(100)])
    is_won = models.BooleanField(default=False, editable=False)
    is_lost = models.BooleanField(default=False, editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "pk"]

    def __str__(self):
        return self.name

    @property
    def is_closed(self):
        return self.is_won or self.is_lost

    @classmethod
    def first_open(cls):
        return cls.objects.filter(is_active=True, is_won=False, is_lost=False).first()


class Opportunity(TimeStampedModel):
    code = models.CharField("Opportunity ID", max_length=20, unique=True, editable=False)
    title = models.CharField("Opportunity title", max_length=200)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="opportunities")
    lead = models.ForeignKey("leads.Lead", null=True, blank=True, on_delete=models.PROTECT,
                             related_name="opportunities", verbose_name="Related lead")
    assigned_engineer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="opportunities_as_engineer")
    assigned_coordinator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="opportunities_as_coordinator")
    team_members = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="opportunity_teams",
                                          help_text="Other employees working on this opportunity. Revenue is "
                                                    "still credited once, to the responsible employee.")
    source = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                               limit_choices_to={"category": "lead_source"}, verbose_name="Opportunity source")
    project_type = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                     limit_choices_to={"category": "project_type"})
    location = models.CharField(max_length=200, blank=True)
    estimated_value = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                          validators=[MinValueValidator(0)])
    probability = models.PositiveSmallIntegerField("Closing probability (%)", default=10,
                                                   validators=[MaxValueValidator(100)])
    expected_close_date = models.DateField("Expected closing date", null=True, blank=True, db_index=True)
    stage = models.ForeignKey(OpportunityStage, on_delete=models.PROTECT, related_name="opportunities")
    products_services = models.TextField("Expected services / products", blank=True)
    competitors = models.CharField("Competitor information", max_length=255, blank=True)
    next_action = models.CharField(max_length=255, blank=True)
    next_follow_up = models.DateField("Next follow-up date", null=True, blank=True, db_index=True)
    notes = models.TextField(blank=True)
    lost_reason = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                    limit_choices_to={"category": "lost_reason"})
    lost_notes = models.CharField(max_length=255, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    stage_changed_at = models.DateTimeField(default=timezone.now)
    is_archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "opportunities"

    def __str__(self):
        return f"{self.code} {self.title}" if self.code else self.title

    def get_absolute_url(self):
        return reverse("sales:opportunity_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next_value("opportunity")
        if self.stage_id:
            stage = self.stage
            if stage.is_won:
                self.probability = 100
            elif stage.is_lost:
                self.probability = 0
        super().save(*args, **kwargs)

    @property
    def weighted_value(self):
        return weighted(self.estimated_value, self.probability)

    @property
    def is_open(self):
        return not self.stage.is_closed

    @property
    def is_close_date_overdue(self):
        return self.is_open and self.expected_close_date and self.expected_close_date < timezone.localdate()

    @property
    def is_follow_up_overdue(self):
        return self.is_open and self.next_follow_up and self.next_follow_up < timezone.localdate()

    @property
    def kanban_title(self):
        return self.title

    @property
    def kanban_subtitle(self):
        return f"{self.code} · {self.customer.company_name} · {self.probability}%"

    @property
    def kanban_value(self):
        return self.estimated_value

    @property
    def kanban_owner(self):
        return self.assigned_engineer


class OpportunityStageHistory(models.Model):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="stage_history")
    from_stage = models.ForeignKey(OpportunityStage, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    to_stage = models.ForeignKey(OpportunityStage, on_delete=models.PROTECT, related_name="+")
    probability = models.PositiveSmallIntegerField()
    estimated_value = models.DecimalField(max_digits=14, decimal_places=2)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    changed_at = models.DateTimeField(default=timezone.now)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-changed_at", "-pk"]


class Project(TimeStampedModel):
    """A project under execution (delivery), normally created from a confirmed sales order."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In progress"
        ON_HOLD = "on_hold", "On hold"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    code = models.CharField("Project ID", max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=200)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="projects")
    opportunity = models.ForeignKey(Opportunity, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="projects")
    sales_order = models.ForeignKey("orders.SalesOrder", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="projects")
    project_type = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                     limit_choices_to={"category": "project_type"})
    location = models.CharField(max_length=200, blank=True)
    project_manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="projects_managed")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNED, db_index=True)
    progress = models.PositiveSmallIntegerField("Progress (%)", default=0, validators=[MaxValueValidator(100)])
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField("Planned completion", null=True, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} {self.name}" if self.code else self.name

    def get_absolute_url(self):
        return reverse("sales:project_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next_value("project")
        if self.status == self.Status.COMPLETED:
            self.progress = 100
        super().save(*args, **kwargs)
