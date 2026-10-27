"""
Reports. Each report is a function returning headers, rows and totals; the framework adds filters
(date range, employee, customer, status), role-based access, scoping and CSV / Excel / PDF export.
All figures come from reporting.metrics or the same querysets, so reports match the dashboard.
"""
import datetime
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import has_capability, scope_queryset
from core.audit import log_action
from core.crud import employees_visible_to, money, person
from core.exports import csv_response, xlsx_response
from core.params import get_date, get_int
from core.pdf import pdf_response
from core.scopes import owners

from . import metrics

ZERO = Decimal("0.00")


@dataclass
class Ctx:
    user: object
    start: datetime.date
    end: datetime.date
    ids: object
    employee: object = None
    customer: object = None
    status: str = ""


@dataclass
class Result:
    headers: list
    rows: list
    totals: list = None
    note: str = ""
    money_cols: set = field(default_factory=set)


@dataclass
class Report:
    key: str
    group: str
    title: str
    description: str
    capability: str
    fn: object
    uses_dates: bool = True
    uses_employee: bool = True
    uses_customer: bool = False
    statuses: list = None

    def context(self, request):
        today = timezone.localdate()
        start = get_date(request.GET, "start") or today.replace(month=1, day=1)
        end = get_date(request.GET, "end") or today
        if end < start:
            start, end = end, start
        emp = get_int(request.GET, "employee")
        ids = metrics.people_ids(request.user, emp)
        customer = None
        cid = get_int(request.GET, "customer")
        if cid and self.uses_customer:
            from customers.models import Customer

            customer = scope_queryset(Customer.objects.all(), request.user, owners("customers.customer")) \
                .filter(pk=cid).first()
        status = request.GET.get("status", "")
        if self.statuses and status not in dict(self.statuses):
            status = ""
        return Ctx(user=request.user, start=start, end=end, ids=ids, employee=emp, customer=customer, status=status)

    def respond(self, request):
        ctx = self.context(request)
        result = self.fn(ctx)
        fmt = request.GET.get("export")
        subtitle = (f"{ctx.start:%d-%b-%Y} to {ctx.end:%d-%b-%Y}" if self.uses_dates else
                    f"As at {timezone.localdate():%d-%b-%Y}")
        if fmt in ("csv", "xlsx", "pdf"):
            if not has_capability(request.user, "data.export") and fmt != "pdf":
                from django.core.exceptions import PermissionDenied

                raise PermissionDenied
            log_action("export", message=f"Report '{self.title}' exported to {fmt.upper()} ({len(result.rows)} rows)")
            plain_rows = [[_plain(v) for v in r] for r in result.rows]
            totals = [_plain(v) for v in result.totals] if result.totals else None
            if fmt == "csv":
                rows = plain_rows + ([totals] if totals else [])
                return csv_response(f"report_{self.key}", result.headers, rows)
            if fmt == "xlsx":
                return xlsx_response(f"report_{self.key}", result.headers, plain_rows, title=self.title,
                                     subtitle=subtitle, totals=totals)
            return pdf_response("reporting/report_pdf.html", {
                "report": self, "result": result, "subtitle": subtitle, "user": request.user,
                "rows": [[_pdf(v, i in result.money_cols) for i, v in enumerate(r)] for r in plain_rows],
                "totals": [_pdf(v, i in result.money_cols) for i, v in enumerate(totals)] if totals else None},
                                f"report_{self.key}")
        from customers.models import Customer

        customers = scope_queryset(Customer.objects.all(), request.user, owners("customers.customer")) \
            .order_by("company_name") if self.uses_customer else []
        return render(request, "reporting/report.html", {
            "report": self, "result": result, "ctx": ctx, "subtitle": subtitle,
            "employees": employees_visible_to(request.user) if self.uses_employee else [],
            "customers": customers,
            "rows_html": [[_html(v, i in result.money_cols) for i, v in enumerate(r)] for r in result.rows],
            "totals_html": [_html(v, i in result.money_cols) for i, v in enumerate(result.totals)]
            if result.totals else None,
            "can_export": has_capability(request.user, "data.export"),
        })


def _plain(v):
    if isinstance(v, tuple) and len(v) == 2:  # (text, url)
        return v[0]
    if hasattr(v, "get_full_name"):
        return person(v)
    return v


