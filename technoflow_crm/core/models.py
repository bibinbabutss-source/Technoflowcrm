"""
Shared building blocks used by every CRM module:

- TimeStampedModel   created/updated timestamps and users on every record
- AuditLog           append-only record of important changes
- CompanyProfile     company details and system defaults (one row)
- NumberSequence     gap-free document numbers (QT-2026-0001 ...)
- LookupValue        configurable drop-down lists (categories, sources ...)
"""
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, editable=False,
        on_delete=models.PROTECT, related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, editable=False,
        on_delete=models.PROTECT, related_name="+",
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        from .middleware import get_current_user

        user = get_current_user()
        if user is not None and user.is_authenticated:
            if self._state.adding and self.created_by_id is None:
                self.created_by = user
            self.updated_by = user
        super().save(*args, **kwargs)


# ---------------------------------------------------------------- audit log
class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"
        ARCHIVE = "archive", "Archived"
        ACTIVATE = "activate", "Activated"
        DEACTIVATE = "deactivate", "Deactivated"
        LOGIN = "login", "Logged in"
        LOGOUT = "logout", "Logged out"
        LOGIN_FAILED = "login_failed", "Failed login"
        PASSWORD_RESET = "password_reset", "Password reset"
        PASSWORD_CHANGE = "password_change", "Password changed"
        PERMISSION = "permission", "Permissions changed"
        APPROVE = "approve", "Approved"
        REJECT = "reject", "Rejected"
        EXPORT = "export", "Exported"
        DOWNLOAD = "download", "Downloaded"
        OTHER = "other", "Other"

    timestamp = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name="audit_entries", editable=False,
    )
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True, editable=False)
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.PROTECT, editable=False
    )
    object_id = models.CharField(max_length=64, blank=True, db_index=True, editable=False)
    object_repr = models.CharField(max_length=255, blank=True, editable=False)
    changes = models.JSONField(default=dict, blank=True, editable=False)
    message = models.CharField(max_length=500, blank=True, editable=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True, editable=False)
    user_agent = models.CharField(max_length=300, blank=True, editable=False)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.timestamp:%d-%b-%Y %H:%M} {self.user} {self.get_action_display()} {self.object_repr}"

    # Append-only: entries can be created but never edited or deleted.
    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Audit log entries cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit log entries cannot be deleted.")


# ------------------------------------------------------- company settings
class CompanyProfile(TimeStampedModel):
    """Single row holding company details and system-wide defaults."""

    company_name = models.CharField(max_length=200, default="Technoflow Trading LLC")
    legal_name = models.CharField(max_length=200, blank=True, default="Technoflow Trading LLC")
    tax_registration_number = models.CharField("TRN", max_length=30, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True, default="Dubai")
    country = models.CharField(max_length=100, blank=True, default="United Arab Emirates")
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True, default="https://technoflow.com/")
    default_currency = models.CharField(max_length=3, default="AED")
    fiscal_year_start_month = models.PositiveSmallIntegerField(
        default=1, validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    max_upload_mb = models.PositiveSmallIntegerField(
        "Maximum upload size (MB)", default=20, validators=[MinValueValidator(1), MaxValueValidator(100)]
    )
    allowed_upload_extensions = models.CharField(
        max_length=300, default="pdf,doc,docx,xls,xlsx,csv,jpg,jpeg,png",
        help_text="Comma-separated list of file extensions users may upload.",
    )
    quotation_validity_days = models.PositiveSmallIntegerField(default=30)
    default_payment_terms_days = models.PositiveSmallIntegerField(default=30)

    # ---- quotation approval rules
    approval_threshold = models.DecimalField(
        "Approval needed from grand total of", max_digits=14, decimal_places=2, default=0,
        validators=[MinValueValidator(0)],
        help_text="Quotations with a grand total at or above this amount need Sales Director approval. "
                  "0 = every quotation needs approval.")
    discount_approval_limit = models.DecimalField(
        "Approval needed above discount (%)", max_digits=5, decimal_places=2, default=10,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Any line discount above this percentage always needs approval, whatever the total.")
    quotation_expiry_warning_days = models.PositiveSmallIntegerField(
        "Warn before quotation expiry (days)", default=7)

    # ---- reminders and notifications
    email_notifications_enabled = models.BooleanField(
        "Send notification emails", default=False,
        help_text="Requires the SMTP email settings to be configured on the server.")
    visit_reminder_days = models.PositiveSmallIntegerField("Remind about visits (days before)", default=1)
    task_reminder_days = models.PositiveSmallIntegerField("Remind about tasks due within (days)", default=1)
    overdue_reminder_days = models.CharField(
        "Overdue invoice reminders (days after due date)", max_length=50, default="1,7,30",
        help_text="Comma-separated, e.g. 1,7,30")

    # ---- KPI rating bands (score out of 100)
    rating_excellent = models.PositiveSmallIntegerField("Excellent from", default=90,
                                                        validators=[MaxValueValidator(100)])
    rating_good = models.PositiveSmallIntegerField("Good from", default=75, validators=[MaxValueValidator(100)])
    rating_satisfactory = models.PositiveSmallIntegerField("Satisfactory from", default=60,
                                                           validators=[MaxValueValidator(100)])

    class Meta:
        verbose_name = "Company profile"

    def clean(self):
        if not (self.rating_excellent > self.rating_good > self.rating_satisfactory):
            raise ValidationError("Rating bands must decrease: Excellent > Good > Satisfactory.")
        try:
            self.overdue_reminder_list
        except ValueError:
            raise ValidationError({"overdue_reminder_days": "Use whole numbers separated by commas, e.g. 1,7,30."})

    @property
    def overdue_reminder_list(self):
        return sorted({int(x) for x in self.overdue_reminder_days.split(",") if x.strip()})

    def rating_for(self, score):
        if score is None:
            return "No target"
        if score >= self.rating_excellent:
            return "Excellent"
        if score >= self.rating_good:
            return "Good"
        if score >= self.rating_satisfactory:
            return "Satisfactory"
        return "Needs improvement"

    def __str__(self):
        return self.company_name

    def save(self, *args, **kwargs):
        self.pk = 1  # enforce a single row
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("The company profile cannot be deleted.")

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def extension_list(self):
        return [e.strip().lower().lstrip(".") for e in self.allowed_upload_extensions.split(",") if e.strip()]


# ------------------------------------------------------- document numbers
class NumberSequence(TimeStampedModel):
    """
    Issues document numbers such as QT-2026-0001.

    next_value() locks the row inside a transaction, so two users saving
    at the same moment can never receive the same number.
    """

    code = models.SlugField(max_length=30, unique=True, help_text="Internal key, e.g. quotation")
    name = models.CharField(max_length=100)
    prefix = models.CharField(max_length=10)
    include_year = models.BooleanField(default=True)
    reset_yearly = models.BooleanField(default=True)
    padding = models.PositiveSmallIntegerField(default=4, validators=[MinValueValidator(3), MaxValueValidator(8)])
    current_year = models.PositiveSmallIntegerField(null=True, blank=True)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.preview()})"

    def format(self, number, year):
        parts = [self.prefix]
        if self.include_year:
            parts.append(str(year))
        parts.append(str(number).zfill(self.padding))
        return "-".join(parts)

    def preview(self):
        year = timezone.localdate().year
        nxt = 1 if (self.reset_yearly and self.current_year != year) else self.last_number + 1
        return self.format(nxt, year)

    @classmethod
    def next_value(cls, code):
        year = timezone.localdate().year
        with transaction.atomic():
            seq = cls.objects.select_for_update().get(code=code)
            if seq.reset_yearly and seq.current_year != year:
                seq.last_number = 0
            seq.current_year = year
            seq.last_number += 1
            seq.save(update_fields=["last_number", "current_year", "updated_at"])
            return seq.format(seq.last_number, year)


