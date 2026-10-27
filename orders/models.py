from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import NumberSequence, TaxRate, TimeStampedModel
from core.scopes import owners

OWNER_FIELDS = owners("orders.salesorder")


class SalesOrder(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft (awaiting confirmation)"
        CONFIRMED = "confirmed", "Confirmed"
        IN_PROGRESS = "in_progress", "In progress"
        PARTIALLY_COMPLETED = "partially_completed", "Partially completed"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    BOOKED_STATUSES = (Status.CONFIRMED, Status.IN_PROGRESS, Status.PARTIALLY_COMPLETED, Status.COMPLETED)

    number = models.CharField("Order number", max_length=30, unique=True, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="orders")
    quotation = models.ForeignKey("quotations.Quotation", on_delete=models.PROTECT, related_name="orders")
    revision = models.ForeignKey("quotations.QuotationRevision", on_delete=models.PROTECT, related_name="orders",
                                 verbose_name="Accepted quotation revision")
    opportunity = models.ForeignKey("sales.Opportunity", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="orders")
    order_date = models.DateField(default=timezone.localdate, db_index=True)
    currency = models.CharField(max_length=3, default="AED")
    net_amount = models.DecimalField("Order value excl. VAT", max_digits=14, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_amount = models.DecimalField("Order total incl. VAT", max_digits=14, decimal_places=2, default=0)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders",
                                    verbose_name="Assigned employee")
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.DRAFT, db_index=True)
    customer_po_ref = models.CharField("Customer PO reference", max_length=100, blank=True)
    delivery_details = models.TextField("Delivery / service details", blank=True)
    payment_terms = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    cancel_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-order_date", "-pk"]

    def __str__(self):
        return self.number or "New order"

    def get_absolute_url(self):
        return reverse("orders:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = NumberSequence.next_value("order")
        super().save(*args, **kwargs)

    @property
    def is_booked(self):
        return self.status in self.BOOKED_STATUSES

    def invoiced_total(self):
        return self.invoices.exclude(status__in=["draft", "cancelled"]).aggregate(
            t=models.Sum("total"))["t"] or Decimal(0)

    def uninvoiced_total(self):
        return self.total_amount - self.invoiced_total()

    def tone(self):
        return {"draft": "warn", "confirmed": "info", "in_progress": "info", "partially_completed": "info",
                "completed": "good", "cancelled": "neutral"}[self.status]


class SalesOrderLine(models.Model):
    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveSmallIntegerField(default=0)
    description = models.TextField()
    quantity = models.DecimalField(max_digits=12, decimal_places=3)
    unit = models.CharField(max_length=20, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_rate = models.ForeignKey(TaxRate, on_delete=models.PROTECT, related_name="+")
    tax_rate_value = models.DecimalField(max_digits=5, decimal_places=2)
    line_net = models.DecimalField(max_digits=14, decimal_places=2)
    line_taxable = models.DecimalField(max_digits=14, decimal_places=2,
                                       help_text="Line net after its share of the overall discount")
    line_tax = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["position", "pk"]


class PaymentMilestone(models.Model):
    """Invoicing schedule of an order, e.g. 30% advance, 40% progress, 30% final."""

    order = models.ForeignKey(SalesOrder, on_delete=models.CASCADE, related_name="milestones")
    sequence = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100)
    percentage = models.DecimalField(max_digits=5, decimal_places=2,
                                     validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(100)])
    amount = models.DecimalField("Amount incl. VAT", max_digits=14, decimal_places=2, default=0)
    due_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["order", "sequence"]
        constraints = [models.UniqueConstraint(fields=["order", "sequence"], name="uniq_milestone_sequence")]

    def __str__(self):
        return f"{self.name} ({self.percentage.normalize():f}%)"

    @property
    def active_invoice(self):
        return self.invoices.exclude(status="cancelled").first()

    @property
    def is_final(self):
        return not self.order.milestones.filter(sequence__gt=self.sequence).exists()
