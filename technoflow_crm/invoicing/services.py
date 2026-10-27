"""
Workflow E (order → collection):

  Confirmed order → Prepare invoice (Draft) → Review and issue (number assigned, locked)
  → Record payment → Allocate to invoices → Outstanding recalculated → Paid when fully settled.

Rules
- Outstanding Balance = Invoice Total − Allocated Payments (net of reversals).
- An invoice is Paid only when allocations cover its total, not merely because a payment exists.
- Payments and allocations are never edited or deleted; a wrong payment is reversed by an equal,
  opposite entry, keeping both in the history.
- Every money operation runs in one database transaction with row locks.
"""
from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from core.activity import record
from core.audit import log_action
from core.models import CompanyProfile, NumberSequence
from core.money import ZERO, LineInput, calculate, q2

from .models import Invoice, InvoiceLine, Payment, PaymentAllocation

I = Invoice.Status


# ------------------------------------------------------------------ invoices
def _issued_invoices(order, exclude_pk=None):
    qs = order.invoices.exclude(status__in=[I.CANCELLED])
    return qs.exclude(pk=exclude_pk) if exclude_pk else qs


@transaction.atomic
def create_from_milestone(milestone, user):
    """Prepare a draft invoice for one payment milestone, pro rata to the order lines."""
    from orders.models import PaymentMilestone, SalesOrder

    milestone = PaymentMilestone.objects.select_for_update().select_related("order").get(pk=milestone.pk)
    order = SalesOrder.objects.select_for_update().get(pk=milestone.order_id)
    if not order.is_booked:
        raise ValidationError("Only confirmed orders can be invoiced.")
    if milestone.active_invoice:
        raise ValidationError("This milestone already has an invoice.")
    company = CompanyProfile.get()
    pct = milestone.percentage
    final = milestone.is_final
    invoice = Invoice.objects.create(
        customer=order.customer, order=order, milestone=milestone, invoice_date=timezone.localdate(),
        due_date=milestone.due_date or timezone.localdate() + timezone.timedelta(days=company.default_payment_terms_days),
        payment_terms=f"{company.default_payment_terms_days} days", reference=order.customer_po_ref,
        currency=order.currency)
    position = 0
    for ol in order.lines.all():
        if final:
            # last milestone: whatever is left of each line, so the order is invoiced to the exact fils
            already = InvoiceLine.objects.filter(order_line=ol, invoice__milestone__isnull=False).exclude(
                invoice__status=I.CANCELLED).exclude(invoice=invoice).aggregate(t=Sum("line_net"))["t"] or ZERO
            share = ol.line_taxable - already
        else:
            share = q2(ol.line_taxable * pct / Decimal(100))
        if share == 0:
            continue
        position += 1
        InvoiceLine.objects.create(invoice=invoice, order_line=ol, position=position,
                                   description=f"{ol.description}\n{milestone.name} — {pct.normalize():f}% of "
                                               f"order {order.number}",
                                   quantity=Decimal(1), unit="Lot", unit_price=share, tax_rate=ol.tax_rate)
    recalculate(invoice)
    record(invoice, "invoice", f"Draft invoice prepared for {milestone.name} ({pct.normalize():f}%) of "
                               f"{order.number}: {invoice.currency} {invoice.total:,.2f}", customer=order.customer)
    return invoice


def recalculate(invoice):
    lines = list(invoice.lines.select_related("tax_rate"))
    totals = calculate([LineInput(ln.quantity, ln.unit_price, ln.discount_pct, ln.tax_rate.rate) for ln in lines])
    for ln, res in zip(lines, totals.lines):
        InvoiceLine.objects.filter(pk=ln.pk).update(tax_rate_value=ln.tax_rate.rate, line_net=res.net,
                                                    line_tax=res.tax)
    tax = totals.tax
    # For the final milestone of an order, VAT is the order's VAT minus what earlier invoices charged,
    # so the invoices of an order always add up exactly to the order total.
    if invoice.milestone_id and invoice.milestone.is_final and all(ln.order_line_id for ln in lines):
        previous_tax = _issued_invoices(invoice.order, exclude_pk=invoice.pk).filter(
            milestone__isnull=False).aggregate(t=Sum("tax_amount"))["t"] or ZERO
        tax = invoice.order.tax_amount - previous_tax
    invoice.subtotal = totals.subtotal
    invoice.tax_amount = tax
    invoice.total = totals.subtotal + tax
    invoice.save(update_fields=["subtotal", "tax_amount", "total", "updated_at", "updated_by"])
    return invoice


