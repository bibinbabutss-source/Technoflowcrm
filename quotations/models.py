from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import NumberSequence, TaxRate, TimeStampedModel
from core.scopes import owners

OWNER_FIELDS = owners("quotations.quotation")


class Quotation(TimeStampedModel):
    """The quotation 'folder': one number, many revisions. The current revision is what counts."""

    number = models.CharField("Quotation number", max_length=30, unique=True, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="quotations")
    opportunity = models.ForeignKey("sales.Opportunity", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="quotations", verbose_name="Related opportunity")
    salesperson = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name="quotations_as_salesperson")
    currency = models.CharField(max_length=3, default="AED")
    current_version = models.PositiveSmallIntegerField(default=1, editable=False)
    # denormalised from the current revision for fast filtering
    status = models.CharField(max_length=20, default="draft", db_index=True, editable=False)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    quotation_date = models.DateField(null=True, editable=False, db_index=True)
    expiry_date = models.DateField(null=True, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.number or "New quotation"

    def get_absolute_url(self):
        return reverse("quotations:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = NumberSequence.next_value("quotation")
        super().save(*args, **kwargs)

    @property
    def current(self):
        if not hasattr(self, "_current"):
            self._current = self.revisions.filter(version=self.current_version).first()
        return self._current

    def sync_from_current(self):
        rev = self.revisions.get(version=self.current_version)
        self._current = rev
        Quotation.objects.filter(pk=self.pk).update(status=rev.status, grand_total=rev.grand_total,
                                                    quotation_date=rev.quotation_date, expiry_date=rev.expiry_date)
        self.status, self.grand_total = rev.status, rev.grand_total
        self.quotation_date, self.expiry_date = rev.quotation_date, rev.expiry_date

    @property
    def display_number(self):
        return f"{self.number} Rev {self.current_version}"


class QuotationRevision(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted for approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SENT = "sent", "Sent to customer"
        ACCEPTED = "accepted", "Accepted by customer"
        DECLINED = "declined", "Declined by customer"
        EXPIRED = "expired", "Expired"
        SUPERSEDED = "superseded", "Superseded by a newer revision"

    FINANCIAL_FIELDS = ("header_discount", "subtotal", "discount_total", "taxable_amount", "tax_amount",
                        "grand_total", "currency")

    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="revisions")
    version = models.PositiveSmallIntegerField()
    quotation_date = models.DateField(default=timezone.localdate)
    expiry_date = models.DateField()
    currency = models.CharField(max_length=3, default="AED")
    payment_terms = models.TextField(blank=True)
    delivery_terms = models.TextField(blank=True)
    scope_of_work = models.TextField(blank=True)
    exclusions = models.TextField(blank=True)
    warranty_terms = models.TextField(blank=True)
    validity = models.CharField("Validity statement", max_length=255, blank=True)
    customer_notes = models.TextField("Customer-facing notes", blank=True)
    internal_remarks = models.TextField(blank=True)
    header_discount = models.DecimalField("Overall discount (amount)", max_digits=14, decimal_places=2, default=0,
                                          validators=[MinValueValidator(0)])
    # calculated by core.money.calculate — never typed in
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_locked = models.BooleanField(default=False, editable=False)
    approval_required = models.BooleanField(default=True, editable=False)
    approval_reason = models.CharField(max_length=255, blank=True, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decision_comments = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    customer_response_at = models.DateField(null=True, blank=True)
    accepted_by_name = models.CharField("Accepted by (customer)", max_length=150, blank=True)
    customer_reference = models.CharField("Customer PO / reference", max_length=100, blank=True)
    decline_reason = models.CharField(max_length=255, blank=True)
    revision_reason = models.CharField(max_length=255, blank=True)

    # ---- quotation document (cover letter, price schedule) — editable while the revision is a draft.
    # Empty values fall back to the customer / opportunity / company quotation template when printing.
    customer_name = models.CharField("Customer name (as printed)", max_length=200, blank=True,
                                     help_text="Leave empty to use the customer's company name.")
    customer_address = models.TextField("Customer address (as printed)", blank=True,
                                        help_text="P.O. Box, city… Leave empty to use the customer's address.")
    attention = models.CharField("Kind attention (K/Attn)", max_length=150, blank=True,
                                 help_text="Leave empty to use the customer's contact person.")
    subject = models.CharField(max_length=200, blank=True)
    project_name = models.CharField("Project", max_length=200, blank=True,
                                    help_text="Leave empty to use the opportunity title.")
    consultant = models.CharField(max_length=150, blank=True)
    letter_body = models.TextField("Cover letter text", blank=True,
                                   help_text="Salutation and paragraphs. Use **text** for bold.")
    letter_closing = models.TextField("Closing", blank=True)
    signatory_name = models.CharField("Signatory name", max_length=150, blank=True)
    signatory_designation = models.CharField("Signatory designation", max_length=150, blank=True)
    manufacturer = models.CharField("Manufacturer / brand line", max_length=150, blank=True,
                                    help_text="Printed above the price table, e.g. TFL VALVES.")
    schedule_note = models.CharField("Price schedule note", max_length=255, blank=True)
    sales_engineer_name = models.CharField("Sales engineer (printed)", max_length=150, blank=True,
                                           help_text="Leave empty to use the salesperson's name.")
    sales_in_charge_name = models.CharField("Sales in charge (printed)", max_length=150, blank=True)
    approved_by_name = models.CharField("Approved by (printed)", max_length=150, blank=True)

    DOCUMENT_FIELDS = ("customer_name", "customer_address", "attention", "subject", "project_name", "consultant",
                       "letter_body", "letter_closing", "signatory_name", "signatory_designation", "manufacturer",
                       "schedule_note", "sales_engineer_name", "sales_in_charge_name", "approved_by_name")

    class Meta:
        ordering = ["quotation", "-version"]
        constraints = [models.UniqueConstraint(fields=["quotation", "version"], name="uniq_quotation_version")]

    def __str__(self):
        return f"{self.quotation.number} Rev {self.version}"

    def get_absolute_url(self):
        return reverse("quotations:detail", args=[self.quotation_id]) + f"?rev={self.version}"

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            old = QuotationRevision.objects.filter(pk=self.pk).values(*self.FINANCIAL_FIELDS, "is_locked").first()
            if old and old["is_locked"]:
                changed = [f for f in self.FINANCIAL_FIELDS if old[f] != getattr(self, f)]
                if changed:
                    raise ValidationError(
                        "This revision is locked: its financial values cannot be changed. Create a new revision.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_locked:
            raise ValidationError("A submitted or approved revision cannot be deleted.")
        super().delete(*args, **kwargs)

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT and not self.is_locked

    @property
    def is_current(self):
        return self.version == self.quotation.current_version

    @property
    def is_past_expiry(self):
        return self.expiry_date < timezone.localdate()

    @property
    def max_discount_pct(self):
        return max((ln.discount_pct for ln in self.lines.all()), default=Decimal(0))

    def tone(self):
        return {"draft": "neutral", "submitted": "warn", "approved": "info", "rejected": "bad", "sent": "info",
                "accepted": "good", "declined": "bad", "expired": "neutral", "superseded": "neutral"}[self.status]


class QuotationLine(models.Model):
    revision = models.ForeignKey(QuotationRevision, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField(default=0)
    part_no = models.CharField("Part no.", max_length=60, blank=True)
    description = models.TextField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3, validators=[MinValueValidator(Decimal("0.001"))])
    unit = models.CharField(max_length=20, blank=True, default="Lot")
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    discount_pct = models.DecimalField("Discount (%)", max_digits=5, decimal_places=2, default=0,
                                       validators=[MinValueValidator(0), MaxValueValidator(100)])
    tax_rate = models.ForeignKey(TaxRate, on_delete=models.PROTECT, related_name="+")
    tax_rate_value = models.DecimalField(max_digits=5, decimal_places=2, default=0, editable=False,
                                         help_text="Rate at the time the line was saved")
    line_net = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    line_tax = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self):
        return self.description[:60]

    def save(self, *args, **kwargs):
        if self.revision.is_locked:
            raise ValidationError("Lines of a locked revision cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.revision.is_locked:
            raise ValidationError("Lines of a locked revision cannot be deleted.")
        super().delete(*args, **kwargs)


class QuotationTerm(models.Model):
    """One row of the 'Commercial terms and conditions' table of a revision."""

    revision = models.ForeignKey(QuotationRevision, on_delete=models.CASCADE, related_name="terms")
    position = models.PositiveSmallIntegerField(default=0)
    heading = models.CharField(max_length=100)
    content = models.TextField(help_text="Use **text** for bold.")

    class Meta:
        ordering = ["position", "pk"]

    def __str__(self):
        return self.heading

    def save(self, *args, **kwargs):
        if self.revision.is_locked:
            raise ValidationError("Terms of a locked revision cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.revision.is_locked:
            raise ValidationError("Terms of a locked revision cannot be deleted.")
        super().delete(*args, **kwargs)


class QuotationTemplate(TimeStampedModel):
    """
    Company-wide wording of the printed quotation (one row). Defaults for new quotations and the
    letterhead / footer of every quotation PDF and Word file. Edited in Settings > Quotation template.
    """

    letterhead_tagline = models.CharField("Line under the logo", max_length=100, blank=True,
                                          default="AN ISO 9001:2015 COMPANY")
    arabic_name = models.CharField("Company name in Arabic", max_length=150, blank=True,
                                   default="تيكنوفلو للتجارة (ش.ذ.م.م)")
    letter_body = models.TextField("Default cover letter text", default=(
        "Dear Sir / Madam,\n\n"
        "We acknowledge with thanks the receipt of your valuable enquiry and are pleased to submit our "
        "Techno-Commercial offer for subject requirement for your kind review and consideration.\n\n"
        "Our offer consist of detailed Price Schedule, Commercial Terms & Conditions and Datasheets (as applicable).\n\n"
        "We hope the above meets your requirement and we request you to kindly accept the above proposal.\n\n"
        "If you require any additional information or clarification, please feel free to contact us.\n\n"
        "Thanking you and assuring you of our best attention and services at all times."))
    letter_closing = models.TextField("Default closing", default="Your's Faithfully,\nFor Technoflow Trading LLC,")
    signatory_designation = models.CharField("Default signatory designation", max_length=150,
                                             default="Asst. Sales Manager")
    signature_label = models.CharField("Signature label (right side)", max_length=60,
                                       default="Authorised Signatory")
    schedule_note = models.CharField("Default price schedule note", max_length=255,
                                     default="NOTE : VAT WILL BE APPLICABLE FROM 1ST OF JANUARY 2018 AS PER UAE LAW")
    show_unit = models.BooleanField("Show the unit next to the quantity", default=False)
    footer_tagline = models.CharField("Footer line 1", max_length=100, blank=True, default="Technology at its best")
    footer_website = models.CharField("Footer line 2 (website)", max_length=100, blank=True,
                                      default="Technoflow.com")
    footer_business_lines = models.CharField("Footer business lines", max_length=255, blank=True, default=(
        "||Building Services | Industrial and Infrastructure | Marine and Oil & Gas | Fire Fighting | Generators ||"))
    footer_contact = models.CharField("Footer contact line", max_length=300, blank=True, default=(
        "E mail: info@technoflow.com, Telephone : +971 4 286 2037, Fax Line : +971 4 286 2038, "
        "Address: P.O. Box 35970, Dubai, United Arab Emirates"))
    default_terms = models.JSONField("Default commercial terms", default=list, blank=True,
                                     help_text="List of [heading, text] rows copied into each new quotation.")

    class Meta:
        verbose_name = "quotation template"

    def __str__(self):
        return "Quotation template"

    @classmethod
    def get(cls):
        obj = cls.objects.order_by("pk").first()
        if obj is None:
            from .document import DEFAULT_TERMS

            obj = cls.objects.create(default_terms=[list(t) for t in DEFAULT_TERMS])
        return obj


class Approval(models.Model):
    class Decision(models.TextChoices):
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        AUTO = "auto", "No approval needed (within limits)"

    revision = models.ForeignKey(QuotationRevision, on_delete=models.CASCADE, related_name="approvals")
    decision = models.CharField(max_length=10, choices=Decision.choices)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(default=timezone.now)
    comments = models.TextField(blank=True)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["-decided_at"]
