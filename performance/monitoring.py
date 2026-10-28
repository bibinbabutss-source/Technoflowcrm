"""
Employee performance monitoring — the single calculation layer for the Employee Performance pages.

ATTRIBUTION (each record counts for exactly ONE employee, so team totals = the sum of the rows):
    Lead, Opportunity  owner = assigned Sales Engineer, else assigned Sales Coordinator, else who created it
    Lead "created"     = who created it (the same rule as the existing "Leads generated" KPI;
                         imported leads are created in the name of the employee in the file)
    Quotation          = its salesperson            Visit, Task = assigned employee
    Communication      = its employee               Daily report = the employee who wrote it

PERIOD vs NOW:
    Figures marked "in the period" count events whose own date falls inside [start, end] in the CRM time
    zone (Asia/Dubai): lead created_at, visit date, quotation created_at / sent_at, approval decision date,
    opportunity closed_at, task completed_at, communication occurred_at, stage-history changed_at.
    Figures marked "now" (open leads, pipeline, pending / overdue work) describe the situation today.

NO DOUBLE COUNTING:
    * A lead with several stage changes counts once in "leads progressed".
    * A quotation with several revisions counts once (created once; "sent" = quotations with at least one
      revision sent in the period; approved / rejected = quotations with such a decision in the period).
    * A deal is the opportunity, counted once when it is won or lost (closed_at); won value = its estimated
      value. Quotations and orders of the same deal do not add to "won value".
    * Cancelled or missed visits never count as completed.
"""
import datetime
from collections import defaultdict
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Count, F, Max, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts import capabilities as caps
from accounts.permissions import get_profile, has_capability, visible_user_ids

ZERO = Decimal("0.00")
SALES_ROLES = [caps.DIRECTOR, caps.COORDINATOR, caps.ENGINEER]

PRESETS = [("today", "Today"), ("yesterday", "Yesterday"), ("this_week", "This week"), ("last_week", "Last week"),
           ("this_month", "This month"), ("last_month", "Last month"), ("custom", "Custom range")]


# ------------------------------------------------------------------ periods
def period_for(preset, today=None, start=None, end=None):
    """(start, end, preset) for a preset name; weeks run Monday to Sunday."""
    today = today or timezone.localdate()
    if preset == "today":
        return today, today, preset
    if preset == "yesterday":
        y = today - datetime.timedelta(days=1)
        return y, y, preset
    monday = today - datetime.timedelta(days=today.weekday())
    if preset == "this_week":
        return monday, monday + datetime.timedelta(days=6), preset
    if preset == "last_week":
        return monday - datetime.timedelta(days=7), monday - datetime.timedelta(days=1), preset
    first = today.replace(day=1)
    if preset == "last_month":
        last_end = first - datetime.timedelta(days=1)
        return last_end.replace(day=1), last_end, preset
    if preset == "custom" and start and end:
        if end < start:
            start, end = end, start
        if (end - start).days > 366 * 3:
            start = end - datetime.timedelta(days=366 * 3)
        return start, end, preset
    next_first = (first + datetime.timedelta(days=32)).replace(day=1)
    return first, next_first - datetime.timedelta(days=1), "this_month"


def month_of(d):
    first = d.replace(day=1)
    return first, (first + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)


# ------------------------------------------------------------------ who may see whom
def sales_employees(include_inactive=False):
    User = get_user_model()
    qs = User.objects.filter(profile__isnull=False, profile__role__code__in=SALES_ROLES).select_related(
        "profile__role", "profile__reporting_manager__user")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return qs.order_by("first_name", "last_name", "username")


def monitorable_ids(viewer):
    """Employee ids whose performance the viewer may open (always includes the viewer). None = all."""
    if has_capability(viewer, "employees.monitor"):
        return visible_user_ids(viewer)  # all (Admin, Director) or own team (Coordinator / team scope)
    return {viewer.pk}


def can_view_employee(viewer, employee):
    if get_profile(viewer) is None or not has_capability(viewer, "performance.view"):
        return False
    if employee.pk == viewer.pk:
        return True
    if not has_capability(viewer, "employees.monitor"):
        return False
    ids = visible_user_ids(viewer)
    return ids is None or employee.pk in ids


# ------------------------------------------------------------------ attribution
def _owner_expr():
    return Coalesce(F("assigned_engineer_id"), F("assigned_coordinator_id"), F("created_by_id"))


def owned(qs, kind, ids):
    """Annotate the single owner of each lead / opportunity and keep those owned by ids (None = all)."""
    qs = qs.annotate(owner_uid=_owner_expr())
    return qs if ids is None else qs.filter(owner_uid__in=ids)


def _count(qs, field):
    return {row[field]: row["n"] for row in qs.values(field).annotate(n=Count("pk", distinct=True)).order_by()}


