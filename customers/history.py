"""
Company history: everything that happened in sales with one customer, in order —
leads, meetings (before and after the sales pipeline), visits, opportunities, quotations, and the activity log.
Each part follows the user's own permissions and data scope (the same getters as the customer page).
"""
from collections import defaultdict
from decimal import Decimal

from accounts.permissions import has_capability
from core import activity
from core.registry import customer_sections


def _scoped(customer, user, key):
    for s in customer_sections:
        if s["key"] == key:
            if not has_capability(user, s["capability"]):
                return None
            return s["getter"](customer, user)
    return None


def company_history(customer, user):
    leads = _scoped(customer, user, "leads")
    opps = _scoped(customer, user, "opportunities")
    meetings = _scoped(customer, user, "meetings")
    visits = _scoped(customer, user, "visits")
    quotes = _scoped(customer, user, "quotations")

    leads = list(leads.select_related("assigned_engineer").order_by("created_at")) if leads is not None else None
    opps = list(opps.select_related("assigned_engineer", "lead").order_by("created_at")) if opps is not None else None
    meetings = list(meetings.order_by("meeting_date", "start_time", "pk")) if meetings is not None else None
    visits = list(visits.order_by("visit_date")) if visits is not None else None
    quotes = list(quotes.order_by("created_at")) if quotes is not None else None

    meetings_by_lead, meetings_by_opp = defaultdict(list), defaultdict(list)
    for m in meetings or []:
        if m.opportunity_id:
            meetings_by_opp[m.opportunity_id].append(m)
        elif m.lead_id:
            meetings_by_lead[m.lead_id].append(m)
    quotes_by_opp, quotes_by_lead = defaultdict(list), defaultdict(list)
    for q in quotes or []:
        if q.opportunity_id:
            quotes_by_opp[q.opportunity_id].append(q)
        elif q.lead_id:
            quotes_by_lead[q.lead_id].append(q)

    def opp_entry(o):
        own = meetings_by_opp.get(o.pk, [])
        before = [m for m in meetings_by_lead.get(o.lead_id, []) if not m.in_pipeline] if o.lead_id else []
        after_lead = [m for m in meetings_by_lead.get(o.lead_id, []) if m.in_pipeline] if o.lead_id else []
        return {"opp": o, "meetings": own + after_lead, "quotations": quotes_by_opp.get(o.pk, []),
                "meetings_before": len(before), "meetings_total": len(before) + len(own) + len(after_lead)}

    opps_by_lead = defaultdict(list)
    for o in opps or []:
        opps_by_lead[o.lead_id].append(o)
    journeys = []
    for lead in leads or []:
        lead_meetings = meetings_by_lead.get(lead.pk, [])
        journeys.append({
            "lead": lead,
            "meetings_before": [m for m in lead_meetings if not m.in_pipeline],
            "opportunities": [opp_entry(o) for o in opps_by_lead.get(lead.pk, [])],
            "quotations": quotes_by_lead.get(lead.pk, []),
            "date": lead.created_at,
        })
    lead_ids = {lead.pk for lead in leads or []}
    for o in opps or []:
        if o.lead_id is None or o.lead_id not in lead_ids:  # opportunities opened directly, or lead out of scope
            journeys.append({"lead": None, "meetings_before": [], "opportunities": [opp_entry(o)],
                             "quotations": [], "date": o.created_at})
    journeys.sort(key=lambda j: j["date"], reverse=True)

    won = [o for o in opps or [] if o.stage.is_won]
    summary = {
        "leads": len(leads) if leads is not None else None,
        "leads_in_pipeline": sum(1 for lead in leads or [] if lead.converted_at),
        "meetings": len(meetings) if meetings is not None else None,
        "meetings_before": sum(1 for m in meetings or [] if not m.in_pipeline),
        "meetings_in_pipeline": sum(1 for m in meetings or [] if m.in_pipeline),
        "visits": len(visits) if visits is not None else None,
        "visits_done": sum(1 for v in visits or [] if v.status == "completed"),
        "opportunities": len(opps) if opps is not None else None,
        "opps_open": sum(1 for o in opps or [] if not o.stage.is_won and not o.stage.is_lost),
        "opps_won": len(won),
        "opps_lost": sum(1 for o in opps or [] if o.stage.is_lost),
        "won_value": sum((o.estimated_value or Decimal(0) for o in won), Decimal(0)),
        "quotations": len(quotes) if quotes is not None else None,
        "revisions": sum(max(q.current_version, 1) for q in quotes or []),
    }
    # meetings it took to win: for each won opportunity, the meetings on it and on its lead before the win
    summary["meetings_per_win"] = (round(sum(opp_entry(o)["meetings_total"] for o in won) / len(won), 1)
                                   if won else None)
    first_dates = [d for d in [leads[0].created_at if leads else None, opps[0].created_at if opps else None] if d]
    summary["first_contact"] = min(first_dates) if first_dates else customer.created_at

    return {
        "summary": summary, "journeys": journeys,
        "meetings": list(reversed(meetings or [])) if meetings is not None else None,
        "visits": list(reversed(visits or [])) if visits is not None else None,
        "activities": activity.for_customer(customer, user)[:200],
    }
