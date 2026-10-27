"""Role-based dashboard: cards, charts (Chart.js) and work lists, all computed by reporting.metrics."""
import datetime

from django.urls import reverse
from django.utils import timezone

from accounts.permissions import get_profile, has_capability, visible_user_ids
from core.crud import money

from . import metrics


def _q(url_name, **params):
    from urllib.parse import urlencode

    return reverse(url_name) + ("?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})
                                if params else "")


def cards_for(user, f, start, end, employee_id=None):
    """Cards shown to this user's role. Each links to the list behind the number (drill-down)."""
    role = get_profile(user).role.code
    d = {"date_from": start.isoformat(), "date_to": end.isoformat()}
    emp = employee_id or ""
    collection_rate = (f["collected"] / f["invoiced"] * 100) if f["invoiced"] else None
    C = {
        "pipeline": ("Pipeline value", money(f["pipeline_value"]), f"{f['open_opportunities']} open opportunities",
                     _q("sales:pipeline", state="open", employee=emp), "pipeline.view"),
        "weighted": ("Weighted forecast", money(f["weighted_forecast"]), "value × closing probability",
                     _q("sales:forecast", employee=emp), "pipeline.view"),
        "approvals": ("Quotations awaiting approval", f["quotations_pending"], "submitted for approval",
                      _q("quotations:list", status="submitted"), "quotations.view"),
        "sent": ("Quotations with customers", f["quotations_sent"], money(f["quotations_sent_value"]),
                 _q("quotations:list", status="sent"), "quotations.view"),
        "booked": ("Orders booked", money(f["orders_value"]), f"{f['orders_confirmed']} confirmed, excl. VAT",
                   _q("orders:list", status="booked", confirmed_from=d["date_from"], confirmed_to=d["date_to"],
                      employee=emp), "orders.view"),
        "invoiced": ("Invoiced", money(f["invoiced"]), "issued invoices, incl. VAT",
                     _q("invoicing:list", date_from=d["date_from"], date_to=d["date_to"]), "invoices.view"),
        "collected": ("Collected", money(f["collected"]), "payments received in the period",
                      _q("invoicing:payments", date_from=d["date_from"], date_to=d["date_to"]), "collections.view"),
        "outstanding": ("Outstanding receivables", money(f["outstanding"]), "unpaid balance of issued invoices",
                        _q("invoicing:list", status="open"), "invoices.view"),
        "overdue": ("Overdue invoices", f["overdue_count"], money(f["overdue_amount"]),
                    _q("invoicing:list", status="overdue"), "invoices.view"),
        "collection_rate": ("Collection rate", f"{collection_rate:.1f}%" if collection_rate is not None else "—",
                            "collected ÷ invoiced in the period", _q("invoicing:collections"), "collections.view"),
        "draft_invoices": ("Draft invoices", f["invoices_draft"], "prepared, not yet issued",
                           _q("invoicing:list", status="draft"), "invoices.manage"),
        "draft_orders": ("Orders to confirm", f["draft_orders"], "created from accepted quotations",
                         _q("orders:list", status="draft"), "orders.view"),
        "customers": ("Customers", f["customers"], f"{f['new_customers']} new in the period",
                      _q("customers:list", employee=emp), "customers.view"),
        "leads": ("Leads", f["leads"], f"{f['new_leads']} new · {f['qualified_leads']} qualified open",
                  _q("leads:list", state="open", employee=emp), "leads.view"),
        "conversion": ("Lead conversion", f"{f['lead_conversion']}%" if f["lead_conversion"] is not None else "—",
                       "won ÷ closed leads in the period", _q("leads:list", state="won"), "leads.view"),
        "visits": ("Upcoming visits", f["upcoming_visits"], "next 7 days",
                   _q("visits:list", state="upcoming", employee=emp), "visits.view"),
        "followups": ("Overdue follow-ups", f["overdue_followups"], f"incl. {f['overdue_tasks']} overdue tasks",
                      _q("tasks:list", show="team", state="overdue"), "tasks.view"),
        "projects": ("Projects in progress", f["projects_in_progress"], "planned or in progress",
                     _q("sales:projects", status="in_progress"), "projects.view"),
    }
    layout = {
        "ADMIN": ["pipeline", "weighted", "approvals", "booked", "invoiced", "collected", "outstanding", "overdue"],
        "DIRECTOR": ["pipeline", "weighted", "approvals", "booked", "invoiced", "collected", "outstanding",
                     "conversion"],
        "ACCOUNTS": ["invoiced", "collected", "outstanding", "overdue", "collection_rate", "draft_invoices",
                     "draft_orders", "customers"],
        "ENGINEER": ["leads", "pipeline", "weighted", "approvals", "booked", "visits", "followups", "conversion"],
        "COORDINATOR": ["leads", "visits", "followups", "sent", "approvals", "draft_orders", "customers", "projects"],
    }.get(role, ["customers", "leads", "visits", "followups"])
    out = []
    for key in layout:
        label, value, sub, url, cap = C[key]
        if has_capability(user, cap):
            out.append({"key": key, "label": label, "value": value, "sub": sub, "url": url})
    return out