def _sum(qs, field, value):
    return {row[field]: row["v"] or ZERO for row in qs.values(field).annotate(v=Sum(value)).order_by()}


def _distinct_count(qs, group, of):
    return {row[group]: row["n"] for row in qs.values(group).annotate(n=Count(of, distinct=True)).order_by()}


def _dt(start, end):
    return {"__date__gte": start, "__date__lte": end}


# ------------------------------------------------------------------ list figures (grouped, few queries)
def list_figures(uids, start, end):
    """Figures for the employee list: {uid: {...}} computed with grouped queries (no per-row queries)."""
    from core.models import AuditLog
    from leads.models import Lead
    from performance.models import KPIDefinition, SalesTarget
    from quotations.models import Quotation
    from sales.models import Opportunity
    from tasks.models import Task
    from visits.models import Visit

    uids = list(uids)
    today = timezone.localdate()
    leads_created = _count(Lead.objects.filter(created_by_id__in=uids, created_at__date__gte=start,
                                               created_at__date__lte=end), "created_by_id")
    open_leads = _count(owned(Lead.objects.filter(is_archived=False, converted_at__isnull=True,
                                                  stage__is_won=False, stage__is_lost=False), "lead", uids),
                        "owner_uid")
    visits = _count(Visit.objects.filter(assigned_to_id__in=uids, status="completed", visit_date__gte=start,
                                         visit_date__lte=end), "assigned_to_id")
    quotes = _count(Quotation.objects.filter(salesperson_id__in=uids, created_at__date__gte=start,
                                             created_at__date__lte=end), "salesperson_id")
    closed = owned(Opportunity.objects.filter(closed_at__date__gte=start, closed_at__date__lte=end), "opportunity",
                   uids)
    won = _count(closed.filter(stage__is_won=True), "owner_uid")
    lost = _count(closed.filter(stage__is_lost=True), "owner_uid")
    won_value = _sum(closed.filter(stage__is_won=True), "owner_uid", "estimated_value")
    followups = _count(Task.objects.filter(assigned_to_id__in=uids, category="follow_up",
                                           status__in=Task.OPEN_STATUSES), "assigned_to_id")
    overdue = _count(Task.objects.filter(assigned_to_id__in=uids, status__in=Task.OPEN_STATUSES,
                                         due_date__lt=today), "assigned_to_id")
    last = {r["user_id"]: r["t"] for r in AuditLog.objects.filter(user_id__in=uids).exclude(
        action__in=["login", "logout", "login_failed"]).values("user_id").annotate(t=Max("timestamp")).order_by()}
    # monthly sales target = the "Won deals value" target of the month that contains the period's end
    m_start, m_end = month_of(end)
    kpi = KPIDefinition.objects.filter(code="won_value").first()
    targets = {t.employee_id: t.target_value for t in SalesTarget.objects.filter(
        kpi=kpi, period_type="month", period_start=m_start, employee_id__in=uids)} if kpi else {}
    month_won = _sum(owned(Opportunity.objects.filter(stage__is_won=True, closed_at__date__gte=m_start,
                                                      closed_at__date__lte=m_end), "opportunity", uids)
                     .filter(stage__is_won=True), "owner_uid", "estimated_value")
    out = {}
    for uid in uids:
        target = targets.get(uid)
        actual = month_won.get(uid, ZERO)
        out[uid] = {
            "leads_created": leads_created.get(uid, 0), "open_leads": open_leads.get(uid, 0),
            "visits_completed": visits.get(uid, 0), "quotations_created": quotes.get(uid, 0),
            "deals_won": won.get(uid, 0), "deals_lost": lost.get(uid, 0), "won_value": won_value.get(uid, ZERO),
            "target": target, "target_actual": actual, "achievement": achievement(actual, target),
            "pending_followups": followups.get(uid, 0), "overdue_tasks": overdue.get(uid, 0),
            "last_activity": last.get(uid), "target_month": m_start,
        }
    return out


def achievement(actual, target):
    """Actual ÷ target × 100, one decimal; None when there is no target or the target is zero."""
    if target is None or Decimal(target) <= 0:
        return None
    return (Decimal(actual or 0) / Decimal(target) * 100).quantize(Decimal("0.1"))


def totals(rows, keys=("leads_created", "open_leads", "visits_completed", "quotations_created", "deals_won",
                       "deals_lost", "won_value", "pending_followups", "overdue_tasks")):
    return {k: sum((r[k] for r in rows), ZERO if k == "won_value" else 0) for k in keys}


