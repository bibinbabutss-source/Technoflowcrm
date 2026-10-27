"""
The single calculation layer for dashboards, reports and KPIs (Phase 1 plan, section 8).

Every figure shown anywhere in the CRM comes from these functions, so the dashboard, a report and
a KPI scorecard can never disagree. Nothing here is typed in or stored: it is computed from records.

Four sales measures are kept separate and never combined:
    quotations issued  — grand total of quotation revisions sent to customers, by sent date
    orders booked      — confirmed orders, value excluding VAT, by confirmation date
    invoiced           — issued (non-cancelled) invoices, total including VAT, by invoice date
    collected          — payments received net of reversals, by payment date

Scope: `ids` is the set of employee user ids whose records the viewer may see (None = everyone).
"""
import datetime
from collections import OrderedDict
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from accounts.permissions import visible_user_ids

ZERO = Decimal("0.00")


# ------------------------------------------------------------------ scope helpers
def people_ids(viewer, employee_id=None):
    """Ids the viewer may see, optionally narrowed to one employee (ignored if not visible)."""
    ids = visible_user_ids(viewer)
    if employee_id:
        if ids is None or employee_id in ids:
            return {employee_id}
        return ids
    return ids


def by_people(qs, fields, ids):
    if ids is None:
        return qs
    cond = Q()
    for f in fields:
        cond |= Q(**{f"{f}__in": ids})
    return qs.filter(cond).distinct()


def _sum(qs, field):
    return qs.aggregate(t=Sum(field))["t"] or ZERO


def month_range(d):
    start = d.replace(day=1)
    end = (start + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
    return start, end


def last_months(n=12, end=None):
    end = end or timezone.localdate()
    months = []
    y, m = end.year, end.month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(months))


def period_bounds(period_type, ref):
    if period_type == "month":
        return month_range(ref)
    if period_type == "quarter":
        q = (ref.month - 1) // 3
        start = datetime.date(ref.year, q * 3 + 1, 1)
        end = month_range(datetime.date(ref.year, q * 3 + 3, 1))[1]
        return start, end
    return datetime.date(ref.year, 1, 1), datetime.date(ref.year, 12, 31)


def previous_period(period_type, start):
    if period_type == "month":
        return period_bounds("month", start - datetime.timedelta(days=1))
    if period_type == "quarter":
        return period_bounds("quarter", start - datetime.timedelta(days=1))
    return period_bounds("year", datetime.date(start.year - 1, 6, 1))


# ------------------------------------------------------------------ querysets (one place each)
def customers_qs(ids):
    from customers.models import Customer

    return by_people(Customer.objects.filter(is_archived=False), ("assigned_engineer", "assigned_coordinator",
                                                                  "created_by"), ids)


def leads_qs(ids):
    from leads.models import Lead

    return by_people(Lead.objects.filter(is_archived=False), ("assigned_engineer", "assigned_coordinator",
                                                              "created_by"), ids)


def opportunities_qs(ids):
    from sales.models import Opportunity

    return by_people(Opportunity.objects.filter(is_archived=False), ("assigned_engineer", "assigned_coordinator",
                                                                     "created_by"), ids)


def open_opportunities_qs(ids):
    return opportunities_qs(ids).filter(stage__is_won=False, stage__is_lost=False)


def booked_orders_qs(ids, start=None, end=None):
    from orders.models import SalesOrder

    qs = by_people(SalesOrder.objects.filter(status__in=SalesOrder.BOOKED_STATUSES), ("assigned_to",), ids)
    if start:
        qs = qs.filter(confirmed_at__date__gte=start)
    if end:
        qs = qs.filter(confirmed_at__date__lte=end)
    return qs


def issued_invoices_qs(ids, start=None, end=None):
    from invoicing.models import Invoice

    qs = by_people(Invoice.objects.exclude(status__in=["draft", "cancelled"]), ("order__assigned_to",), ids)
    if start:
        qs = qs.filter(invoice_date__gte=start)
    if end:
        qs = qs.filter(invoice_date__lte=end)
    return qs


