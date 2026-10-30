"""
Module dashboards: Leads, Customer Visits, Customers, Sales Pipeline, Opportunities, Projects, Quotations.

Every figure is counted from CRM records the viewer may see (the module's own data scope), for the chosen
period and employee. Each card links to the matching filtered list ("drill-down").

Counting rules (no double counting):
* Leads and opportunities are separate: a lead's estimated value is never added to opportunity values.
* A quotation counts once whatever its number of revisions; value = its current revision.
* Revenue = estimated value of opportunities WON in the period (closed date). Quotation values, lead estimates and
  open pipeline are never revenue.
"""
import datetime
from collections import OrderedDict
from decimal import Decimal
from urllib.parse import urlencode

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import has_capability, scope_queryset, visible_user_ids
from core.crud import person
from core.scopes import owners
from performance import monitoring as mon

ZERO = Decimal("0.00")


def link(url_name, **params):
    params = {k: v for k, v in params.items() if v not in (None, "", False)}
    url = reverse(url_name)
    return url + ("?" + urlencode(params) if params else "")


def _d(d):
    return d.strftime("%Y-%m-%d")


def trend(qs, field, start, end, is_datetime=True):
    """Counts per day (periods up to 62 days) or per month."""
    lookup = f"{field}__date" if is_datetime else field
    if (end - start).days <= 62:
        rows = dict(qs.values_list(lookup).annotate(n=Count("pk", distinct=True)).order_by())
        days = [start + datetime.timedelta(days=i) for i in range((end - start).days + 1)]
        return [d.strftime("%d %b") for d in days], [rows.get(d, 0) for d in days]
    rows = {}
    for r in qs.annotate(m=TruncMonth(field)).values("m").annotate(n=Count("pk", distinct=True)).order_by():
        m = r["m"].date() if hasattr(r["m"], "date") and callable(r["m"].date) else r["m"]
        rows[(m.year, m.month)] = r["n"]
    labels, data, cur = [], [], start.replace(day=1)
    while cur <= end:
        labels.append(cur.strftime("%b %Y"))
        data.append(rows.get((cur.year, cur.month), 0))
        cur = (cur + datetime.timedelta(days=32)).replace(day=1)
    return labels, data


def chart(cid, title, kind, labels, datasets, links=None, money=False):
    return {"id": cid, "title": title, "type": kind, "labels": [str(x) for x in labels], "money": money,
            "datasets": [{"label": label, "data": [float(v or 0) for v in data]} for label, data in datasets],
            "links": links or []}


def card(label, value, tone="blue", icon="circle", url=None, sub="", money=False, now=False):
    return {"label": label, "value": value, "tone": tone, "icon": icon, "url": url, "sub": sub, "money": money,
            "now": now}


def _by(qs, field, label_fn=str, limit=12):
    rows = list(qs.values(field).annotate(n=Count("pk", distinct=True)).order_by("-n")[:limit])
    return [(r[field], r["n"]) for r in rows]