def tax_breakdown(invoice):
    rows = defaultdict(lambda: {"base": ZERO, "tax": ZERO})
    for ln in invoice.lines.all():
        rows[ln.tax_rate_value]["base"] += ln.line_net
        rows[ln.tax_rate_value]["tax"] += ln.line_tax
    return dict(rows)


@transaction.atomic
def issue(invoice, user):
    from orders.models import SalesOrder

    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status != I.DRAFT:
        raise ValidationError("Only a draft invoice can be issued.")
    if not invoice.lines.exists() or invoice.total <= 0:
        raise ValidationError("The invoice has no amount to issue.")
    if invoice.due_date < invoice.invoice_date:
        raise ValidationError("The due date cannot be before the invoice date.")
    order = SalesOrder.objects.select_for_update().get(pk=invoice.order_id)
    if not order.is_booked:
        raise ValidationError("The order is not confirmed (or was cancelled).")
    recalculate(invoice)
    invoice.refresh_from_db()
    already = order.invoices.exclude(status__in=[I.DRAFT, I.CANCELLED]).aggregate(t=Sum("total"))["t"] or ZERO
    if already + invoice.total > order.total_amount:
        raise ValidationError(
            f"Issuing this invoice would bill {order.currency} {already + invoice.total:,.2f}, more than the order "
            f"total {order.currency} {order.total_amount:,.2f}.")
    invoice.number = NumberSequence.next_value("invoice")
    invoice.status = I.ISSUED
    invoice.issued_at = timezone.now()
    invoice.issued_by = user
    Invoice.objects.filter(pk=invoice.pk).update(number=invoice.number, status=invoice.status,
                                                 issued_at=invoice.issued_at, issued_by=user)
    record(invoice, "invoice", f"Invoice {invoice.number} issued: {invoice.currency} {invoice.total:,.2f}, "
                               f"due {invoice.due_date:%d-%b-%Y}", customer=invoice.customer)
    log_action("other", invoice, message=f"Invoice issued ({invoice.currency} {invoice.total:,.2f})")
    return invoice


@transaction.atomic
def cancel(invoice, user, reason):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if not (reason or "").strip():
        raise ValidationError("Give the reason for cancelling the invoice.")
    if invoice.status == I.CANCELLED:
        raise ValidationError("The invoice is already cancelled.")
    if invoice.status == I.DRAFT:
        raise ValidationError("A draft invoice can simply be deleted.")
    if invoice.amount_paid != 0:
        raise ValidationError("Payments are allocated to this invoice. Reverse those payments first.")
    Invoice.objects.filter(pk=invoice.pk).update(status=I.CANCELLED, cancelled_at=timezone.now(), cancelled_by=user,
                                                 cancel_reason=reason)
    record(invoice, "invoice", f"Invoice {invoice.number} cancelled: {reason} (number kept, not reused)",
           customer=invoice.customer)
    log_action("other", invoice, message=f"Invoice cancelled: {reason}")
    return invoice


def refresh_payment_status(invoice):
    """Outstanding = total − allocations. Status follows the money, never the other way round."""
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    paid = invoice.allocations.aggregate(t=Sum("amount"))["t"] or ZERO
    if invoice.status in (I.DRAFT, I.CANCELLED):
        return invoice
    if paid > invoice.total:
        raise ValidationError(f"Allocations ({paid:,.2f}) would exceed the invoice total ({invoice.total:,.2f}).")
    if paid < 0:
        raise ValidationError("Allocations cannot be negative in total.")
    status = I.PAID if paid == invoice.total else I.PARTIALLY_PAID if paid > 0 else I.ISSUED
    Invoice.objects.filter(pk=invoice.pk).update(amount_paid=paid, status=status)
    invoice.amount_paid, invoice.status = paid, status
    return invoice


