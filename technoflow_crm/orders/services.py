"""
Workflow D (quotation → order):

  Accepted quotation → Create sales order (Draft, figures copied, nothing re-typed)
  → Authorised confirmation (Sales Director / Administrator) → Notify Accounts → Track status → Invoicing.

An order is never confirmed without the customer's acceptance and an authorised user.
"""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import has_capability
from core.activity import record
from core.audit import log_action
from core.money import LineInput, calculate, split_by_percentages

from .models import PaymentMilestone, SalesOrder, SalesOrderLine

MILESTONE_PRESETS = {
    "100": [("Full payment", 100)],
    "50-50": [("Advance", 50), ("Final", 50)],
    "30-40-30": [("Advance", 30), ("Progress", 40), ("Final", 30)],
    "30-70": [("Advance", 30), ("On delivery", 70)],
}


@transaction.atomic
def create_from_quotation(quotation, *, user, order_date=None, preset="100", customer_po_ref="",
                          delivery_details="", notes=""):
    from quotations.models import Quotation, QuotationRevision

    quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
    rev = quotation.revisions.get(version=quotation.current_version)
    if rev.status != QuotationRevision.Status.ACCEPTED:
        raise ValidationError("A sales order can only be created from a quotation the customer has accepted.")
    if rev.orders.exclude(status=SalesOrder.Status.CANCELLED).exists():
        raise ValidationError("An order already exists for this quotation revision.")
    lines = list(rev.lines.select_related("tax_rate"))
    totals = calculate([LineInput(ln.quantity, ln.unit_price, ln.discount_pct, ln.tax_rate_value) for ln in lines],
                       rev.header_discount)
    if totals.grand_total != rev.grand_total:
        raise ValidationError("The quotation totals do not match its lines. Contact the administrator.")
    order = SalesOrder.objects.create(
        customer=quotation.customer, quotation=quotation, revision=rev, opportunity=quotation.opportunity,
        order_date=order_date or timezone.localdate(), currency=rev.currency, net_amount=rev.taxable_amount,
        tax_amount=rev.tax_amount, total_amount=rev.grand_total, assigned_to=quotation.salesperson,
        customer_po_ref=customer_po_ref or rev.customer_reference, delivery_details=delivery_details,
        payment_terms=rev.payment_terms, notes=notes)
    for i, (ln, res) in enumerate(zip(lines, totals.lines), start=1):
        SalesOrderLine.objects.create(order=order, position=i, description=ln.description, quantity=ln.quantity,
                                      unit=ln.unit, unit_price=ln.unit_price, discount_pct=ln.discount_pct,
                                      tax_rate=ln.tax_rate, tax_rate_value=ln.tax_rate_value, line_net=res.net,
                                      line_taxable=res.taxable, line_tax=res.tax)
    set_milestones(order, MILESTONE_PRESETS.get(preset, MILESTONE_PRESETS["100"]))
    record(order, "order", f"Sales order created from {quotation.number} Rev {rev.version} (awaiting confirmation)",
           customer=order.customer)
    record(quotation, "order", f"Sales order {order.number} created")
    _notify_confirmers(order, user)
    return order


def _notify_confirmers(order, user):
    from django.contrib.auth import get_user_model

    from notifications.services import notify

    users = get_user_model().objects.filter(is_active=True, profile__role__capabilities__code="orders.confirm") \
        .exclude(pk=user.pk).distinct()
    notify(list(users), "order_to_confirm", f"Order awaiting confirmation: {order.number}",
           f"{order.customer.company_name} · {order.currency} {order.net_amount:,.2f} excl. VAT",
           order.get_absolute_url())


def set_milestones(order, items):
    """items: [(name, percentage), ...] summing to 100. Amounts split exactly (last takes the remainder)."""
    pcts = [Decimal(str(p)) for _, p in items]
    if sum(pcts) != Decimal(100):
        raise ValidationError(f"Milestone percentages must add up to 100% (they add up to {sum(pcts)}%).")
    if any(m.active_invoice for m in order.milestones.all()):
        raise ValidationError("Milestones cannot be changed after invoicing has started.")
    order.milestones.all().delete()
    amounts = split_by_percentages(order.total_amount, pcts)
    for i, ((name, pct), amount) in enumerate(zip(items, amounts), start=1):
        PaymentMilestone.objects.create(order=order, sequence=i, name=name, percentage=Decimal(str(pct)),
                                        amount=amount)