# ======================================================================= modules
def leads(user, start, end, emp):
    from core.models import LookupValue
    from leads.models import Lead, LeadStage

    base = scope_queryset(Lead.objects.filter(is_archived=False), user, owners("leads.lead"))
    if emp:
        base = base.filter(Q(assigned_engineer_id=emp) | Q(assigned_coordinator_id=emp))
    period = base.filter(created_at__date__gte=start, created_at__date__lte=end)
    rng = {"created_from": _d(start), "created_to": _d(end), "employee": emp}
    open_now = base.filter(stage__is_won=False, stage__is_lost=False)
    cats = dict(period.values_list("category").annotate(n=Count("pk")).order_by())
    cards = [
        card("Leads created", period.count(), "brand", "funnel", link("leads:list", **rng)),
        card("Job in Hand", cats.get("job_in_hand", 0), "green", "briefcase",
             link("leads:list", category="job_in_hand", **rng)),
        card("Tender", cats.get("tender", 0), "blue", "file-earmark-ruled", link("leads:list", category="tender", **rng)),
        card("Purchase Enquiry", cats.get("purchase_enquiry", 0), "orange", "cart",
             link("leads:list", category="purchase_enquiry", **rng)),
        card("Open leads", open_now.count(), "blue", "hourglass-split", link("leads:list", state="open", employee=emp),
             now=True),
        card("Follow-up overdue", open_now.filter(next_follow_up__lt=timezone.localdate()).count(), "red", "alarm",
             link("leads:list", overdue=1, employee=emp), now=True),
        card("Converted", base.filter(converted_at__date__gte=start, converted_at__date__lte=end).count(), "green",
             "arrow-right-circle", link("leads:list", converted=1, employee=emp),
             sub="to customer / opportunity in the period"),
    ]
    cat_labels = [label for _, label in Lead.Category.choices]
    cat_keys = [k for k, _ in Lead.Category.choices]
    stages = list(LeadStage.objects.filter(is_active=True))
    by_stage = dict(open_now.values_list("stage").annotate(n=Count("pk")).order_by())
    sources = _by(period.exclude(source__isnull=True), "source")
    src_names = dict(LookupValue.objects.filter(pk__in=[k for k, _ in sources]).values_list("pk", "value"))
    labels, data = trend(period, "created_at", start, end)
    charts = [
        chart("cat", "Leads by category (created in the period)", "doughnut", cat_labels,
              [("Leads", [cats.get(k, 0) for k in cat_keys])],
              [link("leads:list", category=k, **rng) for k in cat_keys]),
        chart("trend", "Leads created", "bar", labels, [("Leads", data)]),
        chart("stage", "Open leads by status (now)", "bar", [s.name for s in stages if not s.is_closed],
              [("Leads", [by_stage.get(s.pk, 0) for s in stages if not s.is_closed])],
              [link("leads:list", stage=s.pk, employee=emp) for s in stages if not s.is_closed]),
        chart("source", "Leads by source (created in the period)", "bar", [src_names.get(k, "?") for k, _ in sources],
              [("Leads", [n for _, n in sources])], [link("leads:list", source=k, **rng) for k, _ in sources]),
    ]
    return cards, charts


def visits(user, start, end, emp):
    from visits.models import Visit

    base = scope_queryset(Visit.objects.all(), user, owners("visits.visit"))
    if emp:
        base = base.filter(assigned_to_id=emp)
    period = base.filter(visit_date__gte=start, visit_date__lte=end)
    today = timezone.localdate()
    rng = {"date_from": _d(start), "date_to": _d(end), "employee": emp}
    planned = period.exclude(status="cancelled")
    cards = [
        card("Planned", planned.count(), "brand", "calendar-event", link("visits:list", **rng),
             sub="visits dated in the period (not cancelled)"),
        card("Completed", period.filter(status="completed").count(), "green", "check2-circle",
             link("visits:list", status="completed", **rng)),
        card("Upcoming", base.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__gte=today).count(), "blue",
             "calendar-plus", link("visits:list", state="upcoming", employee=emp), now=True),
        card("Missed", period.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__lt=today).count(), "red",
             "exclamation-octagon", link("visits:list", state="missed", **rng),
             sub="date passed, not completed"),
        card("Cancelled", period.filter(status="cancelled").count(), "orange", "x-circle",
             link("visits:list", status="cancelled", **rng)),
    ]
    statuses = list(Visit.Status.choices)
    by_status = dict(period.values_list("status").annotate(n=Count("pk")).order_by())
    labels, data = trend(period.filter(status="completed"), "visit_date", start, end, is_datetime=False)
    by_emp = _by(period.filter(status="completed"), "assigned_to")
    names = _names([k for k, _ in by_emp])
    charts = [
        chart("status", "Visits by status (dated in the period)", "doughnut", [label for _, label in statuses],
              [("Visits", [by_status.get(k, 0) for k, _ in statuses])],
              [link("visits:list", status=k, **rng) for k, _ in statuses]),
        chart("trend", "Completed visits", "bar", labels, [("Completed", data)]),
        chart("emp", "Completed visits by employee", "bar", [names.get(k, "—") for k, _ in by_emp],
              [("Completed", [n for _, n in by_emp])],
              [link("visits:list", status="completed", employee=k, date_from=_d(start), date_to=_d(end))
               for k, _ in by_emp]),
    ]
    return cards, charts


