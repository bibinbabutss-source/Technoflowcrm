"""Owner Dashboard, Pending Approvals, Team Calendar and Modules & Approvals settings. Access checked on the server."""
import datetime
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import capability_required, has_capability
from core.audit import log_action
from core.calendar_utils import build_month, month_from_request
from core.crud import employees_visible_to, person
from core.forms import BootstrapMixin
from core.models import CompanyProfile
from core.params import get_choice, get_date, get_int
from performance import monitoring as mon

from . import calendar as cal
from .rules import may_approve, owner_exists

ZERO = Decimal("0.00")


def _period(request):
    preset = get_choice(request.GET, "period", [k for k, _ in mon.PRESETS], "this_month")
    start, end, preset = mon.period_for(preset, start=get_date(request.GET, "start"), end=get_date(request.GET, "end"))
    return start, end, preset


# ---------------------------------------------------------------- Owner Dashboard
@capability_required("owner.dashboard")
def dashboard(request):
    from leads.models import Lead
    from quotations.models import Quotation, QuotationRevision
    from sales.models import Opportunity
    from tasks.models import Task
    from visits.models import Visit

    start, end, preset = _period(request)
    today = timezone.localdate()
    tp = get_choice(request.GET, "tp", ["month", "quarter", "year"], "month")
    leads = Lead.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    cats = dict(leads.values_list("category").annotate(n=Count("pk")))
    won = Opportunity.objects.filter(stage__is_won=True, closed_at__date__gte=start, closed_at__date__lte=end)
    open_opps = Opportunity.objects.filter(is_archived=False, stage__is_won=False, stage__is_lost=False)
    pipeline = open_opps.aggregate(v=Sum("estimated_value"))["v"] or ZERO
    weighted = sum((o.weighted_value for o in open_opps.only("estimated_value", "probability")), ZERO)
    pending = QuotationRevision.objects.filter(status="submitted").select_related(
        "quotation__customer", "quotation__salesperson", "submitted_by").order_by("submitted_at")
    overdue_tasks = Task.objects.filter(status__in=Task.OPEN_STATUSES, due_date__lt=today).count()
    missed = Visit.objects.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__lt=today).count()
    late_leads = Lead.objects.filter(is_archived=False, stage__is_won=False, stage__is_lost=False,
                                     next_follow_up__lt=today).count()
    cards = [
        {"label": "Won revenue", "value": won.aggregate(v=Sum("estimated_value"))["v"] or ZERO, "money": True,
         "sub": f"{won.count()} opportunities won in the period", "tone": "green", "icon": "trophy",
         "url": reverse("sales:pipeline") + "?state=won"},
        {"label": "Open pipeline", "value": pipeline, "money": True, "now": True,
         "sub": f"weighted {weighted:,.2f} · {open_opps.count()} open", "tone": "blue", "icon": "kanban",
         "url": reverse("sales:kanban")},
        {"label": "Leads created", "value": leads.count(), "sub": (
            f"Job in Hand {cats.get('job_in_hand', 0)} · Tender {cats.get('tender', 0)} · "
            f"Purchase Enquiry {cats.get('purchase_enquiry', 0)}"), "tone": "brand", "icon": "funnel",
         "url": reverse("leads:list") + f"?created_from={start:%Y-%m-%d}&created_to={end:%Y-%m-%d}"},
        {"label": "Visits completed", "value": Visit.objects.filter(
            status="completed", visit_date__gte=start, visit_date__lte=end).count(),
         "sub": f"{Visit.objects.filter(visit_date__gte=start, visit_date__lte=end).exclude(status='cancelled').count()}"
                " planned in the period", "tone": "green", "icon": "geo-alt",
         "url": reverse("visits:list") + f"?status=completed&date_from={start:%Y-%m-%d}&date_to={end:%Y-%m-%d}"},
        {"label": "Quotations", "value": Quotation.objects.filter(created_at__date__gte=start,
                                                                  created_at__date__lte=end).count(),
         "sub": f"{QuotationRevision.objects.filter(version__gt=1, created_at__date__gte=start, created_at__date__lte=end).count()}"
                " revisions in the period", "tone": "blue", "icon": "file-earmark-text",
         "url": reverse("quotations:list")},
        {"label": "Pending approvals", "value": pending.count(), "now": True, "sub": "waiting for your decision",
         "tone": "orange" if pending.exists() else "green", "icon": "patch-check", "url": reverse("owner:approvals")},
        {"label": "Overdue activities", "value": overdue_tasks + missed + late_leads, "now": True,
         "sub": f"{overdue_tasks} tasks · {missed} missed visits · {late_leads} lead follow-ups",
         "tone": "red" if (overdue_tasks + missed + late_leads) else "green", "icon": "alarm",
         "url": reverse("tasks:list") + "?show=team&state=overdue"},
    ]
    employees = list(mon.sales_employees())
    figs = mon.list_figures([u.pk for u in employees], start, end, target_period=tp)
    rows = []
    for u in employees:
        f = figs[u.pk]
        label, tone = mon.TARGET_STATUS[f["target_status"]]
        rows.append({"user": u, "profile": u.profile, **f, "status_label": label, "status_tone": tone})
    rows.sort(key=lambda r: (r["won_value"], r["deals_won"]), reverse=True)
    achieved = sum(1 for r in rows if r["target_status"] == "achieved")
    with_target = sum(1 for r in rows if r["target_status"] != "none")
    if rows:
        t_start, t_end = rows[0]["target_month"], rows[0]["target_end"]
    else:
        from reporting.metrics import period_bounds

        t_start, t_end = period_bounds(tp, end)
    chart = {
        "labels": [person(r["user"]) for r in rows],
        "datasets": [
            {"label": "Target", "data": [float(r["target"] or 0) for r in rows]},
            {"label": "Won revenue", "data": [float(r["target_actual"] or 0) for r in rows]},
            {"label": "Open pipeline due in the target period", "data": [float(r["pipeline_in_target_period"])
                                                                         for r in rows]},
        ]}
    return render(request, "owner/dashboard.html", {
        "cards": cards, "rows": rows, "totals": mon.totals(rows), "pending": pending[:6],
        "pending_count": pending.count(), "start": start, "end": end, "preset": preset, "presets": mon.PRESETS,
        "tp": tp, "t_start": t_start, "t_end": t_end, "achieved": achieved, "with_target": with_target,
        "chart_list": [{"id": "targets", "title": "Targets", "type": "bar", "money": True, "links": [
            reverse("team:employee", args=[r["user"].pk]) for r in rows], **chart}],
        "owner_ok": owner_exists(), "today": today,
        "keep": _keep(request),
    })