# ------------------------------------------------------------------ payments
@transaction.atomic
def record_payment(*, customer, payment_date, amount, method, reference="", notes="", allocations=(), user=None,
                   currency=None):
    """
    allocations: [(invoice, amount), ...]. Each allocation must not exceed the invoice's outstanding balance,
    and their sum must not exceed the payment amount. Any remainder stays as unallocated credit.
    """
    amount = q2(amount)
    if amount <= 0:
        raise ValidationError("The payment amount must be greater than zero.")
    if payment_date > timezone.localdate():
        raise ValidationError("The payment date cannot be in the future.")
    payment = Payment.objects.create(number=NumberSequence.next_value("payment"), customer=customer,
                                     payment_date=payment_date, amount=amount,
                                     currency=currency or CompanyProfile.get().default_currency, method=method,
                                     reference=reference, notes=notes)
    total = ZERO
    for invoice, alloc in allocations:
        alloc = q2(alloc)
        if alloc == 0:
            continue
        total += alloc
        if total > amount:
            raise ValidationError("The allocations add up to more than the payment amount.")
        _allocate(payment, invoice, alloc, user)
    record(payment, "payment", f"Payment {payment.number} received: {payment.currency} {amount:,.2f} "
                               f"({payment.get_method_display()}{', ref ' + reference if reference else ''})",
           customer=customer)
    log_action("create", payment, message=f"Payment recorded {payment.currency} {amount:,.2f}")
    return payment


def _allocate(payment, invoice, amount, user):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.customer_id != payment.customer_id:
        raise ValidationError(f"Invoice {invoice.display_number} belongs to another customer.")
    if invoice.status not in Invoice.OPEN_STATUSES:
        raise ValidationError(f"Invoice {invoice.display_number} is not open for payment.")
    if amount <= 0:
        raise ValidationError("Allocation amounts must be positive.")
    if amount > invoice.outstanding:
        raise ValidationError(f"{amount:,.2f} is more than the outstanding balance of {invoice.display_number} "
                              f"({invoice.outstanding:,.2f}).")
    PaymentAllocation.objects.create(payment=payment, invoice=invoice, amount=amount, created_by=user)
    invoice = refresh_payment_status(invoice)
    record(invoice, "payment", f"{payment.currency} {amount:,.2f} allocated from {payment.number}; outstanding "
                               f"{invoice.outstanding:,.2f}", customer=invoice.customer)