def customers(user, start, end, emp):
    from core.models import LookupValue
    from customers.models import Customer

    base = scope_queryset(Customer.objects.filter(is_archived=False), user, owners("customers.customer"))
    if emp:
        base = base.filter(Q(assigned_engineer_id=emp) | Q(assigned_coordinator_id=emp))
    period = base.filter(created_at__date__gte=start, created_at__date__lte=end)
    rng = {"created_from": _d(start), "created_to": _d(end), "employee": emp}
    by_status = dict(base.values_list("status").annotate(n=Count("pk")).order_by())
    cards = [
        card("Customers", base.count(), "brand", "building", link("customers:list", employee=emp), now=True),
        card("Active", by_status.get("active", 0), "green", "check2-circle", link("customers:list", status="active",
                                                                                  employee=emp), now=True),
        card("Prospects", by_status.get("prospect", 0), "blue", "binoculars",
             link("customers:list", status="prospect", employee=emp), now=True),
        card("New in the period", period.count(), "green", "plus-circle", link("customers:list", **rng)),
        card("Follow-up overdue", base.filter(next_follow_up__lt=timezone.localdate()).count(), "red", "alarm",
             link("customers:list", overdue=1, employee=emp), now=True),
    ]
    cats = _by(base.exclude(category__isnull=True), "category")
    cat_names = dict(LookupValue.objects.filter(pk__in=[k for k, _ in cats]).values_list("pk", "value"))
    labels, data = trend(period, "created_at", start, end)
    charts = [
        chart("status", "Customers by status (now)", "doughnut", [label for _, label in Customer.Status.choices],
              [("Customers", [by_status.get(k, 0) for k, _ in Customer.Status.choices])],
              [link("customers:list", status=k, employee=emp) for k, _ in Customer.Status.choices]),
        chart("trend", "New customers", "bar", labels, [("Customers", data)]),
        chart("cat", "Customers by category (now)", "bar", [cat_names.get(k, "?") for k, _ in cats],
              [("Customers", [n for _, n in cats])], [link("customers:list", category=k, employee=emp)
                                                      for k, _ in cats]),
    ]
    return cards, charts


def _opps(user, emp):
    from sales.models import Opportunity

    base = scope_queryset(Opportunity.objects.filter(is_archived=False), user, owners("sales.opportunity"))
    if emp:
        base = base.filter(Q(assigned_engineer_id=emp) | Q(assigned_coordinator_id=emp))
    return base


def pipeline(user, start, end, emp):
    from sales.models import OpportunityStage, weighted

    base = _opps(user, emp)
    open_qs = base.filter(stage__is_won=False, stage__is_lost=False)
    today = timezone.localdate()
    value = open_qs.aggregate(v=Sum("estimated_value"))["v"] or ZERO
    w = sum((weighted(o.estimated_value, o.probability) for o in open_qs.only("estimated_value", "probability")),
            ZERO)
    m_start, m_end = mon.month_of(today)
    closing = open_qs.filter(expected_close_date__gte=m_start, expected_close_date__lte=m_end)
    cards = [
        card("Open pipeline", value, "blue", "kanban", link("sales:kanban", employee=emp), money=True, now=True,
             sub=f"{open_qs.count()} open opportunities"),
        card("Weighted forecast", w, "brand", "graph-up", link("sales:forecast"), money=True, now=True,
             sub="value × closing probability"),
        card("Expected to close this month", closing.aggregate(v=Sum("estimated_value"))["v"] or ZERO, "green",
             "calendar-check", link("sales:pipeline", close_from=_d(m_start), close_to=_d(m_end), state="open",
                                    employee=emp), money=True, now=True, sub=f"{closing.count()} opportunities"),
        card("Close date passed", open_qs.filter(expected_close_date__lt=today).count(), "red", "alarm",
             link("sales:pipeline", overdue=1, employee=emp), now=True),
    ]
    stages = [s for s in OpportunityStage.objects.filter(is_active=True) if not s.is_closed]
    by_stage = {r["stage"]: r for r in open_qs.values("stage").annotate(n=Count("pk"), v=Sum("estimated_value"))
                .order_by()}
    months, vals, cur = [], [], today.replace(day=1)
    for _ in range(6):
        nxt = (cur + datetime.timedelta(days=32)).replace(day=1)
        months.append(cur.strftime("%b %Y"))
        vals.append(open_qs.filter(expected_close_date__gte=cur, expected_close_date__lt=nxt)
                    .aggregate(v=Sum("estimated_value"))["v"] or 0)
        cur = nxt
    charts = [
        chart("stage", "Open pipeline value by stage (now)", "bar", [s.name for s in stages],
              [("Value", [by_stage.get(s.pk, {}).get("v") or 0 for s in stages])],
              [link("sales:pipeline", stage=s.pk, employee=emp) for s in stages], money=True),
        chart("forecast", "Open pipeline by expected closing month", "bar", months, [("Value", vals)], money=True),
    ]
    return cards, charts