# ---------------------------------------------------------------- Pending Approvals
@capability_required("approvals.view")
def approvals(request):
    from quotations.models import Approval, QuotationRevision

    allowed, why = may_approve(request.user)
    pending = (QuotationRevision.objects.filter(status="submitted")
               .select_related("quotation__customer", "quotation__salesperson", "quotation__opportunity",
                               "submitted_by").order_by("submitted_at"))
    recent = (Approval.objects.exclude(decision="auto").select_related(
        "revision__quotation__customer", "decided_by").order_by("-decided_at")[:20])
    items = []
    for rev in pending:
        q = rev.quotation
        doc = None
        if q.is_uploaded:
            doc = reverse("quotations:file", args=[q.pk, rev.version])
        elif has_capability(request.user, "quotations.view"):
            doc = reverse("quotations:pdf", args=[q.pk]) + f"?rev={rev.version}"
        items.append({"rev": rev, "q": q, "doc": doc,
                      "waiting": timezone.now() - rev.submitted_at if rev.submitted_at else None,
                      "own": request.user.pk in (q.salesperson_id, rev.created_by_id, rev.submitted_by_id)})
    return render(request, "owner/approvals.html", {
        "items": items, "recent": recent, "can_decide": allowed, "why": why,
        "backup": CompanyProfile.get().director_backup_approval, "owner_ok": owner_exists()})


# ---------------------------------------------------------------- Team Calendar
@capability_required("calendar.view")
def calendar_view(request):
    view = get_choice(request.GET, "view", ["month", "list"], "month")
    types = [t for t in request.GET.getlist("type") if t in dict(cal.TYPES)] or None
    emp = get_int(request.GET, "employee")
    employees = list(employees_visible_to(request.user).filter(is_active=True))
    if emp and emp not in {u.pk for u in employees}:
        emp = None
    if view == "list":
        start = get_date(request.GET, "start") or timezone.localdate()
        end = get_date(request.GET, "end") or start + datetime.timedelta(days=13)
        if end < start:
            start, end = end, start
        end = min(end, start + datetime.timedelta(days=92))
        events = cal.events(request.user, start, end, [emp] if emp else None, types)
        month = None
    else:
        year, month_no = month_from_request(request)
        probe = build_month(year, month_no, [])
        events = cal.events(request.user, probe["start"], probe["end"], [emp] if emp else None, types)
        month = build_month(year, month_no, [{**e, "title": (e["title"] if emp else f"{e['who']}: {e['title']}")
                                              + f" ({e['status_label']})"} for e in events])
        start, end = probe["start"], probe["end"]
    counts = {k: sum(1 for e in events if e["status"] == k) for k in cal.STATUS_LABEL}
    return render(request, "owner/calendar.html", {
        "view": view, "cal": month, "events": events, "employees": employees, "employee": emp,
        "types": cal.TYPES, "selected_types": types or [t for t, _ in cal.TYPES], "start": start, "end": end,
        "counts": counts, "status_labels": cal.STATUS_LABEL, "status_tone": cal.STATUS_TONE,
        "selected_employee": next((u for u in employees if u.pk == emp), None)})


# ---------------------------------------------------------------- Modules & Approvals
class ModulesForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = ["finance_enabled", "director_backup_approval", "approval_threshold", "discount_approval_limit"]


@capability_required("modules.manage")
def modules(request):
    company = CompanyProfile.get()
    form = ModulesForm(request.POST or None, instance=company)
    if request.method == "POST" and form.is_valid():
        changed = list(form.changed_data)
        form.save()
        if changed:
            log_action("update", company, message="Modules & approvals changed: " + ", ".join(
                f"{form.fields[f].label} = {form.cleaned_data[f]}" for f in changed)[:450])
        messages.success(request, "Settings saved." + (" The Finance module is now hidden and blocked; no records "
                                                       "were deleted." if "finance_enabled" in changed
                                                       and not company.finance_enabled else ""))
        return redirect("owner:modules")
    return render(request, "owner/modules.html", {"form": form, "owner_ok": owner_exists()})


def _keep(request):
    """The current query string without the period fields (used by the period chips)."""
    keep = request.GET.copy()
    for k in ("period", "start", "end", "page"):
        keep.pop(k, None)
    return keep.urlencode()