def collected(ids, start, end):
    """Money received in the period. For one employee: allocations to invoices of their orders."""
    from invoicing.models import Payment, PaymentAllocation

    if ids is None:
        return _sum(Payment.objects.filter(payment_date__gte=start, payment_date__lte=end), "amount")
    return _sum(PaymentAllocation.objects.filter(payment__payment_date__gte=start, payment__payment_date__lte=end,
                                                 invoice__order__assigned_to__in=ids), "amount")


def quotations_issued_qs(ids, start=None, end=None):
    from quotations.models import QuotationRevision

    qs = by_people(QuotationRevision.objects.filter(sent_at__isnull=False), ("quotation__salesperson",), ids)
    if start:
        qs = qs.filter(sent_at__date__gte=start)
    if end:
        qs = qs.filter(sent_at__date__lte=end)
    return qs


def open_invoices(ids):
    from invoicing.models import Invoice

    return list(by_people(Invoice.objects.filter(status__in=Invoice.OPEN_STATUSES), ("order__assigned_to",
                                                                                     "customer__assigned_engineer",
                                                                                     "customer__assigned_coordinator"),
                          ids).select_related("customer"))


# ------------------------------------------------------------------ KPI actuals (per employee or team)
KPI_CODES = [
    ("orders_booked", "Order booking value (excl. VAT)", "amount"),
    ("invoiced", "Invoiced amount", "amount"),
    ("collected", "Collections received", "amount"),
    ("quotations_value", "Quotation value issued", "amount"),
    ("leads_created", "Leads generated", "count"),
    ("visits_completed", "Customer visits completed", "count"),
    ("new_customers", "New customers acquired", "count"),
    ("opportunities_won", "Opportunities won", "count"),
    ("conversion_rate", "Lead conversion rate", "percent"),
    ("followup_completion", "Follow-ups completed on time", "percent"),
]
KPI_INFO = {code: (label, unit) for code, label, unit in KPI_CODES}


def kpi_actual(code, ids, start, end):
    """The actual value of a KPI for a set of employees (None = whole company) over a period."""
    from customers.models import Customer
    from leads.models import Lead
    from sales.models import Opportunity
    from tasks.models import Task
    from visits.models import Visit

    if code == "orders_booked":
        return _sum(booked_orders_qs(ids, start, end), "net_amount")
    if code == "invoiced":
        return _sum(issued_invoices_qs(ids, start, end), "total")
    if code == "collected":
        return collected(ids, start, end)
    if code == "quotations_value":
        return _sum(quotations_issued_qs(ids, start, end), "grand_total")
    if code == "leads_created":
        return Decimal(by_people(Lead.objects.filter(created_at__date__gte=start, created_at__date__lte=end),
                                 ("created_by",), ids).count())
    if code == "visits_completed":
        return Decimal(by_people(Visit.objects.filter(status="completed", visit_date__gte=start,
                                                      visit_date__lte=end), ("assigned_to",), ids).count())
    if code == "new_customers":
        return Decimal(by_people(Customer.objects.filter(created_at__date__gte=start, created_at__date__lte=end),
                                 ("assigned_engineer",), ids).count())
    if code == "opportunities_won":
        return Decimal(by_people(Opportunity.objects.filter(stage__is_won=True, closed_at__date__gte=start,
                                                            closed_at__date__lte=end), ("assigned_engineer",),
                                 ids).count())
    if code == "conversion_rate":
        closed = by_people(Lead.objects.filter(stage_changed_at__date__gte=start, stage_changed_at__date__lte=end)
                           .filter(Q(stage__is_won=True) | Q(stage__is_lost=True)), ("assigned_engineer",), ids)
        total = closed.count()
        if total == 0:
            return None
        return (Decimal(closed.filter(stage__is_won=True).count()) / Decimal(total) * 100).quantize(Decimal("0.1"))
    if code == "followup_completion":
        due = by_people(Task.objects.filter(due_date__gte=start, due_date__lte=end).exclude(status="cancelled"),
                        ("assigned_to",), ids)
        total = due.count()
        if total == 0:
            return None
        on_time = sum(1 for t in due.filter(status="completed") if t.completed_at and
                      timezone.localtime(t.completed_at).date() <= t.due_date)
        return (Decimal(on_time) / Decimal(total) * 100).quantize(Decimal("0.1"))
    raise ValueError(f"Unknown KPI {code}")