@transaction.atomic
def allocate(payment, invoice, amount, user):
    """Allocate unallocated credit of an existing payment."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    amount = q2(amount)
    if payment.is_reversal or payment.is_reversed:
        raise ValidationError("A reversed payment cannot be allocated.")
    if amount > payment.unallocated:
        raise ValidationError(f"Only {payment.unallocated:,.2f} of {payment.number} is unallocated.")
    _allocate(payment, invoice, amount, user)
    return payment


@transaction.atomic
def reverse(payment, user, reason):
    """Undo a wrong payment with an equal and opposite entry. The original stays in the history."""
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if not (reason or "").strip():
        raise ValidationError("Give the reason for the reversal.")
    if payment.is_reversal:
        raise ValidationError("A reversal entry cannot itself be reversed.")
    if payment.is_reversed:
        raise ValidationError("This payment has already been reversed.")
    rev = Payment.objects.create(number=NumberSequence.next_value("payment"), customer=payment.customer,
                                 payment_date=timezone.localdate(), amount=-payment.amount, currency=payment.currency,
                                 method=payment.method, reference=payment.reference,
                                 notes=f"Reversal of {payment.number}", is_reversal=True, reverses=payment,
                                 reversal_reason=reason)
    for alloc in payment.allocations.select_related("invoice"):
        invoice = Invoice.objects.select_for_update().get(pk=alloc.invoice_id)
        PaymentAllocation.objects.create(payment=rev, invoice=invoice, amount=-alloc.amount, created_by=user)
        invoice = refresh_payment_status(invoice)
        record(invoice, "payment", f"{alloc.amount:,.2f} from {payment.number} reversed ({reason}); outstanding "
                                   f"{invoice.outstanding:,.2f}", customer=invoice.customer)
    record(payment, "payment", f"Payment {payment.number} reversed by {rev.number}: {reason}",
           customer=payment.customer)
    log_action("other", payment, message=f"Payment reversed by {rev.number}: {reason}")
    return rev


# ------------------------------------------------------------------ statement of account
def statement(customer, start, end):
    """
    Opening balance + invoices issued − payments received (net of reversals) = closing balance.
    Only issued (non-draft) invoices count; cancelled invoices are excluded.
    """
    invoices = Invoice.objects.filter(customer=customer).exclude(status__in=[I.DRAFT, I.CANCELLED])
    payments = Payment.objects.filter(customer=customer)
    opening = (invoices.filter(invoice_date__lt=start).aggregate(t=Sum("total"))["t"] or ZERO) - \
              (payments.filter(payment_date__lt=start).aggregate(t=Sum("amount"))["t"] or ZERO)
    entries = []
    for inv in invoices.filter(invoice_date__gte=start, invoice_date__lte=end):
        entries.append({"date": inv.invoice_date, "kind": "Invoice", "ref": inv.number, "obj": inv,
                        "detail": f"Due {inv.due_date:%d-%b-%Y}" + (f" · PO {inv.reference}" if inv.reference else ""),
                        "debit": inv.total, "credit": ZERO})
    for p in payments.filter(payment_date__gte=start, payment_date__lte=end):
        if p.amount >= 0:
            entries.append({"date": p.payment_date, "kind": "Payment", "ref": p.number, "obj": p,
                            "detail": f"{p.get_method_display()}" + (f" · {p.reference}" if p.reference else ""),
                            "debit": ZERO, "credit": p.amount})
        else:
            entries.append({"date": p.payment_date, "kind": "Reversal", "ref": p.number, "obj": p,
                            "detail": p.notes, "debit": -p.amount, "credit": ZERO})
    entries.sort(key=lambda e: (e["date"], 0 if e["kind"] == "Invoice" else 1, e["ref"]))
    balance = opening
    for e in entries:
        balance += e["debit"] - e["credit"]
        e["balance"] = balance
    total_debit = sum((e["debit"] for e in entries), ZERO)
    total_credit = sum((e["credit"] for e in entries), ZERO)
    open_items = [inv for inv in invoices.filter(status__in=Invoice.OPEN_STATUSES).order_by("due_date")
                  if inv.invoice_date <= end]
    unallocated = sum((p.unallocated for p in payments.filter(is_reversal=False) if not p.is_reversed), ZERO)
    return {"opening": opening, "entries": entries, "closing": balance, "total_debit": total_debit,
            "total_credit": total_credit, "open_items": open_items, "unallocated": unallocated}


AGEING_BUCKETS = [("Not yet due", None, 0), ("1–30 days", 1, 30), ("31–60 days", 31, 60),
                  ("61–90 days", 61, 90), ("Over 90 days", 91, None)]


def ageing(invoices):
    """Group open invoices by days past due."""
    buckets = [{"label": label, "count": 0, "amount": ZERO} for label, _, _ in AGEING_BUCKETS]
    today = timezone.localdate()
    for inv in invoices:
        if inv.outstanding <= 0:
            continue
        days = (today - inv.due_date).days
        for b, (_, lo, hi) in zip(buckets, AGEING_BUCKETS):
            if (lo is None and days <= 0) or (lo is not None and days >= lo and (hi is None or days <= hi)):
                b["count"] += 1
                b["amount"] += inv.outstanding
                break
    return buckets