def _pdf(v, is_money=False):
    if isinstance(v, Decimal) and is_money:
        return money(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        from core.crud import fmt_date

        return fmt_date(v)
    return "—" if v is None else v


def _html(v, is_money=False):
    from django.utils.html import format_html

    if isinstance(v, tuple) and len(v) == 2:
        return format_html('<a href="{}">{}</a>', v[1], v[0])
    if hasattr(v, "get_full_name"):
        return person(v)
    if isinstance(v, Decimal) and is_money:
        return money(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        from core.crud import fmt_date

        return fmt_date(v)
    if v is None:
        return "—"
    return v


def link(obj, text=None):
    return (text or str(obj), obj.get_absolute_url())


def pct(a, b):
    return (Decimal(a) / Decimal(b) * 100).quantize(Decimal("0.1")) if b else None


# ====================================================================== querysets
def _customers(ctx):
    from customers.models import Customer

    qs = metrics.by_people(Customer.objects.all(), owners("customers.customer"), ctx.ids)
    return qs.select_related("category", "assigned_engineer")


def _leads(ctx):
    from leads.models import Lead

    return metrics.by_people(Lead.objects.filter(is_archived=False), owners("leads.lead"), ctx.ids) \
        .select_related("stage", "source", "assigned_engineer", "lost_reason")


def _opps(ctx):
    from sales.models import Opportunity

    return metrics.by_people(Opportunity.objects.filter(is_archived=False), owners("sales.opportunity"), ctx.ids) \
        .select_related("stage", "customer", "assigned_engineer", "lost_reason")


def _visits(ctx):
    from visits.models import Visit

    return metrics.by_people(Visit.objects.all(), ("assigned_to",), ctx.ids).select_related(
        "customer", "assigned_to", "purpose")


def _quotes(ctx):
    from quotations.models import Quotation

    return metrics.by_people(Quotation.objects.all(), ("salesperson", "created_by"), ctx.ids).select_related(
        "customer", "salesperson")


def _invoices(ctx):
    from invoicing.models import Invoice

    qs = metrics.by_people(Invoice.objects.exclude(status__in=["draft", "cancelled"]),
                           ("order__assigned_to", "customer__assigned_engineer", "customer__assigned_coordinator"),
                           ctx.ids).select_related("customer", "order")
    return qs.filter(customer=ctx.customer) if ctx.customer else qs


# ====================================================================== customer reports
def r_customer_list(ctx):
    qs = _customers(ctx).filter(is_archived=False).order_by("company_name")
    if ctx.customer:
        qs = qs.filter(pk=ctx.customer.pk)
    rows = [[link(c, c.code), c.company_name, c.category or "", c.get_status_display(), c.contact_person, c.phone,
             c.email, c.city, c.assigned_engineer, c.created_at.date(), c.last_contact_date] for c in qs]
    return Result(["ID", "Company", "Category", "Status", "Contact", "Phone", "Email", "City", "Sales Engineer",
                   "Created", "Last contact"], rows, note=f"{len(rows)} customers")


def r_customers_by_category(ctx):
    qs = _customers(ctx).filter(is_archived=False)
    counts = Counter(str(c.category or "Uncategorised") for c in qs)
    status = defaultdict(Counter)
    for c in qs:
        status[str(c.category or "Uncategorised")][c.status] += 1
    rows = [[cat, n, status[cat]["active"], status[cat]["prospect"], status[cat]["inactive"] + status[cat]["on_hold"]]
            for cat, n in counts.most_common()]
    return Result(["Category", "Customers", "Active", "Prospect", "Inactive / on hold"], rows,
                  totals=["Total", sum(counts.values()), "", "", ""])


def r_new_customers(ctx):
    qs = _customers(ctx).filter(created_at__date__gte=ctx.start, created_at__date__lte=ctx.end).order_by("created_at")
    rows = [[c.created_at.date(), link(c, c.code), c.company_name, c.category or "", c.source or "",
             c.assigned_engineer] for c in qs]
    return Result(["Created", "ID", "Company", "Category", "Source", "Sales Engineer"], rows,
                  totals=["Total", len(rows), "", "", "", ""])


def r_inactive_customers(ctx):
    cutoff = timezone.localdate() - datetime.timedelta(days=90)
    qs = _customers(ctx).filter(is_archived=False).filter(Q(last_contact_date__lt=cutoff) |
                                                          Q(last_contact_date__isnull=True)).order_by(
        "last_contact_date")
    rows = [[link(c, c.code), c.company_name, c.get_status_display(), c.assigned_engineer, c.last_contact_date,
             (timezone.localdate() - c.last_contact_date).days if c.last_contact_date else None] for c in qs]
    return Result(["ID", "Company", "Status", "Sales Engineer", "Last contact", "Days since contact"], rows,
                  note="Customers with no recorded contact (visit or communication) in the last 90 days.")


def r_interactions(ctx):
    from communications.models import Communication
    from visits.models import Visit

    customers = _customers(ctx).filter(is_archived=False)
    if ctx.customer:
        customers = customers.filter(pk=ctx.customer.pk)
    comm = Communication.objects.filter(occurred_at__date__gte=ctx.start, occurred_at__date__lte=ctx.end) \
        .values("customer").annotate(n=Count("pk"))
    comm = {r["customer"]: r["n"] for r in comm}
    vis = Visit.objects.filter(status="completed", visit_date__gte=ctx.start, visit_date__lte=ctx.end) \
        .values("customer").annotate(n=Count("pk"))
    vis = {r["customer"]: r["n"] for r in vis}
    rows = [[link(c, c.company_name), c.assigned_engineer, vis.get(c.pk, 0), comm.get(c.pk, 0),
             vis.get(c.pk, 0) + comm.get(c.pk, 0), c.last_contact_date] for c in customers]
    rows.sort(key=lambda r: -r[4])
    return Result(["Customer", "Sales Engineer", "Visits completed", "Communications", "Total interactions",
                   "Last contact"], rows, totals=["Total", "", sum(r[2] for r in rows), sum(r[3] for r in rows),
                                                  sum(r[4] for r in rows), ""])


# ====================================================================== lead reports
def _leads_period(ctx):
    return _leads(ctx).filter(created_at__date__gte=ctx.start, created_at__date__lte=ctx.end)


def _lead_group(ctx, keyfn, label):
    groups = OrderedDict()
    for lead in _leads_period(ctx):
        k = keyfn(lead)
        g = groups.setdefault(k, {"n": 0, "open": 0, "won": 0, "lost": 0, "value": ZERO})
        g["n"] += 1
        g["value"] += lead.estimated_value
        if lead.stage.is_won:
            g["won"] += 1
        elif lead.stage.is_lost:
            g["lost"] += 1
        else:
            g["open"] += 1
    rows = [[k, g["n"], g["open"], g["won"], g["lost"], pct(g["won"], g["won"] + g["lost"]), g["value"]]
            for k, g in sorted(groups.items(), key=lambda kv: -kv[1]["n"])]
    t = [sum(r[i] for r in rows) for i in (1, 2, 3, 4)]
    return Result([label, "Leads", "Open", "Won", "Lost", "Conversion %", "Estimated value"], rows,
                  totals=["Total", *t, pct(t[2], t[2] + t[3]), sum((r[6] for r in rows), ZERO)], money_cols={6},
                  note="Leads created in the period. Conversion % = won ÷ (won + lost).")


def r_leads_by_source(ctx):
    return _lead_group(ctx, lambda lead: str(lead.source or "Not recorded"), "Source")


def r_leads_by_owner(ctx):
    return _lead_group(ctx, lambda lead: person(lead.assigned_engineer) if lead.assigned_engineer else "Unassigned",
                       "Sales Engineer")


def r_leads_by_stage(ctx):
    from leads.models import LeadStage

    qs = _leads_period(ctx)
    rows = []
    for s in LeadStage.objects.all():
        items = [x for x in qs if x.stage_id == s.pk]
        rows.append([(s.name, reverse("leads:list") + f"?stage={s.pk}"), len(items),
                     sum((x.estimated_value for x in items), ZERO)])
    return Result(["Stage", "Leads", "Estimated value"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO)], money_cols={2})


def r_lead_conversion(ctx):
    res = _lead_group(ctx, lambda lead: lead.created_at.strftime("%Y-%m"), "Month created")
    res.rows.sort(key=lambda r: r[0])
    return res


def r_lost_leads(ctx):
    qs = _leads(ctx).filter(stage__is_lost=True, stage_changed_at__date__gte=ctx.start,
                            stage_changed_at__date__lte=ctx.end)
    by_reason = Counter(str(x.lost_reason or "Not recorded") for x in qs)
    value = defaultdict(lambda: ZERO)
    for x in qs:
        value[str(x.lost_reason or "Not recorded")] += x.estimated_value
    rows = [[r, n, value[r]] for r, n in by_reason.most_common()]
    return Result(["Lost reason", "Leads lost", "Estimated value lost"], rows,
                  totals=["Total", sum(by_reason.values()), sum(value.values(), ZERO)], money_cols={2},
                  note="Leads moved to Lost in the period.")


# ====================================================================== sales reports
def r_pipeline(ctx):
    rows = []
    for r in metrics.pipeline_by_stage(ctx.user, ctx.employee):
        rows.append([(r["stage"].name, reverse("sales:pipeline") + f"?stage={r['stage'].pk}"), r["count"],
                     r["value"], r["weighted"]])
    return Result(["Stage", "Opportunities", "Value", "Weighted forecast"], rows,
                  totals=["Total open pipeline", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO),
                          sum((r[3] for r in rows), ZERO)], money_cols={2, 3}, note="Open opportunities as of today.")


