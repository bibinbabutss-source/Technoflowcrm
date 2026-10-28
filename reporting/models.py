from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class ImportBatch(models.Model):
    """One Excel / CSV import: the uploaded rows, the column mapping, the preview and the result."""

    class Kind(models.TextChoices):
        CUSTOMERS = "customers", "Customers"
        LEADS = "leads", "Sales leads"
        VISITS = "visits", "Customer visits"
        TASKS = "tasks", "Follow-ups and tasks"
        OPPORTUNITIES = "opportunities", "Opportunities and completed sales"

    class Mode(models.TextChoices):
        SKIP = "skip", "Import new records, skip duplicates"
        UPDATE = "update", "Import new records and update existing ones when there is a reliable match"
        UPDATE_ONLY = "update_only", "Only update existing records (reliable matches), import nothing new"

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
    mode = models.CharField("Duplicates", max_length=12, choices=Mode.choices, default=Mode.SKIP,
                            db_default="skip")  # keeps an older code version working after a rollback
    imported_at = models.DateTimeField(null=True, blank=True)
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


class ImportKey(models.Model):
    """
    Remembers what each imported row created, by the row's Reference (or a fingerprint of its key columns),
    so the same file uploaded again is recognised and never creates duplicate records or revenue.
    """

    kind = models.CharField(max_length=20)
    key = models.CharField(max_length=120)
    object_id = models.PositiveBigIntegerField()
    batch = models.ForeignKey(ImportBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="keys")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "key"], name="uniq_import_key")]

    def __str__(self):
        return f"{self.kind} {self.key} -> {self.object_id}"
