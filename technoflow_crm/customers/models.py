import re

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.scopes import owners
from core.models import LookupValue, NumberSequence, TimeStampedModel

OWNER_FIELDS = owners("customers.customer")

LEGAL_SUFFIXES = r"\b(l\.?l\.?c|llc|fze|fzco|fzllc|co|company|est|establishment|ltd|limited|plc|inc|trading|group)\b"


def normalize_name(name):
    """'ABC Developers L.L.C.' and 'abc developers llc' both become 'abc developers'."""
    text = (name or "").lower()
    text = re.sub(LEGAL_SUFFIXES, " ", text)
    text = re.sub(r"[^a-z0-9؀-ۿ]+", " ", text)
    return " ".join(text.split())


def normalize_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("971"):
        digits = digits[3:]
    return digits.lstrip("0")


class Customer(TimeStampedModel):
    class Status(models.TextChoices):
        PROSPECT = "prospect", "Prospect"
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        ON_HOLD = "on_hold", "On hold"

    code = models.CharField("Customer ID", max_length=20, unique=True, editable=False)
    company_name = models.CharField(max_length=200)
    normalized_name = models.CharField(max_length=200, db_index=True, editable=False)
    category = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                 limit_choices_to={"category": "customer_category"})
    industry = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                                 limit_choices_to={"category": "industry"})
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROSPECT, db_index=True)
    # primary contact
    contact_person = models.CharField(max_length=150, blank=True)
    designation = models.CharField(max_length=100, blank=True)
    phone = models.CharField("Primary phone", max_length=40, blank=True)
    alt_phone = models.CharField("Alternative phone", max_length=40, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    # addresses
    billing_address = models.TextField(blank=True)
    office_address = models.TextField(blank=True)
    city = models.CharField("Emirate / city", max_length=100, blank=True)
    country = models.CharField(max_length=100, default="United Arab Emirates", blank=True)
    trn = models.CharField("Tax registration number (TRN)", max_length=30, blank=True, db_index=True)
    # ownership
    assigned_engineer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="customers_as_engineer")
    assigned_coordinator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="customers_as_coordinator")
    source = models.ForeignKey(LookupValue, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
                               limit_choices_to={"category": "lead_source"}, verbose_name="Customer source")
    last_contact_date = models.DateField(null=True, blank=True)
    next_follow_up = models.DateField("Next follow-up date", null=True, blank=True, db_index=True)
    notes = models.TextField("Internal notes", blank=True)
    is_archived = models.BooleanField(default=False, db_index=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["company_name"]
        indexes = [models.Index(fields=["assigned_engineer", "status"])]

    def __str__(self):
        return f"{self.company_name} ({self.code})" if self.code else self.company_name

    def get_absolute_url(self):
        return reverse("customers:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next_value("customer")
        self.normalized_name = normalize_name(self.company_name)
        self.email = (self.email or "").strip().lower()
        self.trn = (self.trn or "").replace(" ", "").upper()
        super().save(*args, **kwargs)

    @property
    def is_follow_up_overdue(self):
        return bool(self.next_follow_up and self.next_follow_up < timezone.localdate())

    def status_tone(self):
        return {"active": "good", "prospect": "info", "on_hold": "warn", "inactive": "neutral"}.get(self.status)

    def touch_contact(self, date=None, next_follow_up=None):
        """Record that the customer was contacted (visits and communications call this)."""
        date = date or timezone.localdate()
        fields = []
        if not self.last_contact_date or date > self.last_contact_date:
            self.last_contact_date = date
            fields.append("last_contact_date")
        if next_follow_up:
            self.next_follow_up = next_follow_up
            fields.append("next_follow_up")
        if fields:
            Customer.objects.filter(pk=self.pk).update(**{f: getattr(self, f) for f in fields})


class CustomerContact(TimeStampedModel):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=150)
    designation = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    is_primary = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-is_primary", "name"]

    def __str__(self):
        return f"{self.name} ({self.customer.company_name})"

    def get_absolute_url(self):
        return self.customer.get_absolute_url() + "#contacts"