def r_sales_by_employee(ctx):
    rows = [[r["user"], r["quoted"], r["booked"], r["invoiced"], r["collected"], r["won"], r["visits"]]
            for r in metrics.employee_performance(ctx.user, ctx.start, ctx.end)
            if ctx.employee is None or r["user"].pk == ctx.employee]
    return Result(["Employee", "Quotations issued", "Orders booked (excl. VAT)", "Invoiced", "Collected",
                   "Opportunities won", "Visits completed"], rows,
                  totals=["Total"] + [sum((r[i] for r in rows), ZERO) for i in (1, 2, 3, 4)] +
                  [sum((r[i] or 0 for r in rows), ZERO) for i in (5, 6)], money_cols={1, 2, 3, 4},
                  note="Four separate measures, never added together.")


def r_sales_by_customer(ctx):
    orders = metrics.booked_orders_qs(ctx.ids, ctx.start, ctx.end).select_related("customer")
    if ctx.customer:
        orders = orders.filter(customer=ctx.customer)
    agg = defaultdict(lambda: {"n": 0, "v": ZERO})
    names = {}
    for o in orders:
        agg[o.customer_id]["n"] += 1
        agg[o.customer_id]["v"] += o.net_amount
        names[o.customer_id] = o.customer
    rows = [[link(names[k], names[k].company_name), a["n"], a["v"]] for k, a in sorted(agg.items(),
                                                                                       key=lambda kv: -kv[1]["v"])]
    return Result(["Customer", "Orders", "Booked (excl. VAT)"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO)], money_cols={2})


