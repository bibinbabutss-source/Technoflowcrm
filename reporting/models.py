from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class ImportBatch(models.Model):
    """One Excel / CSV import: the uploaded rows, the column mapping, the preview and the result."""

    class Kind(models.TextChoices):
        CUSTOMERS = "customers", "Customers"
        LEADS = "leads", "Leads"

    class Status(models.TextChoices):
        MAPPING = "mapping", "Waiting for column mapping"
        PREVIEW = "preview", "Previewed, not imported"
        IMPORTED = "imported", "Imported"
        CANCELLED = "cancelled", "Cancelled"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.MAPPING)
    headers = models.JSONField(default=list)
    rows = models.JSONField(default=list)
    mapping = models.JSONField(default=dict)
    results = models.JSONField(default=list, help_text="Per row: status and messages from the last preview/import")
    summary = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} import {self.created_at:%d-%b-%Y %H:%M} ({self.file_name})"

    def get_absolute_url(self):
        return reverse("reporting:import_detail", args=[self.pk])