def charts_for(user):
    role = get_profile(user).role.code
    charts = []
    if has_capability(user, "orders.view") or has_capability(user, "invoices.view"):
        charts.append(("monthly", "Orders booked, invoiced and collected by month"))
    if has_capability(user, "pipeline.view"):
        charts.append(("pipeline", "Open pipeline by stage"))
    if has_capability(user, "leads.view"):
        charts.append(("funnel", "Lead conversion funnel (leads created in the period)"))
    if has_capability(user, "quotations.view"):
        charts.append(("quotations", "Quotation value issued by month"))
    if has_capability(user, "invoices.view") and role in ("ADMIN", "DIRECTOR", "ACCOUNTS"):
        charts.append(("ageing", "Outstanding receivables by age"))
    if has_capability(user, "targets.view"):
        charts.append(("targets", "Target vs achievement (this month)"))
    if has_capability(user, "team.view"):
        charts.append(("employees", "Performance by employee in the period"))
    return charts[:6]


def chart_data(user, key, start, end, employee_id=None):
    if key == "monthly":
        s = metrics.monthly_sales(user, employee_id)
        links = [_q("orders:list", status="booked", confirmed_from=a, confirmed_to=b) for a, b in _months(s)]
        return {"type": "bar", "labels": s["labels"], "links": links, "datasets": [
            {"label": "Orders booked (excl. VAT)", "data": [float(x) for x in s["booked"]]},
            {"label": "Invoiced", "data": [float(x) for x in s["invoiced"]]},
            {"label": "Collected", "data": [float(x) for x in s["collected"]]}]}
    if key == "quotations":
        s = metrics.monthly_sales(user, employee_id)
        return {"type": "line", "labels": s["labels"], "datasets": [
            {"label": "Quotations issued", "data": [float(x) for x in s["quoted"]]}],
            "links": [_q("quotations:list", sent_from=a, sent_to=b) for a, b in _months(s)]}
    if key == "pipeline":
        rows = metrics.pipeline_by_stage(user, employee_id)
        return {"type": "bar", "labels": [r["stage"].name for r in rows],
                "links": [_q("sales:pipeline", stage=r["stage"].pk, employee=employee_id or "") for r in rows],
                "datasets": [{"label": "Value", "data": [float(r["value"]) for r in rows]},
                             {"label": "Weighted", "data": [float(r["weighted"]) for r in rows]}]}
    if key == "funnel":
        rows = metrics.lead_funnel(user, start, end, employee_id)
        return {"type": "bar", "horizontal": True, "labels": [r["stage"].name for r in rows],
                "links": [_q("leads:list", stage=r["stage"].pk) for r in rows],
                "datasets": [{"label": "Leads reaching this stage", "data": [r["count"] for r in rows]}]}
    if key == "ageing":
        rows = metrics.receivables_ageing(user, employee_id)
        return {"type": "bar", "labels": [r["label"] for r in rows],
                "links": [_q("invoicing:collections") for _ in rows],
                "datasets": [{"label": "Outstanding", "data": [float(r["amount"]) for r in rows]}]}
    if key == "targets":
        from performance.services import scorecard

        subject = None if has_capability(user, "team.view") and not employee_id else (
            _user(employee_id) if employee_id else user)
        card = scorecard(subject, "month", timezone.localdate(), compare=False)
        rows = [r for r in card["rows"] if r["target"] is not None]
        return {"type": "bar", "labels": [r["kpi"].name for r in rows], "percent": True,
                "links": [reverse("performance:overview") for _ in rows],
                "datasets": [{"label": "Achievement %", "data": [float(r["pct"] or 0) for r in rows]}],
                "empty": "No targets set for this month." if not rows else ""}
    if key == "employees":
        rows = metrics.employee_performance(user, start, end)
        return {"type": "bar", "labels": [r["user"].get_full_name() for r in rows],
                "links": [_q("orders:list", employee=r["user"].pk) for r in rows],
                "datasets": [{"label": "Quotations issued", "data": [float(r["quoted"]) for r in rows]},
                             {"label": "Orders booked", "data": [float(r["booked"]) for r in rows]},
                             {"label": "Invoiced", "data": [float(r["invoiced"]) for r in rows]},
                             {"label": "Collected", "data": [float(r["collected"]) for r in rows]}]}
    return None