def r_sales_by_period(ctx):
    rows = []
    d = ctx.start.replace(day=1)
    while d <= ctx.end:
        s, e = metrics.month_range(d)
        s, e = max(s, ctx.start), min(e, ctx.end)
        rows.append([d.strftime("%b %Y"), metrics._sum(metrics.quotations_issued_qs(ctx.ids, s, e), "grand_total"),
                     metrics._sum(metrics.booked_orders_qs(ctx.ids, s, e), "net_amount"),
                     metrics._sum(metrics.issued_invoices_qs(ctx.ids, s, e), "total"),
                     metrics.collected(ctx.ids, s, e)])
        d = (d + datetime.timedelta(days=32)).replace(day=1)
    return Result(["Month", "Quotations issued", "Orders booked (excl. VAT)", "Invoiced", "Collected"], rows,
                  totals=["Total"] + [sum((r[i] for r in rows), ZERO) for i in (1, 2, 3, 4)], money_cols={1, 2, 3, 4})


def r_won_lost(ctx):
    qs = _opps(ctx).filter(closed_at__date__gte=ctx.start, closed_at__date__lte=ctx.end).filter(
        Q(stage__is_won=True) | Q(stage__is_lost=True)).order_by("-closed_at")
    rows = [[link(o, o.code), o.title, o.customer.company_name, "Won" if o.stage.is_won else "Lost",
             o.estimated_value, o.closed_at.date(), str(o.lost_reason or "") if o.stage.is_lost else "",
             o.assigned_engineer] for o in qs]
    won = [r for r in rows if r[3] == "Won"]
    return Result(["ID", "Opportunity", "Customer", "Result", "Value", "Closed", "Lost reason", "Sales Engineer"],
                  rows, totals=["", f"Won {len(won)} / lost {len(rows) - len(won)}", "",
                                f"Win rate {pct(len(won), len(rows)) or 0}%", sum((r[4] for r in rows), ZERO), "", "",
                                ""], money_cols={4})


def r_forecast(ctx):
    from sales.services import forecast_by_month

    rows = [[r["label"], r["count"], r["value"], r["weighted"]] for r in forecast_by_month(_opps(ctx))]
    return Result(["Expected closing month", "Opportunities", "Value", "Weighted forecast"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO),
                          sum((r[3] for r in rows), ZERO)], money_cols={2, 3},
                  note="Open opportunities by expected closing date. Weighted = value × probability.")


# ====================================================================== visit reports
def r_visits_by_employee(ctx):
    qs = _visits(ctx).filter(visit_date__gte=ctx.start, visit_date__lte=ctx.end)
    agg = defaultdict(Counter)
    users = {}
    for v in qs:
        users[v.assigned_to_id] = v.assigned_to
        key = "missed" if v.is_missed else v.status
        agg[v.assigned_to_id][key] += 1
        agg[v.assigned_to_id]["total"] += 1
    rows = [[users[k], a["total"], a["completed"], a["scheduled"] + a["confirmed"] + a["rescheduled"], a["missed"],
             a["cancelled"]] for k, a in agg.items()]
    return Result(["Employee", "Visits", "Completed", "Upcoming", "Missed", "Cancelled"], rows,
                  totals=["Total"] + [sum(r[i] for r in rows) for i in range(1, 6)])


def _visit_list(ctx, cond, title_col="Status"):
    qs = _visits(ctx).filter(cond).order_by("visit_date", "start_time")
    rows = [[v.visit_date, link(v, v.code), v.customer.company_name, v.purpose or "", v.assigned_to, v.location,
             "Missed" if v.is_missed else v.get_status_display()] for v in qs]
    return Result(["Date", "Visit", "Customer", "Purpose", "Employee", "Location", title_col], rows,
                  totals=["Total", len(rows), "", "", "", "", ""])


def r_completed_visits(ctx):
    res = _visit_list(ctx, Q(status="completed", visit_date__gte=ctx.start, visit_date__lte=ctx.end))
    return res


def r_upcoming_visits(ctx):
    from visits.models import Visit

    return _visit_list(ctx, Q(status__in=Visit.UPCOMING_STATUSES, visit_date__gte=timezone.localdate()))


def r_cancelled_visits(ctx):
    return _visit_list(ctx, Q(status="cancelled", visit_date__gte=ctx.start, visit_date__lte=ctx.end))


def r_followup_completion(ctx):
    from tasks.models import Task

    qs = metrics.by_people(Task.objects.filter(due_date__gte=ctx.start, due_date__lte=ctx.end).exclude(
        status="cancelled"), ("assigned_to",), ctx.ids).select_related("assigned_to")
    today = timezone.localdate()
    agg = defaultdict(Counter)
    users = {}
    for t in qs:
        users[t.assigned_to_id] = t.assigned_to
        a = agg[t.assigned_to_id]
        a["due"] += 1
        if t.status == "completed":
            a["done"] += 1
            if t.completed_at and timezone.localtime(t.completed_at).date() <= t.due_date:
                a["on_time"] += 1
        elif t.due_date < today:
            a["overdue"] += 1
    rows = [[users[k], a["due"], a["done"], a["on_time"], a["overdue"], pct(a["on_time"], a["due"])]
            for k, a in agg.items()]
    t = [sum(r[i] for r in rows) for i in (1, 2, 3, 4)]
    return Result(["Employee", "Tasks due", "Completed", "On time", "Still overdue", "On-time %"], rows,
                  totals=["Total", *t, pct(t[2], t[0])])


# ====================================================================== quotation reports
def r_quotes_by_status(ctx):
    from quotations.models import QuotationRevision

    qs = _quotes(ctx).filter(quotation_date__gte=ctx.start, quotation_date__lte=ctx.end)
    rows = []
    for code, label in QuotationRevision.Status.choices:
        if code == "superseded":
            continue
        items = qs.filter(status=code)
        rows.append([(label, reverse("quotations:list") + f"?status={code}"), items.count(),
                     metrics._sum(items, "grand_total")])
    return Result(["Status (current revision)", "Quotations", "Grand total"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO)], money_cols={2})


