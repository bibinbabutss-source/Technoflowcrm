"""Rules for sales meetings: who may see them, and what a saved meeting updates."""
from django.db.models import Q

from accounts.permissions import visible_user_ids
from core.activity import record


def visible_meetings(user, qs):
    """Meetings of records inside the user's data scope (the same rule as leads / opportunities / customers)."""
    ids = visible_user_ids(user)
    if ids is None:
        return qs
    return qs.filter(Q(held_by_id__in=ids) | Q(created_by_id__in=ids) | Q(lead__assigned_engineer_id__in=ids)
                     | Q(lead__assigned_coordinator_id__in=ids) | Q(lead__created_by_id__in=ids)
                     | Q(opportunity__assigned_engineer_id__in=ids)
                     | Q(opportunity__assigned_coordinator_id__in=ids)
                     | Q(customer__assigned_engineer_id__in=ids) | Q(customer__assigned_coordinator_id__in=ids)
                     ).distinct()


def for_lead(lead):
    return lead.meetings.select_related("held_by", "lead", "opportunity").all()


def for_opportunity(opp):
    from .models import Meeting

    q = Q(opportunity=opp)
    if opp.lead_id:
        q |= Q(lead_id=opp.lead_id, opportunity__isnull=True)
    return Meeting.objects.filter(q).select_related("held_by", "lead", "opportunity")


def after_save(meeting, created):
    """Keep the lead / opportunity follow-up date and last-contact date in step with the latest meeting."""
    from .models import Meeting

    for parent in (meeting.lead, meeting.opportunity):
        if parent is None:
            continue
        latest = (Meeting.objects.filter(**{parent.__class__.__name__.lower(): parent})
                  .order_by("-meeting_date", "-pk").first())
        fields = []
        if latest and latest.pk == meeting.pk and meeting.next_follow_up:
            parent.next_follow_up = meeting.next_follow_up
            fields.append("next_follow_up")
        if hasattr(parent, "last_contact_date") and (parent.last_contact_date is None
                                                     or meeting.meeting_date > parent.last_contact_date):
            parent.last_contact_date = meeting.meeting_date
            fields.append("last_contact_date")
        if fields:
            parent.save(update_fields=fields + ["updated_at"])
    target = meeting.opportunity or meeting.lead or meeting.customer
    verb = "recorded" if created else "updated"
    record(target, "comment", f"Meeting {verb} ({meeting.meeting_date:%d-%b-%Y}, {meeting.get_meeting_type_display()}):"
                              f" {meeting.summary[:200]}", customer=meeting.customer)


def counts(lead=None, opportunity=None):
    """{'total', 'before_pipeline', 'in_pipeline'} for a lead or an opportunity."""
    if opportunity is not None:
        qs = for_opportunity(opportunity)
    elif lead is not None:
        qs = for_lead(lead)
    else:
        return {"total": 0, "before_pipeline": 0, "in_pipeline": 0}
    before = qs.filter(in_pipeline=False).count()
    total = qs.count()
    return {"total": total, "before_pipeline": before, "in_pipeline": total - before}


def annotate_lead_meetings(qs):
    """Lead list: number of meetings recorded on each lead."""
    from django.db.models import Count

    return qs.annotate(meeting_count=Count("meetings", distinct=True))


def annotate_opportunity_meetings(qs):
    """Opportunity list: meetings on the opportunity plus the meetings held on its lead before it."""
    from django.db.models import Count, IntegerField, OuterRef, Subquery
    from django.db.models.functions import Coalesce

    from .models import Meeting

    own = (Meeting.objects.filter(opportunity_id=OuterRef("pk")).order_by().values("opportunity_id")
           .annotate(c=Count("pk")).values("c"))
    on_lead = (Meeting.objects.filter(lead_id=OuterRef("lead_id"), opportunity__isnull=True).order_by()
               .values("lead_id").annotate(c=Count("pk")).values("c"))
    return qs.annotate(meeting_count=Coalesce(Subquery(own, output_field=IntegerField()), 0)
                       + Coalesce(Subquery(on_lead, output_field=IntegerField()), 0))


def with_permissions(meetings, user):
    """Mark each meeting with whether this user may edit it: a meeting on an opportunity needs pipeline.edit,
    a meeting on a lead needs leads.edit, and archived parents are read-only (same rules as the views)."""
    from accounts.permissions import has_capability

    lead_ok, opp_ok = has_capability(user, "leads.edit"), has_capability(user, "pipeline.edit")
    lead_del, opp_del = has_capability(user, "leads.archive"), has_capability(user, "pipeline.archive")
    out = list(meetings)
    for m in out:
        if m.opportunity_id:
            m.can_change = opp_ok and not m.opportunity.is_archived
            manager = opp_del
        else:
            m.can_change = lead_ok and m.lead_id is not None and not m.lead.is_archived
            manager = lead_del
        m.can_delete = m.can_change and (m.created_by_id == user.pk or manager)
    return out
