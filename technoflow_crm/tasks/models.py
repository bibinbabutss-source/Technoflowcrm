from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.scopes import owners
from core.models import NumberSequence, TimeStampedModel

OWNER_FIELDS = owners("tasks.task")


class Task(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        WAITING = "waiting", "Waiting"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Category(models.TextChoices):
        GENERAL = "general", "General"
        FOLLOW_UP = "follow_up", "Follow-up"
        COLLECTION = "collection", "Collection follow-up"
        DOCUMENTATION = "documentation", "Documentation"

    OPEN_STATUSES = (Status.OPEN, Status.IN_PROGRESS, Status.WAITING)

    code = models.CharField("Task ID", max_length=20, unique=True, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.GENERAL)
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="tasks")
    lead = models.ForeignKey("leads.Lead", null=True, blank=True, on_delete=models.PROTECT, related_name="tasks")
    visit = models.ForeignKey("visits.Visit", null=True, blank=True, on_delete=models.PROTECT, related_name="tasks")
    opportunity = models.ForeignKey("sales.Opportunity", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="tasks")
    quotation = models.ForeignKey("quotations.Quotation", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="tasks")
    invoice = models.ForeignKey("invoicing.Invoice", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="tasks")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tasks")
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["due_date", "pk"]
        indexes = [models.Index(fields=["assigned_to", "status", "due_date"])]

    def __str__(self):
        return f"{self.code} {self.title}" if self.code else self.title

    def get_absolute_url(self):
        return reverse("tasks:detail", args=[self.pk])

    def clean(self):
        if self.start_date and self.due_date and self.start_date > self.due_date:
            raise ValidationError({"due_date": "The due date cannot be before the start date."})

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next_value("task")
        if self.status == self.Status.COMPLETED and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status != self.Status.COMPLETED:
            self.completed_at = None
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES

    @property
    def is_overdue(self):
        return self.is_open and self.due_date < timezone.localdate()

    def related_records(self):
        return [r for r in (self.customer, self.lead, self.visit, self.opportunity, self.quotation, self.invoice) if r]


class TaskComment(models.Model):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    text = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]