# --------------------------------------------------------- lookup lists
class LookupValue(TimeStampedModel):
    """Configurable drop-down values maintained by the System Administrator."""

    class Category(models.TextChoices):
        CUSTOMER_CATEGORY = "customer_category", "Customer category"
        INDUSTRY = "industry", "Industry"
        LEAD_SOURCE = "lead_source", "Lead / opportunity source"
        PROJECT_TYPE = "project_type", "Project type"
        VISIT_PURPOSE = "visit_purpose", "Visit purpose"
        LOST_REASON = "lost_reason", "Lost reason"
        DEPARTMENT = "department", "Department"
        DOCUMENT_CATEGORY = "document_category", "Document category"

    category = models.CharField(max_length=40, choices=Category.choices, db_index=True)
    value = models.CharField(max_length=100)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "sort_order", "value"]
        constraints = [
            models.UniqueConstraint(fields=["category", "value"], name="uniq_lookup_category_value"),
        ]

    def __str__(self):
        return self.value

    @classmethod
    def choices_for(cls, category):
        return cls.objects.filter(category=category, is_active=True)


# ------------------------------------------------------------- tax rates
class TaxRate(TimeStampedModel):
    """VAT / tax rates maintained by the Administrator (never hardcoded)."""

    name = models.CharField(max_length=60, unique=True)
    rate = models.DecimalField("Rate (%)", max_digits=5, decimal_places=2,
                               validators=[MinValueValidator(0), MaxValueValidator(100)])
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.rate.normalize():f}%)"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            TaxRate.objects.exclude(pk=self.pk).filter(is_default=True).update(is_default=False)

    @classmethod
    def default(cls):
        return cls.objects.filter(is_active=True, is_default=True).first() or cls.objects.filter(is_active=True).first()


# ------------------------------------------------------- activity timeline
class Activity(models.Model):
    """
    Business timeline entry shown on record pages and the customer timeline:
    creation, assignment, status changes, comments, approvals, revisions,
    order confirmation, invoices, payments, documents.
    """

    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        ASSIGNED = "assigned", "Assigned"
        STATUS = "status", "Status changed"
        COMMENT = "comment", "Comment"
        APPROVAL = "approval", "Approval"
        REVISION = "revision", "Revision"
        CONVERTED = "converted", "Converted"
        ORDER = "order", "Order"
        INVOICE = "invoice", "Invoice"
        PAYMENT = "payment", "Payment"
        DOCUMENT = "document", "Document"
        COMMUNICATION = "communication", "Communication"
        VISIT = "visit", "Visit"
        TASK = "task", "Task"

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                             related_name="+")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    message = models.CharField(max_length=500)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    object_repr = models.CharField(max_length=255)
    customer = models.ForeignKey("customers.Customer", null=True, blank=True, on_delete=models.CASCADE,
                                 related_name="activities")
    financial = models.BooleanField(default=False, help_text="Shown only to users who can see invoices")

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]
        verbose_name_plural = "activities"

    def __str__(self):
        return f"{self.object_repr}: {self.message}"


class SystemJobRun(models.Model):
    """Remembers when a daily job (reminders) last ran, so it runs once per day."""

    name = models.CharField(max_length=60, unique=True)
    last_run_date = models.DateField(null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_result = models.CharField(max_length=500, blank=True)