def r_quote_value_period(ctx):
    rows = []
    d = ctx.start.replace(day=1)
    while d <= ctx.end:
        s, e = metrics.month_range(d)
        s, e = max(s, ctx.start), min(e, ctx.end)
        issued = metrics.quotations_issued_qs(ctx.ids, s, e)
        rows.append([d.strftime("%b %Y"), issued.count(), metrics._sum(issued, "grand_total")])
        d = (d + datetime.timedelta(days=32)).replace(day=1)
    return Result(["Month", "Revisions sent", "Value sent"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO)], money_cols={2})


def r_approval_turnaround(ctx):
    from quotations.models import Approval

    qs = Approval.objects.filter(decision__in=["approved", "rejected"], decided_at__date__gte=ctx.start,
                                 decided_at__date__lte=ctx.end).select_related("revision__quotation", "decided_by")
    qs = metrics.by_people(qs, ("revision__quotation__salesperson",), ctx.ids)
    rows = []
    for a in qs.order_by("-decided_at"):
        sub = a.revision.submitted_at
        hours = round((a.decided_at - sub).total_seconds() / 3600, 1) if sub else None
        rows.append([link(a.revision.quotation, f"{a.revision.quotation.number} Rev {a.revision.version}"),
                     a.get_decision_display(), a.decided_by, sub, a.decided_at, hours, a.grand_total])
    hours = [r[5] for r in rows if r[5] is not None]
    avg = round(sum(hours) / len(hours), 1) if hours else None
    return Result(["Quotation", "Decision", "Approver", "Submitted", "Decided", "Hours to decide", "Grand total"],
                  rows, totals=["Average", "", "", "", "", avg, ""], money_cols={6})


def r_accepted_rejected(ctx):
    from quotations.models import QuotationRevision

    qs = metrics.by_people(QuotationRevision.objects.filter(
        status__in=["accepted", "declined", "rejected"]).filter(
        Q(customer_response_at__gte=ctx.start, customer_response_at__lte=ctx.end) |
        Q(decided_at__date__gte=ctx.start, decided_at__date__lte=ctx.end)), ("quotation__salesperson",),
        ctx.ids).select_related("quotation__customer", "quotation__salesperson")
    rows = [[link(r.quotation, f"{r.quotation.number} Rev {r.version}"), r.quotation.customer.company_name,
             r.get_status_display(), r.customer_response_at or (r.decided_at.date() if r.decided_at else None),
             r.grand_total, r.decline_reason or r.decision_comments if r.status != "accepted" else r.customer_reference,
             r.quotation.salesperson] for r in qs]
    return Result(["Quotation", "Customer", "Outcome", "Date", "Grand total", "Reason / PO", "Salesperson"], rows,
                  money_cols={4})


def r_quote_conversion(ctx):
    from quotations.models import QuotationRevision

    qs = metrics.by_people(QuotationRevision.objects.filter(sent_at__date__gte=ctx.start,
                                                            sent_at__date__lte=ctx.end), ("quotation__salesperson",),
                           ctx.ids).select_related("quotation__salesperson")
    agg = defaultdict(Counter)
    users = {}
    for r in qs:
        users[r.quotation.salesperson_id] = r.quotation.salesperson
        a = agg[r.quotation.salesperson_id]
        a["sent"] += 1
        a[r.status] += 1
    rows = [[users[k], a["sent"], a["accepted"], a["declined"], a["expired"], a["sent"] - a["accepted"] -
             a["declined"] - a["expired"], pct(a["accepted"], a["accepted"] + a["declined"] + a["expired"])]
            for k, a in agg.items()]
    t = [sum(r[i] for r in rows) for i in (1, 2, 3, 4, 5)]
    return Result(["Salesperson", "Sent", "Accepted", "Declined", "Expired", "Superseded / pending",
                   "Conversion %"], rows, totals=["Total", *t, pct(t[1], t[1] + t[2] + t[3])],
                  note="Revisions sent in the period. Conversion = accepted ÷ (accepted + declined + expired).")


# ====================================================================== order reports
def _orders(ctx):
    qs = metrics.booked_orders_qs(ctx.ids, ctx.start, ctx.end).select_related("customer", "assigned_to")
    return qs.filter(customer=ctx.customer) if ctx.customer else qs


def r_confirmed_orders(ctx):
    rows = [[o.confirmed_at.date(), link(o, o.number), o.customer.company_name, o.customer_po_ref,
             o.get_status_display(), o.assigned_to, o.net_amount, o.total_amount] for o in _orders(ctx).order_by(
        "confirmed_at")]
    return Result(["Confirmed", "Order", "Customer", "Customer PO", "Status", "Employee", "Excl. VAT", "Incl. VAT"],
                  rows, totals=["Total", len(rows), "", "", "", "", sum((r[6] for r in rows), ZERO),
                                sum((r[7] for r in rows), ZERO)], money_cols={6, 7})