# ------------------------------------------------------------------ one employee in detail
def employee_dashboard(user, start, end):
    from communications.models import Communication
    from leads.models import Lead, LeadStage, LeadStageHistory
    from performance.models import DailyReport
    from quotations.models import Approval, Quotation
    from sales.models import Opportunity, OpportunityStageHistory, weighted
    from tasks.models import Task
    from visits.models import Visit

    uid = user.pk
    today = timezone.localdate()
    ids = {uid}

    # ---- leads
    my_leads = owned(Lead.objects.filter(is_archived=False), "lead", ids)
    first_stage = LeadStage.objects.filter(is_active=True, is_won=False, is_lost=False).order_by("order").first()
    open_leads = my_leads.filter(converted_at__isnull=True, stage__is_won=False, stage__is_lost=False)
    created = Lead.objects.filter(created_by_id=uid, created_at__date__gte=start, created_at__date__lte=end)
    assigned = owned(Lead.objects.filter(created_at__date__gte=start, created_at__date__lte=end), "lead", ids)
    closed_leads = my_leads.filter(stage_changed_at__date__gte=start, stage_changed_at__date__lte=end)
    won_l = closed_leads.filter(stage__is_won=True).count()
    lost_l = closed_leads.filter(stage__is_lost=True).count()
    leads = {
        "created": created.count(),
        "assigned": assigned.count(),
        "new_now": open_leads.filter(stage=first_stage).count() if first_stage else 0,
        "contacted_now": open_leads.exclude(stage=first_stage).filter(stage__is_qualified=False).count()
        if first_stage else 0,
        "qualified_now": open_leads.filter(stage__is_qualified=True).count(),
        "converted": my_leads.filter(converted_at__date__gte=start, converted_at__date__lte=end).count(),
        "open_now": open_leads.count(),
        "won": won_l, "lost": lost_l,
        "conversion_rate": (Decimal(won_l) / Decimal(won_l + lost_l) * 100).quantize(Decimal("0.1"))
        if (won_l + lost_l) else None,
        "by_source": list(assigned.values("source__value").annotate(n=Count("pk")).order_by("-n")),
        "by_status": list(my_leads.values("stage__name", "stage__order").annotate(n=Count("pk"))
                          .order_by("stage__order")),
        "needs_followup": list(open_leads.filter(next_follow_up__lte=today).select_related("stage")
                               .order_by("next_follow_up")[:20]),
        "progressed": LeadStageHistory.objects.filter(changed_by_id=uid, changed_at__date__gte=start,
                                                      changed_at__date__lte=end).values("lead").distinct().count(),
    }

    # ---- visits
    vis = Visit.objects.filter(assigned_to_id=uid)
    period_vis = vis.filter(visit_date__gte=start, visit_date__lte=end)
    visits = {
        "scheduled": period_vis.count(),
        "completed": period_vis.filter(status="completed").count(),
        "cancelled": period_vis.filter(status="cancelled").count(),
        "missed": period_vis.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__lt=today).count(),
        "upcoming_now": vis.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__gte=today).count(),
        "rows": list(period_vis.select_related("customer", "lead", "opportunity", "purpose")
                     .order_by("-visit_date", "-start_time")[:50]),
    }

    # ---- sales
    quotes = Quotation.objects.filter(salesperson_id=uid)
    q_created = quotes.filter(created_at__date__gte=start, created_at__date__lte=end)
    sent = quotes.filter(revisions__sent_at__date__gte=start, revisions__sent_at__date__lte=end).distinct()
    decisions = Approval.objects.filter(revision__quotation__salesperson_id=uid, decided_at__date__gte=start,
                                        decided_at__date__lte=end)
    my_opps = owned(Opportunity.objects.filter(is_archived=False), "opportunity", ids)
    closed = owned(Opportunity.objects.filter(closed_at__date__gte=start, closed_at__date__lte=end),
                   "opportunity", ids)
    won = closed.filter(stage__is_won=True)
    won_n, won_value = won.count(), won.aggregate(v=Sum("estimated_value"))["v"] or ZERO
    open_opps = list(my_opps.filter(stage__is_won=False, stage__is_lost=False).select_related("stage", "customer"))
    m_start, m_end = month_of(end)
    sales = {
        "quotations_created": q_created.count(),
        "quotations_sent": sent.count(),
        "quotations_pending_now": quotes.filter(status__in=["draft", "submitted"]).count(),
        "approved": decisions.filter(decision__in=["approved", "auto"]).values("revision__quotation")
        .distinct().count(),
        "rejected": decisions.filter(decision="rejected").values("revision__quotation").distinct().count(),
        "opportunities_created": owned(Opportunity.objects.filter(created_at__date__gte=start,
                                                                  created_at__date__lte=end), "opportunity",
                                       ids).count(),
        "won": won_n, "lost": closed.filter(stage__is_lost=True).count(), "won_value": won_value,
        "average_deal": (won_value / won_n).quantize(Decimal("0.01")) if won_n else None,
        "pipeline_count": len(open_opps),
        "pipeline_value": sum((o.estimated_value for o in open_opps), ZERO),
        "pipeline_weighted": sum((weighted(o.estimated_value, o.probability) for o in open_opps), ZERO),
        "lost_reasons": list(closed.filter(stage__is_lost=True).values("lost_reason__value")
                             .annotate(n=Count("pk")).order_by("-n")),
        "won_rows": list(won.select_related("customer").order_by("-closed_at")[:20]),
        "month_start": m_start,
    }
    from performance.models import KPIDefinition, SalesTarget

    kpi = KPIDefinition.objects.filter(code="won_value").first()
    target = SalesTarget.objects.filter(kpi=kpi, employee_id=uid, period_type="month",
                                        period_start=m_start).first() if kpi else None
    month_actual = owned(Opportunity.objects.filter(stage__is_won=True, closed_at__date__gte=m_start,
                                                    closed_at__date__lte=m_end), "opportunity", ids) \
        .aggregate(v=Sum("estimated_value"))["v"] or ZERO
    sales.update({"target": target.target_value if target else None, "target_actual": month_actual,
                  "achievement": achievement(month_actual, target.target_value if target else None)})

    # ---- follow-ups and tasks
    tasks = Task.objects.filter(assigned_to_id=uid)
    fu = tasks.filter(category="follow_up")
    followups = {
        "fu_completed": fu.filter(status="completed", completed_at__date__gte=start,
                                  completed_at__date__lte=end).count(),
        "fu_overdue_now": fu.filter(status__in=Task.OPEN_STATUSES, due_date__lt=today).count(),
        "fu_upcoming_now": fu.filter(status__in=Task.OPEN_STATUSES, due_date__gte=today).count(),
        "tasks_completed": tasks.filter(status="completed", completed_at__date__gte=start,
                                        completed_at__date__lte=end).count(),
        "tasks_pending_now": tasks.filter(status__in=Task.OPEN_STATUSES).count(),
        "tasks_overdue_now": tasks.filter(status__in=Task.OPEN_STATUSES, due_date__lt=today).count(),
        "overdue_rows": list(tasks.filter(status__in=Task.OPEN_STATUSES, due_date__lt=today)
                             .select_related("customer").order_by("due_date")[:20]),
    }

    # ---- activity in the period (CRM-tracked vs self-reported)
    activity = {
        "calls": Communication.objects.filter(employee_id=uid, kind="call", occurred_at__date__gte=start,
                                              occurred_at__date__lte=end).count(),
        "communications": Communication.objects.filter(employee_id=uid, occurred_at__date__gte=start,
                                                       occurred_at__date__lte=end).count(),
        "opportunities_progressed": OpportunityStageHistory.objects.filter(
            changed_by_id=uid, changed_at__date__gte=start, changed_at__date__lte=end).values("opportunity")
        .distinct().count(),
        "daily_reports": DailyReport.objects.filter(employee_id=uid, report_date__gte=start, report_date__lte=end,
                                                    status__in=["submitted", "reviewed"]).count(),
    }
    return {"leads": leads, "visits": visits, "sales": sales, "followups": followups, "activity": activity,
            "chart": activity_chart(uid, start, end)}