def opportunities(user, start, end, emp):
    from core.models import LookupValue

    base = _opps(user, emp)
    created = base.filter(created_at__date__gte=start, created_at__date__lte=end)
    closed = base.filter(closed_at__date__gte=start, closed_at__date__lte=end)
    won, lost = closed.filter(stage__is_won=True), closed.filter(stage__is_lost=True)
    won_value = won.aggregate(v=Sum("estimated_value"))["v"] or ZERO
    nw, nl = won.count(), lost.count()
    cards = [
        card("Created", created.count(), "brand", "lightning-charge", link("sales:pipeline", employee=emp)),
        card("Open", base.filter(stage__is_won=False, stage__is_lost=False).count(), "blue", "hourglass-split",
             link("sales:pipeline", state="open", employee=emp), now=True),
        card("Won", nw, "green", "trophy", link("sales:pipeline", state="won", employee=emp),
             sub="closed in the period"),
        card("Won revenue", won_value, "green", "cash-stack", link("sales:pipeline", state="won", employee=emp),
             money=True, sub="the only revenue figure: won opportunities"),
        card("Lost", nl, "red", "x-octagon", link("sales:pipeline", state="lost", employee=emp)),
        card("Win rate", f"{(nw * 100 / (nw + nl)):.0f}%" if (nw + nl) else "—", "orange", "percent",
             sub="won ÷ (won + lost) in the period"),
        card("Average won deal", (won_value / nw).quantize(Decimal("0.01")) if nw else ZERO, "blue", "calculator",
             money=True),
    ]
    reasons = _by(lost.exclude(lost_reason__isnull=True), "lost_reason")
    rnames = dict(LookupValue.objects.filter(pk__in=[k for k, _ in reasons]).values_list("pk", "value"))
    owners_won = mon.owned(won, "opportunity", None).values("owner_uid").annotate(v=Sum("estimated_value"))
    owners_won = sorted(owners_won, key=lambda r: r["v"] or 0, reverse=True)[:12]
    names = _names([r["owner_uid"] for r in owners_won])
    labels, data = trend(created, "created_at", start, end)
    charts = [
        chart("trend", "Opportunities created", "bar", labels, [("Created", data)]),
        chart("won", "Won revenue by responsible employee", "bar", [names.get(r["owner_uid"], "—") for r in owners_won],
              [("Won revenue", [r["v"] or 0 for r in owners_won])],
              [link("sales:pipeline", state="won", employee=r["owner_uid"]) for r in owners_won], money=True),
        chart("lost", "Lost reasons (closed in the period)", "doughnut", [rnames.get(k, "?") for k, _ in reasons],
              [("Opportunities", [n for _, n in reasons])]),
    ]
    return cards, charts


def projects(user, start, end, emp):
    from sales.models import Project

    base = scope_queryset(Project.objects.all(), user, owners("sales.project"))
    if emp:
        base = base.filter(project_manager_id=emp)
    by_status = dict(base.values_list("status").annotate(n=Count("pk")).order_by())
    cards = [card(label, by_status.get(k, 0), tone, icon, link("sales:projects", status=k, employee=emp), now=True)
             for (k, label), tone, icon in zip(Project.Status.choices, ["blue", "brand", "orange", "green", "red"],
                                                ["clipboard", "play-circle", "pause-circle", "check2-circle",
                                                 "x-circle"])]
    period = base.filter(created_at__date__gte=start, created_at__date__lte=end)
    cards.insert(0, card("Started in the period", period.count(), "brand", "briefcase",
                         link("sales:projects", employee=emp)))
    labels, data = trend(period, "created_at", start, end)
    charts = [
        chart("status", "Projects by status (now)", "doughnut", [label for _, label in Project.Status.choices],
              [("Projects", [by_status.get(k, 0) for k, _ in Project.Status.choices])],
              [link("sales:projects", status=k, employee=emp) for k, _ in Project.Status.choices]),
        chart("trend", "Projects created", "bar", labels, [("Projects", data)]),
    ]
    return cards, charts