def r_order_value_period(ctx):
    rows = []
    d = ctx.start.replace(day=1)
    while d <= ctx.end:
        s, e = metrics.month_range(d)
        s, e = max(s, ctx.start), min(e, ctx.end)
        qs = metrics.booked_orders_qs(ctx.ids, s, e)
        rows.append([d.strftime("%b %Y"), qs.count(), metrics._sum(qs, "net_amount")])
        d = (d + datetime.timedelta(days=32)).replace(day=1)
    return Result(["Month", "Orders confirmed", "Booking value (excl. VAT)"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO)], money_cols={2})


def r_orders_by_employee(ctx):
    agg = defaultdict(lambda: {"n": 0, "v": ZERO})
    users = {}
    for o in _orders(ctx):
        users[o.assigned_to_id] = o.assigned_to
        agg[o.assigned_to_id]["n"] += 1
        agg[o.assigned_to_id]["v"] += o.net_amount
    rows = [[users[k], a["n"], a["v"]] for k, a in sorted(agg.items(), key=lambda kv: -kv[1]["v"])]
    return Result(["Employee", "Orders", "Booked (excl. VAT)"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO)], money_cols={2})


def r_order_status(ctx):
    from orders.models import SalesOrder

    qs = metrics.by_people(SalesOrder.objects.filter(order_date__gte=ctx.start, order_date__lte=ctx.end),
                           ("assigned_to",), ctx.ids)
    rows = []
    for code, label in SalesOrder.Status.choices:
        items = qs.filter(status=code)
        rows.append([(label, reverse("orders:list") + f"?status={code}"), items.count(),
                     metrics._sum(items, "net_amount")])
    return Result(["Status", "Orders", "Value (excl. VAT)"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO)], money_cols={2},
                  note="Orders dated in the period. Draft and cancelled orders are not order bookings.")


# ====================================================================== financial reports
def r_invoices_issued(ctx):
    qs = _invoices(ctx).filter(invoice_date__gte=ctx.start, invoice_date__lte=ctx.end).order_by("invoice_date")
    rows = [[i.invoice_date, link(i, i.number), i.customer.company_name, i.order.number, i.due_date, i.subtotal,
             i.tax_amount, i.total, i.amount_paid, i.outstanding, i.display_status] for i in qs]
    return Result(["Date", "Invoice", "Customer", "Order", "Due", "Excl. VAT", "VAT", "Total", "Paid", "Outstanding",
                   "Status"], rows,
                  totals=["Total", len(rows), "", "", ""] + [sum((r[i] for r in rows), ZERO) for i in (5, 6, 7, 8, 9)]
                  + [""], money_cols={5, 6, 7, 8, 9})


def r_collections(ctx):
    from invoicing.models import Payment

    qs = metrics.by_people(Payment.objects.filter(payment_date__gte=ctx.start, payment_date__lte=ctx.end),
                           ("created_by", "customer__assigned_engineer", "customer__assigned_coordinator"),
                           ctx.ids).select_related("customer")
    if ctx.customer:
        qs = qs.filter(customer=ctx.customer)
    rows = [[p.payment_date, link(p, p.number), p.customer.company_name, p.get_method_display(), p.reference,
             "Reversal" if p.is_reversal else "Receipt", p.amount, p.allocated, p.unallocated]
            for p in qs.order_by("payment_date")]
    return Result(["Date", "Receipt", "Customer", "Method", "Reference", "Type", "Amount", "Allocated", "Unallocated"],
                  rows, totals=["Net total", len(rows), "", "", "", ""] + [sum((r[i] for r in rows), ZERO)
                                                                          for i in (6, 7, 8)], money_cols={6, 7, 8})


def r_receivables(ctx):
    from invoicing.models import Invoice
    from invoicing.services import AGEING_BUCKETS

    invoices = [i for i in _invoices(ctx).filter(status__in=Invoice.OPEN_STATUSES)]
    today = timezone.localdate()
    per = OrderedDict()
    for i in sorted(invoices, key=lambda x: x.customer.company_name):
        row = per.setdefault(i.customer_id, [link(i.customer, i.customer.company_name)] + [ZERO] * 6)
        days = (today - i.due_date).days
        for idx, (_, lo, hi) in enumerate(AGEING_BUCKETS):
            if (lo is None and days <= 0) or (lo is not None and days >= lo and (hi is None or days <= hi)):
                row[1 + idx] += i.outstanding
                break
        row[6] += i.outstanding
    rows = list(per.values())
    return Result(["Customer"] + [b[0] for b in AGEING_BUCKETS] + ["Total outstanding"], rows,
                  totals=["Total"] + [sum((r[i] for r in rows), ZERO) for i in range(1, 7)],
                  money_cols={1, 2, 3, 4, 5, 6}, note="Open invoices as of today, by days past due.")


def r_overdue(ctx):
    from invoicing.models import Invoice

    rows = [[link(i, i.number), i.customer.company_name, i.due_date, i.days_overdue, i.total, i.outstanding,
             "Yes" if i.is_disputed else ""] for i in _invoices(ctx).filter(status__in=Invoice.OPEN_STATUSES)
            .order_by("due_date") if i.is_overdue]
    return Result(["Invoice", "Customer", "Due", "Days overdue", "Total", "Outstanding", "Disputed"], rows,
                  totals=["Total", len(rows), "", "", sum((r[4] for r in rows), ZERO), sum((r[5] for r in rows), ZERO),
                          ""], money_cols={4, 5})