# ------------------------------------------------------------------ dashboard figures
def dashboard_figures(viewer, start, end, employee_id=None):
    from invoicing.models import Invoice
    from orders.models import SalesOrder
    from quotations.models import Quotation
    from sales.models import Project, weighted
    from tasks.models import Task
    from visits.models import Visit

    ids = people_ids(viewer, employee_id)
    today = timezone.localdate()
    open_opps = list(open_opportunities_qs(ids))
    invoices_open = open_invoices(ids)
    overdue = [i for i in invoices_open if i.is_overdue]
    leads = leads_qs(ids)
    quotes = by_people(Quotation.objects.all(), ("salesperson", "created_by", "customer__assigned_engineer",
                                                 "customer__assigned_coordinator"), ids)
    orders = booked_orders_qs(ids, start, end)
    f = OrderedDict()
    f["customers"] = customers_qs(ids).count()
    f["new_customers"] = customers_qs(ids).filter(created_at__date__gte=start, created_at__date__lte=end).count()
    f["leads"] = leads.count()
    f["new_leads"] = leads.filter(created_at__date__gte=start, created_at__date__lte=end).count()
    f["qualified_leads"] = leads.filter(stage__is_qualified=True, stage__is_won=False, stage__is_lost=False).count()
    f["open_opportunities"] = len(open_opps)
    f["pipeline_value"] = sum((o.estimated_value for o in open_opps), ZERO)
    f["weighted_forecast"] = sum((weighted(o.estimated_value, o.probability) for o in open_opps), ZERO)
    f["projects_in_progress"] = by_people(Project.objects.filter(status__in=["planned", "in_progress"]),
                                          ("project_manager", "created_by", "customer__assigned_engineer",
                                           "customer__assigned_coordinator"), ids).count()
    f["quotations_pending"] = quotes.filter(status="submitted").count()
    f["quotations_sent"] = quotes.filter(status="sent").count()
    f["quotations_sent_value"] = _sum(quotes.filter(status="sent"), "grand_total")
    f["orders_confirmed"] = orders.count()
    f["orders_value"] = _sum(orders, "net_amount")
    f["invoiced"] = _sum(issued_invoices_qs(ids, start, end), "total")
    f["collected"] = collected(ids, start, end)
    f["outstanding"] = sum((i.outstanding for i in invoices_open), ZERO)
    f["overdue_count"] = len(overdue)
    f["overdue_amount"] = sum((i.outstanding for i in overdue), ZERO)
    f["upcoming_visits"] = by_people(Visit.objects.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__gte=today,
                                                          visit_date__lte=today + datetime.timedelta(days=7)),
                                     ("assigned_to",), ids).count()
    overdue_tasks = by_people(Task.objects.filter(status__in=Task.OPEN_STATUSES, due_date__lt=today),
                              ("assigned_to",), ids).count()
    overdue_followups = leads.filter(next_follow_up__lt=today, stage__is_won=False, stage__is_lost=False).count() \
        + open_opportunities_qs(ids).filter(next_follow_up__lt=today).count()
    f["overdue_followups"] = overdue_followups + overdue_tasks
    f["overdue_tasks"] = overdue_tasks
    f["draft_orders"] = by_people(SalesOrder.objects.filter(status="draft"), ("assigned_to", "created_by"),
                                  ids).count()
    f["invoices_draft"] = by_people(Invoice.objects.filter(status="draft"), ("order__assigned_to", "created_by"),
                                    ids).count()
    f["lead_conversion"] = kpi_actual("conversion_rate", ids, start, end)
    return f


