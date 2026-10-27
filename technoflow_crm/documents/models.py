import uuid
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import LookupValue, TimeStampedModel
from core.scopes import owners

OWNER_FIELDS = owners("documents.document")


class PrivateStorage(FileSystemStorage):
    """Uploaded files live in MEDIA_ROOT, which is never published by the web server; downloads go
    through a permission-checked view. base_url=None means Django cannot build a public URL for them."""

    def __init__(self, **kwargs):
        kwargs.setdefault("location", settings.MEDIA_ROOT)
        kwargs["base_url"] = None
        super().__init__(**kwargs)

    def url(self, name):
        raise ValueError("Private documents have no public URL. Use the download view.")


def private_path(instance, filename):
    """Safe internal name: documents/2026/10/<random>.pdf (the original name is stored separately)."""
    ext = Path(filename).suffix.lower()[:10]
    today = timezone.localdate()
    return f"documents/{today:%Y}/{today:%m}/{uuid.uuid4().hex}{ext}"


class Document(TimeStampedModel):
    title = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True)
    category = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                 limit_choices_to={"category": "document_category"})
    file = models.FileField(upload_to=private_path, storage=PrivateStorage(), max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    content_type_mime = models.CharField("File type", max_length=100)
    sha256 = models.CharField(max_length=64, editable=False)
    version = models.PositiveSmallIntegerField(default=1)
    previous = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="next_version")
    is_current = models.BooleanField(default=True, db_index=True)
    target_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    target_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("target_type", "target_id")
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="documents")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="documents")
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self):
        return f"{self.title} (v{self.version})"

    def get_absolute_url(self):
        return reverse("documents:detail", args=[self.pk])

    @property
    def extension(self):
        return Path(self.original_name).suffix.lower().lstrip(".")

    @property
    def icon(self):
        return {"pdf": "file-earmark-pdf", "doc": "file-earmark-word", "docx": "file-earmark-word",
                "xls": "file-earmark-excel", "xlsx": "file-earmark-excel", "csv": "file-earmark-spreadsheet",
                "png": "file-earmark-image", "jpg": "file-earmark-image", "jpeg": "file-earmark-image"}.get(
            self.extension, "file-earmark")
