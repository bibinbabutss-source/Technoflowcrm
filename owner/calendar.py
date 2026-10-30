"""
Team calendar: one place to see employees' visits, meetings, follow-ups, tasks and deadlines.

Privacy: each viewer sees only employees inside their data scope (Owner / Director: everyone; Coordinator: their
team; Sales Engineer: themselves) - the same rule as every other list. Every event links to the record's own page,
which checks access again.

Status (shown with colour AND text):
    completed  done / visit completed              upcoming  later than today, not done
    pending    due today, not done                 overdue   date passed, not done
"""
import datetime

from django.utils import timezone

from accounts.permissions import has_capability, visible_user_ids
from core.crud import person

TYPES = [("visit", "Customer visits"), ("meeting", "Meetings (logged in Communication History)"), ("follow_up", "Follow-ups"), ("task", "Tasks"),
         ("deadline", "Deadlines (closing dates, quotation expiry)")]
STATUS_TONE = {"completed": "good", "upcoming": "info", "pending": "warn", "overdue": "bad", "cancelled": "neutral"}
STATUS_LABEL = {"completed": "Completed", "upcoming": "Upcoming", "pending": "Due today", "overdue": "Overdue",
                "cancelled": "Cancelled"}


def _status(date, done, today):
    if done:
        return "completed"
    if date < today:
        return "overdue"
    if date == today:
        return "pending"
    return "upcoming"


def _ids_filter(qs, field, ids):
    return qs if ids is None else qs.filter(**{f"{field}__in": ids})


def events(user, start, end, employee_ids=None, types=None):
    """All calendar events between start and end (dates), for employees the user may see."""
    from leads.models import Lead
    from quotations.models import Quotation
    from sales.models import Opportunity
    from tasks.models import Task
    from visits.models import Visit

    today = timezone.localdate()
    allowed = visible_user_ids(user)
    ids = allowed
    if employee_ids:
        ids = set(employee_ids) if allowed is None else set(employee_ids) & allowed
    types = set(types or [t for t, _ in TYPES])
    out = []

    if "visit" in types and has_capability(user, "visits.view"):
        qs = _ids_filter(Visit.objects.filter(visit_date__gte=start, visit_date__lte=end), "assigned_to_id", ids)
        for v in qs.select_related("customer", "assigned_to", "purpose"):
            st = "cancelled" if v.status == "cancelled" else _status(v.visit_date, v.status == "completed", today)
            out.append({"date": v.visit_date, "time": v.start_time, "type": "visit", "status": st,
                        "title": f"{v.start_time:%H:%M} {v.customer.company_name}", "employee": v.assigned_to,
                        "detail": str(v.purpose or "Customer visit"), "url": v.get_absolute_url()})

    if "meeting" in types and has_capability(user, "communications.view"):
        from communications.models import Communication

        qs = Communication.objects.filter(kind="meeting", occurred_at__date__gte=start, occurred_at__date__lte=end)
        for c in _ids_filter(qs, "employee_id", ids).select_related("employee", "customer"):
            when = timezone.localtime(c.occurred_at)
            out.append({"date": when.date(), "time": when.time(), "type": "meeting",
                        "status": "completed" if when.date() <= today else "upcoming",
                        "title": f"{when:%H:%M} Meeting: {c.customer.company_name}", "employee": c.employee,
                        "detail": c.subject or "Customer meeting", "url": c.get_absolute_url()})

    if ({"follow_up", "task"} & types) and has_capability(user, "tasks.view"):
        qs = _ids_filter(Task.objects.filter(due_date__gte=start, due_date__lte=end), "assigned_to_id", ids)
        for t in qs.select_related("assigned_to", "customer"):
            kind = "follow_up" if t.category == "follow_up" else "task"
            if kind not in types:
                continue
            st = "cancelled" if t.status == "cancelled" else _status(t.due_date, t.status == "completed", today)
            out.append({"date": t.due_date, "time": None, "type": kind, "status": st, "title": t.title,
                        "employee": t.assigned_to, "detail": str(t.customer or t.get_category_display()),
                        "url": t.get_absolute_url()})

    if "follow_up" in types and has_capability(user, "leads.view"):
        qs = Lead.objects.filter(next_follow_up__gte=start, next_follow_up__lte=end, is_archived=False,
                                 stage__is_won=False, stage__is_lost=False)
        qs = _ids_filter(qs, "assigned_engineer_id", ids)
        for lead in qs.select_related("assigned_engineer"):
            out.append({"date": lead.next_follow_up, "time": None, "type": "follow_up",
                        "status": _status(lead.next_follow_up, False, today),
                        "title": f"Lead follow-up: {lead.company_name}", "employee": lead.assigned_engineer,
                        "detail": f"{lead.code} {lead.title}", "url": lead.get_absolute_url()})

    if "deadline" in types:
        if has_capability(user, "pipeline.view"):
            qs = Opportunity.objects.filter(expected_close_date__gte=start, expected_close_date__lte=end,
                                            is_archived=False)
            qs = _ids_filter(qs, "assigned_engineer_id", ids)
            for o in qs.select_related("assigned_engineer", "stage"):
                st = "completed" if o.stage.is_closed else _status(o.expected_close_date, False, today)
                out.append({"date": o.expected_close_date, "time": None, "type": "deadline", "status": st,
                            "title": f"Expected close: {o.title}", "employee": o.assigned_engineer,
                            "detail": f"{o.code} · {o.stage}", "url": o.get_absolute_url()})
        if has_capability(user, "quotations.view"):
            qs = Quotation.objects.filter(expiry_date__gte=start, expiry_date__lte=end,
                                          status__in=("approved", "sent"))
            qs = _ids_filter(qs, "salesperson_id", ids)
            for q in qs.select_related("salesperson", "customer"):
                out.append({"date": q.expiry_date, "time": None, "type": "deadline",
                            "status": _status(q.expiry_date, False, today),
                            "title": f"Quotation expires: {q.number}", "employee": q.salesperson,
                            "detail": q.customer.company_name, "url": q.get_absolute_url()})

    for ev in out:
        ev["tone"] = STATUS_TONE[ev["status"]]
        ev["status_label"] = STATUS_LABEL[ev["status"]]
        ev["type_label"] = dict(TYPES).get(ev["type"], ev["type"])
        ev["who"] = person(ev["employee"])
    out.sort(key=lambda e: (e["date"], e["time"] or datetime.time(23, 59), e["who"]))
    return out