def quotations(user, start, end, emp):
    from quotations.models import Quotation, QuotationRevision

    base = scope_queryset(Quotation.objects.all(), user, owners("quotations.quotation"))
    if emp:
        base = base.filter(salesperson_id=emp)
    period = base.filter(created_at__date__gte=start, created_at__date__lte=end)
    rng = {"date_from": _d(start), "date_to": _d(end), "employee": emp}
    revs = QuotationRevision.objects.filter(quotation__in=base, version__gt=1, created_at__date__gte=start,
                                            created_at__date__lte=end)
    by_status = dict(base.values_list("status").annotate(n=Count("pk")).order_by())
    cards = [
        card("Quotations", period.count(), "brand", "file-earmark-text", link("quotations:list", **rng),
             sub=f"{period.filter(source='uploaded').count()} uploaded · "
                 f"{period.filter(source='built').count()} prepared in the CRM"),
        card("Revisions", revs.count(), "blue", "files", sub=f"on {revs.values('quotation').distinct().count()} "
                                                             "quotations (counted once each)"),
        card("Awaiting approval", by_status.get("submitted", 0), "orange", "hourglass-split",
             link("quotations:list", status="submitted", employee=emp), now=True),
        card("Approved / sent", by_status.get("approved", 0) + by_status.get("sent", 0), "blue", "send",
             link("quotations:list", status="sent", employee=emp), now=True),
        card("Accepted", by_status.get("accepted", 0), "green", "hand-thumbs-up",
             link("quotations:list", status="accepted", employee=emp), now=True),
        card("Value quoted", period.aggregate(v=Sum("grand_total"))["v"] or ZERO, "brand", "cash", money=True,
             sub="latest revision of each quotation · not revenue"),
    ]
    statuses = [k for k in ("draft", "submitted", "approved", "rejected", "sent", "accepted", "declined", "expired")]
    labels_map = dict(QuotationRevision.Status.choices)
    labels, data = trend(period, "created_at", start, end)
    by_emp = _by(period, "salesperson")
    names = _names([k for k, _ in by_emp])
    charts = [
        chart("status", "Quotations by current status (now)", "doughnut", [labels_map[k] for k in statuses],
              [("Quotations", [by_status.get(k, 0) for k in statuses])],
              [link("quotations:list", status=k, employee=emp) for k in statuses]),
        chart("trend", "Quotations created", "bar", labels, [("Quotations", data)]),
        chart("emp", "Quotations by salesperson (period)", "bar", [names.get(k, "—") for k, _ in by_emp],
              [("Quotations", [n for _, n in by_emp])], [link("quotations:list", employee=k, **{
                  "date_from": _d(start), "date_to": _d(end)}) for k, _ in by_emp]),
    ]
    return cards, charts


def _names(ids):
    from django.contrib.auth import get_user_model

    return {u.pk: person(u) for u in get_user_model().objects.filter(pk__in=[i for i in ids if i])}


MODULES = OrderedDict([
    ("leads", ("Leads Dashboard", "funnel", "leads.view", leads, "leads:list")),
    ("visits", ("Customer Visits Dashboard", "calendar-check", "visits.view", visits, "visits:list")),
    ("customers", ("Customers Dashboard", "building", "customers.view", customers, "customers:list")),
    ("pipeline", ("Sales Pipeline Dashboard", "kanban", "pipeline.view", pipeline, "sales:kanban")),
    ("opportunities", ("Opportunities Dashboard", "lightning-charge", "pipeline.view", opportunities,
                       "sales:pipeline")),
    ("projects", ("Projects Dashboard", "briefcase", "projects.view", projects, "sales:projects")),
    ("quotations", ("Quotations Dashboard", "file-earmark-text", "quotations.view", quotations, "quotations:list")),
])


def employees_for(user):
    ids = visible_user_ids(user)
    qs = mon.sales_employees(include_inactive=False)
    return [u for u in qs if ids is None or u.pk in ids]


def allowed_modules(user):
    return [(k, v[0], v[1]) for k, v in MODULES.items() if has_capability(user, v[2])]