def r_partially_paid(ctx):
    rows = [[link(i, i.number), i.customer.company_name, i.invoice_date, i.due_date, i.total, i.amount_paid,
             i.outstanding] for i in _invoices(ctx).filter(status="partially_paid").order_by("due_date")]
    return Result(["Invoice", "Customer", "Date", "Due", "Total", "Paid", "Outstanding"], rows,
                  totals=["Total", len(rows), "", "", *(sum((r[i] for r in rows), ZERO) for i in (4, 5, 6))],
                  money_cols={4, 5, 6})


def r_statements(ctx):
    from invoicing.models import Invoice

    customers = {}
    for i in _invoices(ctx):
        c = customers.setdefault(i.customer_id, {"c": i.customer, "inv": ZERO, "out": ZERO, "n": 0})
        c["inv"] += i.total
        c["n"] += 1
        if i.status in Invoice.OPEN_STATUSES:
            c["out"] += i.outstanding
    rows = [[(c["c"].company_name, reverse("invoicing:statement", args=[c["c"].pk]) +
              f"?start={ctx.start}&end={ctx.end}"), c["n"],
             c["inv"], c["out"]] for c in sorted(customers.values(), key=lambda x: -x["out"])]
    return Result(["Customer (opens the statement)", "Invoices", "Invoiced (all time)", "Outstanding"], rows,
                  money_cols={2, 3}, note="Open a customer to see the full statement for the chosen period.")


def r_collection_performance(ctx):
    rows = []
    d = ctx.start.replace(day=1)
    while d <= ctx.end:
        s, e = metrics.month_range(d)
        s, e = max(s, ctx.start), min(e, ctx.end)
        inv = metrics._sum(metrics.issued_invoices_qs(ctx.ids, s, e), "total")
        col = metrics.collected(ctx.ids, s, e)
        rows.append([d.strftime("%b %Y"), inv, col, pct(col, inv)])
        d = (d + datetime.timedelta(days=32)).replace(day=1)
    ti, tc = sum((r[1] for r in rows), ZERO), sum((r[2] for r in rows), ZERO)
    return Result(["Month", "Invoiced", "Collected", "Collection rate %"], rows, totals=["Total", ti, tc, pct(tc, ti)],
                  money_cols={1, 2}, note="Collection rate = collected ÷ invoiced in the same month.")


# ====================================================================== employee reports
def r_target_achievement(ctx):
    from performance.services import scorecard

    rows = []
    for u in employees_visible_to(ctx.user).filter(is_active=True, profile__role__code__in=["ENGINEER", "DIRECTOR",
                                                                                           "COORDINATOR"]):
        if ctx.employee and u.pk != ctx.employee:
            continue
        card = scorecard(u, "month", ctx.end, compare=False)
        for r in card["rows"]:
            if r["target"] is None:
                continue
            rows.append([u, r["kpi"].name, card["start"].strftime("%b %Y"), r["target"], r["actual"], r["pct"]])
    return Result(["Employee", "KPI", "Month", "Target", "Actual", "Achievement %"], rows,
                  note="Monthly targets for the month containing the end date. Achievement = actual ÷ target × 100.")


def r_quotation_generation(ctx):
    agg = defaultdict(lambda: {"n": 0, "v": ZERO})
    users = {}
    for r in metrics.quotations_issued_qs(ctx.ids, ctx.start, ctx.end).select_related("quotation__salesperson"):
        u = r.quotation.salesperson
        users[u.pk] = u
        agg[u.pk]["n"] += 1
        agg[u.pk]["v"] += r.grand_total
    rows = [[users[k], a["n"], a["v"]] for k, a in agg.items()]
    return Result(["Salesperson", "Revisions sent", "Value sent"], rows,
                  totals=["Total", sum(r[1] for r in rows), sum((r[2] for r in rows), ZERO)], money_cols={2})