def activity_chart(uid, start, end):
    """Leads created, visits completed and quotations created per day (≤ 62 days) or per month."""
    from leads.models import Lead
    from quotations.models import Quotation
    from visits.models import Visit

    days = (end - start).days + 1
    by_month = days > 62

    def key(d):
        return d.strftime("%Y-%m") if by_month else d.isoformat()

    buckets = []
    if by_month:
        d = start.replace(day=1)
        while d <= end:
            buckets.append(key(d))
            d = (d + datetime.timedelta(days=32)).replace(day=1)
    else:
        buckets = [key(start + datetime.timedelta(days=i)) for i in range(days)]
    series = {"Leads created": defaultdict(int), "Visits completed": defaultdict(int),
              "Quotations created": defaultdict(int)}
    for dt in Lead.objects.filter(created_by_id=uid, created_at__date__gte=start,
                                  created_at__date__lte=end).values_list("created_at", flat=True):
        series["Leads created"][key(timezone.localtime(dt).date())] += 1
    for d in Visit.objects.filter(assigned_to_id=uid, status="completed", visit_date__gte=start,
                                  visit_date__lte=end).values_list("visit_date", flat=True):
        series["Visits completed"][key(d)] += 1
    for dt in Quotation.objects.filter(salesperson_id=uid, created_at__date__gte=start,
                                       created_at__date__lte=end).values_list("created_at", flat=True):
        series["Quotations created"][key(timezone.localtime(dt).date())] += 1
    labels = [b if by_month else datetime.date.fromisoformat(b).strftime("%d %b") for b in buckets]
    return {"labels": labels, "datasets": [{"label": name, "data": [vals.get(b, 0) for b in buckets]}
                                           for name, vals in series.items()]}
