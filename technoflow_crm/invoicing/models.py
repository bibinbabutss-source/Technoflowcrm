from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import TaxRate, TimeStampedModel
from core.scopes import owners

OWNER_FIELDS = owners("invoicing.invoice")
PAYMENT_OWNER_FIELDS = owners("invoicing.payment")


class Invoice(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        ISSUED = "issued", "Issued"
        PARTIALLY_PAID = "partially_paid", "Partially paid"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    OPEN_STATUSES = (Status.ISSUED, Status.PARTIALLY_PAID)
    FINANCIAL_FIELDS = ("subtotal", "tax_amount", "total", "currency", "customer_id", "invoice_date")

    number = models.CharField("Invoice number", max_length=30, unique=True, null=True, blank=True, editable=False,
                              help_text="Assigned when the invoice is issued (gap-free).")
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="invoices")
    order = models.ForeignKey("orders.SalesOrder", on_delete=models.PROTECT, related_name="invoices",
                              verbose_name="Related sales order")
    milestone = models.ForeignKey("orders.PaymentMilestone", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="invoices")
    invoice_date = models.DateField(default=timezone.localdate, db_index=True)
    due_date = models.DateField(db_index=True)
    payment_terms = models.CharField(max_length=255, blank=True)
    reference = models.CharField("Reference number", max_length=100, blank=True,
                                 help_text="Customer PO or other reference printed on the invoice")
    currency = models.CharField(max_length=3, default="AED")
    subtotal = models.DecimalField("Amount excl. VAT", max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField("VAT", max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField("Invoice total", max_digits=14, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False,
                                      help_text="Sum of allocated payments net of reversals (recalculated)")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    notes = models.TextField(blank=True)
    is_disputed = models.BooleanField(default=False)
    dispute_note = models.CharField(max_length=255, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    cancel_reason = models.CharField(max_length=255, blank=True)
    last_reminder_days = models.SmallIntegerField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-invoice_date", "-pk"]

    def __str__(self):
        return self.display_number

    def get_absolute_url(self):
        return reverse("invoicing:detail", args=[self.pk])

    @property
    def display_number(self):
        return self.number or f"Draft #{self.pk}"

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            old = Invoice.objects.filter(pk=self.pk).values("status", *self.FINANCIAL_FIELDS).first()
            if old and old["status"] != self.Status.DRAFT:
                changed = [f for f in self.FINANCIAL_FIELDS if old[f] != getattr(self, f)]
                if changed:
                    raise ValidationError("An issued invoice cannot be changed. Cancel it and issue a new one.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status != self.Status.DRAFT:
            raise ValidationError("Issued invoices are never deleted; cancel them instead.")
        super().delete(*args, **kwargs)

    @property
    def outstanding(self):
        """Outstanding Balance = Invoice Total − Allocated Payments."""
        if self.status in (self.Status.DRAFT, self.Status.CANCELLED):
            return Decimal("0.00")
        return self.total - self.amount_paid

    @property
    def is_overdue(self):
        return self.status in self.OPEN_STATUSES and self.due_date < timezone.localdate() and self.outstanding > 0

    @property
    def days_overdue(self):
        return (timezone.localdate() - self.due_date).days if self.is_overdue else 0

    @property
    def display_status(self):
        return "Overdue" if self.is_overdue else self.get_status_display()

    def tone(self):
        if self.is_overdue:
            return "bad"
        return {"draft": "neutral", "issued": "info", "partially_paid": "warn", "paid": "good",
                "cancelled": "neutral"}[self.status]


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey("orders.SalesOrderLine", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="invoice_lines")
    position = models.PositiveSmallIntegerField(default=0)
    description = models.TextField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=1,
                                   validators=[MinValueValidator(Decimal("0.001"))])
    unit = models.CharField(max_length=20, blank=True, default="Lot")
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                       validators=[MinValueValidator(0), MaxValueValidator(100)])
    tax_rate = models.ForeignKey(TaxRate, on_delete=models.PROTECT, related_name="+")
    tax_rate_value = models.DecimalField(max_digits=5, decimal_places=2, default=0, editable=False)
    line_net = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)
    line_tax = models.DecimalField(max_digits=14, decimal_places=2, default=0, editable=False)

    class Meta:
        ordering = ["position", "pk"]

    def save(self, *args, **kwargs):
        if self.invoice.status != Invoice.Status.DRAFT:
            raise ValidationError("Lines of an issued invoice cannot be changed.")
        super().save(*args, **kwargs)


class Payment(TimeStampedModel):
    class Method(models.TextChoices):
        BANK = "bank", "Bank transfer"
        CHEQUE = "cheque", "Cheque"
        CASH = "cash", "Cash"
        CARD = "card", "Card"
        OTHER = "other", "Other"

    number = models.CharField("Receipt number", max_length=30, unique=True, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="payments")
    payment_date = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=14, decimal_places=2,
                                 help_text="Positive for money received; negative only for reversal entries")
    currency = models.CharField(max_length=3, default="AED")
    method = models.CharField(max_length=10, choices=Method.choices, default=Method.BANK)
    reference = models.CharField("Payment reference", max_length=100, blank=True,
                                 help_text="Bank transfer reference, cheque number...")
    notes = models.CharField(max_length=255, blank=True)
    is_reversal = models.BooleanField(default=False, editable=False)
    reverses = models.OneToOneField("self", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="reversed_by", editable=False)
    reversal_reason = models.CharField(max_length=255, blank=True, editable=False)

    class Meta:
        ordering = ["-payment_date", "-pk"]

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("invoicing:payment_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            old = Payment.objects.filter(pk=self.pk).values("amount", "customer_id", "payment_date").first()
            if old and (old["amount"] != self.amount or old["customer_id"] != self.customer_id
                        or old["payment_date"] != self.payment_date):
                raise ValidationError("A recorded payment cannot be changed. Reverse it and record it again.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Payments are never deleted. Use a reversal entry.")

    @property
    def allocated(self):
        return self.allocations.aggregate(t=models.Sum("amount"))["t"] or Decimal("0.00")

    @property
    def unallocated(self):
        return self.amount - self.allocated

    @property
    def is_reversed(self):
        return hasattr(self, "reversed_by") and self.reversed_by is not None


class PaymentAllocation(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [models.CheckConstraint(condition=~models.Q(amount=0), name="allocation_not_zero")]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Allocations cannot be edited. Reverse the payment instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Allocations are never deleted. Reverse the payment instead.")
