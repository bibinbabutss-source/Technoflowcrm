from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.activity import record
from core.middleware import get_current_user

from .models import Opportunity, OpportunityStage, OpportunityStageHistory

DEFAULT_STAGES = [
    # name, order, default probability, won, lost
    ("Initial Discussion", 10, 10, False, False),
    ("Requirements Gathering", 20, 20, False, False),
    ("Technical Assessment", 30, 30, False, False),
    ("Proposal Preparation", 40, 40, False, False),
    ("Proposal Submitted", 50, 50, False, False),
    ("Negotiation", 60, 70, False, False),
    ("Won", 70, 100, True, False),
    ("Lost", 80, 0, False, True),
]


def seed_stages():
    if OpportunityStage.objects.exists():
        return
    for name, order, prob, won, lost in DEFAULT_STAGES:
        OpportunityStage.objects.create(name=name, order=order, default_probability=prob, is_won=won, is_lost=lost)


@transaction.atomic
def change_stage(opp, stage, *, probability=None, lost_reason=None, lost_notes="", note=""):
    """
    Move an opportunity to another stage. Winning an opportunity does NOT create an order:
    orders only come from accepted, approved quotations confirmed by an authorised user.
    """
    if stage.pk == opp.stage_id and probability in (None, opp.probability):
        return opp
    if stage.is_lost and not lost_reason:
        raise ValidationError("A lost reason is required to mark an opportunity as Lost.")
    old = opp.stage
    opp.stage = stage
    opp.stage_changed_at = timezone.now()
    if stage.is_won:
        opp.probability = 100
    elif stage.is_lost:
        opp.probability = 0
    elif probability is not None:
        opp.probability = probability
    elif old.pk != stage.pk:
        opp.probability = stage.default_probability
    opp.lost_reason = lost_reason if stage.is_lost else None
    opp.lost_notes = lost_notes if stage.is_lost else ""
    opp.closed_at = timezone.now() if stage.is_closed else None
    opp.save()
    user = get_current_user()
    OpportunityStageHistory.objects.create(
        opportunity=opp, from_stage=old, to_stage=stage, probability=opp.probability,
        estimated_value=opp.estimated_value, changed_by=user if user and user.is_authenticated else None, note=note)
    record(opp, "status", f"Stage: {old} → {stage} ({opp.probability}%)" +
           (f", lost: {lost_reason}" if stage.is_lost else ""))
    _sync_lead(opp, stage)
    return opp


def _sync_lead(opp, stage):
    """When the opportunity is won or lost, the lead it came from follows."""
    if not opp.lead_id or not stage.is_closed:
        return
    from leads.models import LeadStage
    from leads.services import change_stage as lead_change

    target = LeadStage.objects.filter(is_won=stage.is_won, is_lost=stage.is_lost).first()
    if target and opp.lead.stage_id != target.pk:
        lead_change(opp.lead, target, lost_reason=opp.lost_reason, lost_notes=opp.lost_notes,
                    note=f"From opportunity {opp.code}")


def record_creation(opp):
    user = get_current_user()
    OpportunityStageHistory.objects.create(
        opportunity=opp, from_stage=None, to_stage=opp.stage, probability=opp.probability,
        estimated_value=opp.estimated_value, changed_by=user if user and user.is_authenticated else None,
        note="Created")


def create_from_order(order, *, name=None, project_manager=None):
    from .models import Project

    project = Project.objects.create(
        name=name or (order.quotation.opportunity.title if order.quotation and order.quotation.opportunity_id
                      else f"Project for {order.number}"),
        customer=order.customer, opportunity=order.opportunity, sales_order=order,
        project_manager=project_manager or order.assigned_to, start_date=timezone.localdate(),
        status="planned", location=getattr(order.opportunity, "location", "") if order.opportunity_id else "",
        project_type=getattr(order.opportunity, "project_type", None) if order.opportunity_id else None)
    record(project, "created", f"Delivery project created from order {order.number}", customer=order.customer)
    return project


def forecast_by_month(qs, months=12):
    """Open pipeline by expected closing month: count, value and weighted value."""
    from collections import OrderedDict
    from decimal import Decimal

    from .models import weighted

    today = timezone.localdate().replace(day=1)
    buckets = OrderedDict()
    overdue = {"label": "Overdue (date passed)", "count": 0, "value": Decimal(0), "weighted": Decimal(0)}
    undated = {"label": "No closing date", "count": 0, "value": Decimal(0), "weighted": Decimal(0)}
    for i in range(months):
        y, m = divmod(today.month - 1 + i, 12)
        key = (today.year + y, m + 1)
        buckets[key] = {"label": timezone.datetime(key[0], key[1], 1).strftime("%b %Y"), "count": 0,
                        "value": Decimal(0), "weighted": Decimal(0), "year": key[0], "month": key[1]}
    later = {"label": "Later", "count": 0, "value": Decimal(0), "weighted": Decimal(0)}
    for o in qs.filter(stage__is_won=False, stage__is_lost=False):
        d = o.expected_close_date
        if d is None:
            b = undated
        elif d < timezone.localdate():
            b = overdue
        else:
            b = buckets.get((d.year, d.month), later)
        b["count"] += 1
        b["value"] += o.estimated_value
        b["weighted"] += weighted(o.estimated_value, o.probability)
    rows = [overdue] + list(buckets.values()) + [later, undated]
    return [r for r in rows if r["count"] or "year" in r]


__all__ = ["change_stage", "seed_stages", "record_creation", "create_from_order", "forecast_by_month", "Opportunity"]