# ------------------------------------------------------------------ chart series
def monthly_sales(viewer, employee_id=None, months=12):
    ids = people_ids(viewer, employee_id)
    labels, booked, invoiced, collected_s, quoted = [], [], [], [], []
    for y, m in last_months(months):
        start, end = month_range(datetime.date(y, m, 1))
        labels.append(start.strftime("%b %Y"))
        booked.append(_sum(booked_orders_qs(ids, start, end), "net_amount"))
        invoiced.append(_sum(issued_invoices_qs(ids, start, end), "total"))
        collected_s.append(collected(ids, start, end))
        quoted.append(_sum(quotations_issued_qs(ids, start, end), "grand_total"))
    return {"labels": labels, "booked": booked, "invoiced": invoiced, "collected": collected_s, "quoted": quoted,
            "months": [f"{y}-{m:02d}" for y, m in last_months(months)]}


def lead_funnel(viewer, start, end, employee_id=None):
    """How many leads created in the period reached each stage (using stage history)."""
    from leads.models import LeadStage, LeadStageHistory

    ids = people_ids(viewer, employee_id)
    leads = list(leads_qs(ids).filter(created_at__date__gte=start, created_at__date__lte=end)
                 .select_related("stage"))
    stages = list(LeadStage.objects.filter(is_lost=False, is_active=True).order_by("order"))
    reached_order = {}
    for lead in leads:
        reached_order[lead.pk] = lead.stage.order if not lead.stage.is_lost else 0
    for h in LeadStageHistory.objects.filter(lead_id__in=reached_order.keys()).select_related("to_stage"):
        if not h.to_stage.is_lost:
            reached_order[h.lead_id] = max(reached_order[h.lead_id], h.to_stage.order)
    rows = []
    for s in stages:
        rows.append({"stage": s, "count": sum(1 for v in reached_order.values() if v >= s.order)})
    return rows


def pipeline_by_stage(viewer, employee_id=None):
    from sales.models import OpportunityStage, weighted

    ids = people_ids(viewer, employee_id)
    opps = list(open_opportunities_qs(ids))
    rows = []
    for s in OpportunityStage.objects.filter(is_won=False, is_lost=False, is_active=True):
        items = [o for o in opps if o.stage_id == s.pk]
        rows.append({"stage": s, "count": len(items), "value": sum((o.estimated_value for o in items), ZERO),
                     "weighted": sum((weighted(o.estimated_value, o.probability) for o in items), ZERO)})
    return rows


def employee_performance(viewer, start, end):
    """Per employee: quotations issued, orders booked, invoiced, collected (kept separate)."""
    from django.contrib.auth import get_user_model

    ids = visible_user_ids(viewer)
    User = get_user_model()
    users = User.objects.filter(profile__role__code__in=["ENGINEER", "DIRECTOR", "COORDINATOR"])
    if ids is not None:
        users = users.filter(pk__in=ids)
    rows = []
    for u in users.order_by("first_name"):
        one = {u.pk}
        rows.append({"user": u,
                     "quoted": _sum(quotations_issued_qs(one, start, end), "grand_total"),
                     "booked": _sum(booked_orders_qs(one, start, end), "net_amount"),
                     "invoiced": _sum(issued_invoices_qs(one, start, end), "total"),
                     "collected": collected(one, start, end),
                     "won": kpi_actual("opportunities_won", one, start, end),
                     "visits": kpi_actual("visits_completed", one, start, end)})
    return rows


def receivables_ageing(viewer, employee_id=None):
    from invoicing.services import ageing

    return ageing(open_invoices(people_ids(viewer, employee_id)))

