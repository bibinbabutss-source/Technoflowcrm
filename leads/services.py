"""Lead business rules: stage changes, assignment, duplicate checks and conversion."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.activity import record
from core.middleware import get_current_user
from customers.models import Customer, normalize_name, normalize_phone

from .models import Lead, LeadAssignment, LeadStage, LeadStageHistory

DEFAULT_STAGES = [
    # name, order, qualified, won, lost
    ("New", 10, False, False, False),
    ("Contacted", 20, False, False, False),
    ("Qualification", 30, False, False, False),
    ("Qualified", 40, True, False, False),
    ("Proposal in Preparation", 50, True, False, False),
    ("Proposal Submitted", 60, True, False, False),
    ("Negotiation", 70, True, False, False),
    ("Won", 80, True, True, False),
    ("Lost", 90, False, False, True),
]


def seed_stages():
    if LeadStage.objects.exists():
        return
    for name, order, qualified, won, lost in DEFAULT_STAGES:
        LeadStage.objects.create(name=name, order=order, is_qualified=qualified, is_won=won, is_lost=lost)


def notify_assignment(lead, previous_engineer=None, previous_coordinator=None):
    from notifications.services import notify

    user = get_current_user()
    targets = []
    if lead.assigned_engineer_id and lead.assigned_engineer_id != getattr(previous_engineer, "pk", None):
        targets.append(lead.assigned_engineer)
    if lead.assigned_coordinator_id and lead.assigned_coordinator_id != getattr(previous_coordinator, "pk", None):
        targets.append(lead.assigned_coordinator)
    targets = [t for t in targets if t != user]
    if targets:
        notify(targets, "lead_assigned", f"Lead assigned to you: {lead.title}",
               f"{lead.code} · {lead.company_name}", lead.get_absolute_url())


def record_assignment(lead, *, previous_engineer=None, previous_coordinator=None, note=""):
    if (lead.assigned_engineer_id == getattr(previous_engineer, "pk", None) and
            lead.assigned_coordinator_id == getattr(previous_coordinator, "pk", None)):
        return
    user = get_current_user()
    LeadAssignment.objects.create(lead=lead, engineer=lead.assigned_engineer, coordinator=lead.assigned_coordinator,
                                  assigned_by=user if user and user.is_authenticated else None, note=note)
    record(lead, "assigned", f"Assigned to {lead.assigned_engineer or '—'} (engineer) / "
                             f"{lead.assigned_coordinator or '—'} (coordinator)")
    notify_assignment(lead, previous_engineer, previous_coordinator)


@transaction.atomic
def change_stage(lead, stage, *, lost_reason=None, lost_notes="", note=""):
    if stage.pk == lead.stage_id:
        return lead
    if stage.is_lost and not lost_reason:
        raise ValidationError("A lost reason is required to mark a lead as Lost.")
    old = lead.stage
    lead.stage = stage
    lead.stage_changed_at = timezone.now()
    if stage.is_lost:
        lead.lost_reason = lost_reason
        lead.lost_notes = lost_notes
    else:
        lead.lost_reason = None
        lead.lost_notes = ""
    lead.save()
    user = get_current_user()
    LeadStageHistory.objects.create(lead=lead, from_stage=old, to_stage=stage,
                                    changed_by=user if user and user.is_authenticated else None, note=note)
    msg = f"Stage: {old} → {stage}"
    if stage.is_lost:
        msg += f" (reason: {lost_reason})"
    record(lead, "status", msg)
    return lead


def find_lead_duplicates(*, company_name="", email="", phone="", exclude_pk=None):
    """Open leads that look like the same enquiry."""
    name = normalize_name(company_name)
    cond = Q()
    if email:
        cond |= Q(email__iexact=email.strip())
    qs = Lead.objects.filter(is_archived=False).exclude(stage__is_lost=True).exclude(stage__is_won=True)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    matches = list(qs.filter(cond)) if cond else []
    digits = normalize_phone(phone)
    for lead in qs.exclude(pk__in=[m.pk for m in matches]).only("pk", "company_name", "phone", "code", "title"):
        if (name and normalize_name(lead.company_name) == name) or (
                len(digits) >= 7 and normalize_phone(lead.phone) == digits):
            matches.append(lead)
    return matches


@transaction.atomic
def convert(lead, *, customer=None, new_customer_data=None, opportunity_data=None, user=None):
    """
    Convert a qualified lead: link to an existing customer or create one (never both),
    and optionally create a sales opportunity. Runs in one transaction.
    """
    from sales.models import Opportunity, OpportunityStage

    lead = Lead.objects.select_for_update().get(pk=lead.pk)
    if lead.is_converted:
        raise ValidationError("This lead has already been converted.")
    if lead.stage.is_lost:
        raise ValidationError("A lost lead cannot be converted. Move it back to an open stage first.")
    if customer is None:
        if not new_customer_data:
            raise ValidationError("Choose an existing customer or enter the new customer's details.")
        customer = Customer(**new_customer_data)
        customer.save()
        record(customer, "created", f"Customer created from lead {lead.code}")
    lead.customer = customer
    lead.converted_at = timezone.now()
    lead.converted_by = user
    if not lead.stage.is_qualified:
        qualified = LeadStage.objects.filter(is_qualified=True, is_won=False, is_lost=False,
                                             is_active=True).order_by("order").first()
        if qualified:
            change_stage(lead, qualified, note="Converted")
    lead.save()
    opportunity = None
    if opportunity_data:
        opportunity = Opportunity(customer=customer, lead=lead, assigned_engineer=lead.assigned_engineer,
                                  assigned_coordinator=lead.assigned_coordinator, source=lead.source,
                                  stage=OpportunityStage.first_open(), **opportunity_data)
        opportunity.save()
        record(opportunity, "created", f"Opportunity created from lead {lead.code}")
    record(lead, "converted", f"Converted to customer {customer.code}" +
           (f" and opportunity {opportunity.code}" if opportunity else ""), customer=customer)
    return customer, opportunity