@transaction.atomic
def confirm(order, user):
    from notifications.services import notify

    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    if not has_capability(user, "orders.confirm"):
        raise PermissionDenied("You are not allowed to confirm orders.")
    if order.status != SalesOrder.Status.DRAFT:
        raise ValidationError("Only a draft order can be confirmed.")
    if order.revision.status != "accepted":
        raise ValidationError("The quotation revision is no longer accepted; the order cannot be confirmed.")
    total_pct = sum((m.percentage for m in order.milestones.all()), Decimal(0))
    if total_pct != Decimal(100):
        raise ValidationError("Set the payment milestones (100% in total) before confirming.")
    order.status = SalesOrder.Status.CONFIRMED
    order.confirmed_at = timezone.now()
    order.confirmed_by = user
    order.save()
    record(order, "order", f"Order confirmed by {user.get_full_name()}", customer=order.customer)
    log_action("approve", order, message=f"Order confirmed ({order.currency} {order.net_amount:,.2f} excl. VAT)")
    _win_opportunity(order)
    from django.contrib.auth import get_user_model

    accounts = list(get_user_model().objects.filter(is_active=True, profile__role__capabilities__code="invoices.manage")
                    .distinct())
    notify([u for u in accounts + [order.assigned_to] if u != user], "order_confirmed",
           f"Order confirmed: {order.number}",
           f"{order.customer.company_name} · ready for invoicing", order.get_absolute_url())
    return order


def _win_opportunity(order):
    """A confirmed order means the opportunity is won (recorded in its stage history)."""
    if not order.opportunity_id:
        return
    from sales.models import OpportunityStage
    from sales.services import change_stage

    opp = order.opportunity
    won = OpportunityStage.objects.filter(is_won=True).first()
    if won and opp.stage_id != won.pk and not opp.stage.is_lost:
        change_stage(opp, won, note=f"Order {order.number} confirmed")


@transaction.atomic
def cancel(order, user, reason):
    order = SalesOrder.objects.select_for_update().get(pk=order.pk)
    if not has_capability(user, "orders.confirm"):
        raise PermissionDenied("You are not allowed to cancel orders.")
    if order.status in (SalesOrder.Status.CANCELLED, SalesOrder.Status.COMPLETED):
        raise ValidationError("This order cannot be cancelled.")
    if order.invoices.exclude(status__in=["draft", "cancelled"]).exists():
        raise ValidationError("This order has issued invoices. Accounts must cancel them before the order "
                              "can be cancelled.")
    if not (reason or "").strip():
        raise ValidationError("Give the reason for cancelling.")
    order.invoices.filter(status="draft").delete()
    order.status = SalesOrder.Status.CANCELLED
    order.cancelled_at = timezone.now()
    order.cancelled_by = user
    order.cancel_reason = reason
    order.save()
    record(order, "order", f"Order cancelled: {reason}", customer=order.customer)
    log_action("other", order, message=f"Order cancelled: {reason}")
    return order


PROGRESS_FLOW = {
    "confirmed": ["in_progress", "partially_completed", "completed"],
    "in_progress": ["partially_completed", "completed"],
    "partially_completed": ["in_progress", "completed"],
    "completed": ["in_progress"],
}


def set_progress(order, status, user, note=""):
    allowed = PROGRESS_FLOW.get(order.status, [])
    if status not in allowed:
        raise ValidationError(f"An order that is {order.get_status_display().lower()} cannot move to that status.")
    old = order.get_status_display()
    order.status = status
    order.save(update_fields=["status", "updated_at", "updated_by"])
    record(order, "status", f"Status: {old} → {order.get_status_display()}" + (f" ({note})" if note else ""),
           customer=order.customer)
    return order