# ====================================================================== registry
R = Report
REPORTS = [
    R("customer_list", "Customers", "Complete customer list", "Every active customer with owner and contact dates.",
      "reports.customers", r_customer_list, uses_dates=False, uses_customer=True),
    R("customers_by_category", "Customers", "Customers by category", "Counts by category and status.",
      "reports.customers", r_customers_by_category, uses_dates=False),
    R("new_customers", "Customers", "New customers by period", "Customers created in the period.",
      "reports.customers", r_new_customers),
    R("inactive_customers", "Customers", "Inactive customers", "No visit or communication for 90 days.",
      "reports.customers", r_inactive_customers, uses_dates=False),
    R("interactions", "Customers", "Customer interaction history", "Visits and communications per customer.",
      "reports.operational", r_interactions, uses_customer=True),
    R("leads_by_source", "Leads", "Leads by source", "Volume, value and conversion by lead source.",
      "reports.sales", r_leads_by_source),
    R("leads_by_owner", "Leads", "Leads by owner", "Volume, value and conversion by Sales Engineer.",
      "reports.sales", r_leads_by_owner),
    R("leads_by_stage", "Leads", "Leads by status", "Leads created in the period by current stage.",
      "reports.sales", r_leads_by_stage),
    R("lead_conversion", "Leads", "Lead conversion rate", "Conversion by month the lead was created.",
      "reports.sales", r_lead_conversion),
    R("lost_leads", "Leads", "Lost-lead analysis", "Why leads were lost, by reason.", "reports.sales", r_lost_leads),
    R("pipeline", "Sales", "Pipeline value", "Open pipeline by stage with weighted forecast.", "reports.sales",
      r_pipeline, uses_dates=False),
    R("sales_by_employee", "Sales", "Sales by employee", "Quotations, orders, invoices and collections per employee.",
      "team.view", r_sales_by_employee),
    R("sales_by_customer", "Sales", "Sales by customer", "Orders booked per customer.", "reports.sales",
      r_sales_by_customer, uses_customer=True),
    R("sales_by_period", "Sales", "Sales by period", "Monthly quotations, orders, invoices and collections.",
      "reports.sales", r_sales_by_period),
    R("won_lost", "Sales", "Won and lost opportunities", "Opportunities closed in the period with win rate.",
      "reports.sales", r_won_lost),
    R("forecast", "Sales", "Expected closing forecast", "Open pipeline by expected closing month.", "reports.sales",
      r_forecast, uses_dates=False),
    R("visits_by_employee", "Visits", "Visits by employee", "Completed, upcoming, missed and cancelled visits.",
      "reports.operational", r_visits_by_employee),
    R("completed_visits", "Visits", "Completed visits", "Visits completed in the period.", "reports.operational",
      r_completed_visits),
    R("upcoming_visits", "Visits", "Upcoming visits", "Scheduled visits from today.", "reports.operational",
      r_upcoming_visits, uses_dates=False),
    R("cancelled_visits", "Visits", "Cancelled visits", "Visits cancelled in the period.", "reports.operational",
      r_cancelled_visits),
    R("followup_completion", "Visits", "Follow-up completion", "Tasks due, completed on time and overdue.",
      "reports.operational", r_followup_completion),
    R("quotes_by_status", "Quotations", "Quotations by status", "Count and value by current status.",
      "reports.sales", r_quotes_by_status),
    R("quote_value_period", "Quotations", "Quotation value by period", "Value of revisions sent per month.",
      "reports.sales", r_quote_value_period),
    R("approval_turnaround", "Quotations", "Approval turnaround time", "Hours from submission to decision.",
      "reports.sales", r_approval_turnaround),
    R("accepted_rejected", "Quotations", "Accepted and rejected quotations", "Customer and approval outcomes.",
      "reports.sales", r_accepted_rejected),
    R("quote_conversion", "Quotations", "Quotation conversion rate", "Accepted ÷ decided, per salesperson.",
      "reports.sales", r_quote_conversion),
    R("confirmed_orders", "Orders", "Confirmed orders", "Orders confirmed in the period.", "reports.sales",
      r_confirmed_orders, uses_customer=True),
    R("order_value_period", "Orders", "Order booking value", "Booking value by month.", "reports.sales",
      r_order_value_period),
    R("orders_by_customer", "Orders", "Orders by customer", "Booking value per customer.", "reports.sales",
      r_sales_by_customer, uses_customer=True),
    R("orders_by_employee", "Orders", "Orders by employee", "Booking value per employee.", "reports.sales",
      r_orders_by_employee),
    R("order_status", "Orders", "Order status", "Orders by status.", "reports.sales", r_order_status),
    R("invoices_issued", "Financial", "Invoices issued", "Invoices issued in the period.", "reports.financial",
      r_invoices_issued, uses_customer=True),
    R("collections", "Financial", "Collections received", "Payments and reversals in the period.",
      "reports.financial", r_collections, uses_customer=True),
    R("receivables", "Financial", "Outstanding receivables", "Ageing of open invoices by customer.",
      "reports.financial", r_receivables, uses_dates=False, uses_customer=True),
    R("overdue", "Financial", "Overdue invoices", "Open invoices past their due date.", "reports.financial",
      r_overdue, uses_dates=False, uses_customer=True),
    R("partially_paid", "Financial", "Partially paid invoices", "Invoices with part payments.",
      "reports.financial", r_partially_paid, uses_dates=False, uses_customer=True),
    R("statements", "Financial", "Customer statements", "Customers with invoices; open their statement.",
      "statements.view", r_statements),
    R("collection_performance", "Financial", "Collection performance", "Invoiced vs collected by month.",
      "reports.financial", r_collection_performance),
    R("target_achievement", "Employees", "Target achievement", "Monthly targets against actual results.",
      "targets.view", r_target_achievement),
    R("employee_conversion", "Employees", "Lead conversion by employee", "Lead conversion per Sales Engineer.",
      "reports.sales", r_leads_by_owner),
    R("employee_visits", "Employees", "Customer visits by employee", "Visit outcomes per employee.",
      "reports.operational", r_visits_by_employee),
    R("employee_followups", "Employees", "Follow-up completion by employee", "On-time follow-up rate.",
      "reports.operational", r_followup_completion),
    R("quotation_generation", "Employees", "Quotation generation", "Quotations sent per salesperson.",
      "reports.sales", r_quotation_generation),
    R("order_performance", "Employees", "Order booking performance", "Orders booked per employee.",
      "reports.sales", r_orders_by_employee),
]
GROUP_ORDER = ["Customers", "Leads", "Sales", "Visits", "Quotations", "Orders", "Financial", "Employees"]


def get_report(key):
    return next((r for r in REPORTS if r.key == key), None)


def report_groups(user):
    groups = OrderedDict((g, []) for g in GROUP_ORDER)
    for r in REPORTS:
        if has_capability(user, r.capability):
            groups[r.group].append(r)
    return [(g, items) for g, items in groups.items() if items]