def _months(series):
    out = []
    for m in series["months"]:
        first = datetime.date(int(m[:4]), int(m[5:]), 1)
        out.append((first.isoformat(), metrics.month_range(first)[1].isoformat()))
    return out


def _user(pk):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(pk=pk).first()


def work_lists(user):
    """Short lists of things needing action (top 5 each), respecting scope."""
    from accounts.permissions import scope_queryset
    from core.scopes import owners
    from quotations.models import Quotation
    from tasks.models import Task
    from visits.models import Visit

    today = timezone.localdate()
    lists = []
    if has_capability(user, "quotations.approve"):
        qs = scope_queryset(Quotation.objects.filter(status="submitted"), user, owners("quotations.quotation")) \
            .exclude(salesperson=user).select_related("customer")[:5]
        lists.append(("Quotations awaiting your approval", [(q.display_number, f"{q.customer.company_name} · "
                                                            f"{money(q.grand_total, q.currency)}",
                                                            q.get_absolute_url()) for q in qs],
                      _q("quotations:list", status="submitted")))
    if has_capability(user, "tasks.view"):
        tasks = Task.objects.filter(assigned_to=user, status__in=Task.OPEN_STATUSES, due_date__lte=today +
                                    datetime.timedelta(days=2)).order_by("due_date")[:5]
        lists.append(("Your tasks due soon or overdue", [(t.title, f"{'Overdue' if t.is_overdue else 'Due'} "
                                                          f"{t.due_date:%d-%b}", t.get_absolute_url()) for t in tasks],
                      _q("tasks:list", show="mine", state="open")))
    if has_capability(user, "visits.view"):
        ids = visible_user_ids(user)
        vqs = Visit.objects.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__gte=today).select_related(
            "customer").order_by("visit_date", "start_time")
        if ids is not None:
            vqs = vqs.filter(assigned_to__in=ids)
        lists.append(("Upcoming visits", [(v.customer.company_name, f"{v.visit_date:%a %d-%b} {v.start_time:%H:%M}",
                                           v.get_absolute_url()) for v in vqs[:5]], _q("visits:schedule")))
    if has_capability(user, "invoices.manage"):
        from invoicing.models import Invoice

        inv = [i for i in Invoice.objects.filter(status__in=Invoice.OPEN_STATUSES, due_date__lt=today)
               .select_related("customer").order_by("due_date")[:5]]
        lists.append(("Overdue invoices", [(i.number, f"{i.customer.company_name} · {money(i.outstanding)}",
                                            i.get_absolute_url()) for i in inv], _q("invoicing:list",
                                                                                     status="overdue")))
    return lists[:4]
