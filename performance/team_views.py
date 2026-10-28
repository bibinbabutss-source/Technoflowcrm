"""Employee Performance (list + individual dashboards) and daily work reports. Access is checked on the server."""
import datetime

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.forms import inlineformset_factory
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required, has_capability
from core.crud import CrmFormMixin, person
from core.exports import csv_response, xlsx_response
from core.params import get_choice, get_date, get_int
from core.related import apply_related_fields
from core.scopes import owners

from . import monitoring as mon
from .models import DailyReport, DailyReportEntry

User = get_user_model()

SORTS = {
    "name": ("Name", None),
    "won_value": ("Won value", "won_value"),
    "deals_won": ("Deals won", "deals_won"),
    "leads_created": ("Leads created", "leads_created"),
    "visits_completed": ("Visits completed", "visits_completed"),
    "achievement": ("Target achievement", "achievement"),
}


def _period(request):
    preset = get_choice(request.GET, "period", [k for k, _ in mon.PRESETS], "this_month")
    start, end, preset = mon.period_for(preset, start=get_date(request.GET, "start"), end=get_date(request.GET, "end"))
    return start, end, preset


def _period_ctx(request, start, end, preset):
    keep = request.GET.copy()
    for k in ("period", "start", "end", "page"):
        keep.pop(k, None)
    return {"start": start, "end": end, "preset": preset, "presets": mon.PRESETS, "keep": keep.urlencode()}


# ------------------------------------------------------------------ employee list
@capability_required("performance.view")
def team(request):
    u = request.user
    if not has_capability(u, "employees.monitor"):
        return redirect("team:employee", pk=u.pk)
    start, end, preset = _period(request)
    ids = mon.monitorable_ids(u)
    status = get_choice(request.GET, "status", ["active", "inactive", "all"], "active")
    qs = mon.sales_employees(include_inactive=status != "active")
    if status == "inactive":
        qs = qs.filter(is_active=False)
    if ids is not None:
        qs = qs.filter(pk__in=ids)
    all_visible = list(qs)
    q = request.GET.get("q", "").strip()[:80]
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q) |
                       Q(profile__employee_id__icontains=q))
    designation = request.GET.get("designation", "").strip()[:100]
    if designation:
        qs = qs.filter(Q(profile__job_title=designation) | Q(profile__role__name=designation))
    department = request.GET.get("department", "").strip()[:100]
    if department:
        qs = qs.filter(profile__department=department)
    manager = get_int(request.GET, "manager")
    if manager:
        qs = qs.filter(profile__reporting_manager__user_id=manager)
    employee = get_int(request.GET, "employee")
    if employee:
        qs = qs.filter(pk=employee)
    employees = list(qs)
    figures = mon.list_figures([e.pk for e in employees], start, end)
    rows = [{"user": e, "profile": e.profile, **figures[e.pk]} for e in employees]
    sort = get_choice(request.GET, "sort", list(SORTS), "won_value")
    key = SORTS[sort][1]
    if key:
        rows.sort(key=lambda r: (r[key] is None, -(r[key] or 0), (r["user"].get_full_name() or "").lower()))
    else:
        rows.sort(key=lambda r: (r["user"].get_full_name() or r["user"].username).lower())
    total = mon.totals(rows)
    fmt = request.GET.get("export")
    if fmt in ("csv", "xlsx"):
        if not has_capability(u, "data.export"):
            raise PermissionDenied
        headers = ["Employee", "Employee ID", "Designation", "Department", "Reporting manager", "Status",
                   "Leads created", "Open leads (now)", "Visits completed", "Quotations created", "Deals won",
                   "Deals lost", "Won value", "Monthly target (won value)", "Achievement %",
                   "Pending follow-ups (now)", "Last activity"]
        data = [[person(r["user"]), r["profile"].employee_id, r["profile"].job_title or r["profile"].role.name,
                 r["profile"].department, person(r["profile"].reporting_manager.user)
                 if r["profile"].reporting_manager else "", "Active" if r["user"].is_active else "Inactive",
                 r["leads_created"], r["open_leads"], r["visits_completed"], r["quotations_created"], r["deals_won"],
                 r["deals_lost"], r["won_value"], r["target"] if r["target"] is not None else "",
                 r["achievement"] if r["achievement"] is not None else "", r["pending_followups"],
                 timezone.localtime(r["last_activity"]).strftime("%d-%m-%Y %H:%M") if r["last_activity"] else ""]
                for r in rows]
        name = f"employee_performance_{start:%Y%m%d}_{end:%Y%m%d}"
        return csv_response(name, headers, data) if fmt == "csv" else xlsx_response(name, headers, data)
    page = Paginator(rows, 25).get_page(request.GET.get("page"))
    profiles = [e.profile for e in all_visible]
    return render(request, "performance/team.html", {
        "rows": page, "page": page, "total": total, "count": len(rows), "q": q, "sort": sort, "sorts": SORTS,
        "status": status, "designation": designation, "department": department, "manager": manager,
        "employee": employee, "all_employees": all_visible,
        "designations": sorted({p.job_title or p.role.name for p in profiles}),
        "departments": sorted({p.department for p in profiles if p.department}),
        "managers": sorted({p.reporting_manager.user for p in profiles if p.reporting_manager},
                           key=lambda x: x.get_full_name()),
        "can_export": has_capability(u, "data.export"),
        **_period_ctx(request, start, end, preset)})


# ------------------------------------------------------------------ one employee
@capability_required("performance.view")
def employee(request, pk):
    emp = User.objects.filter(pk=pk, profile__isnull=False).select_related("profile__role").first()
    if emp is None or not mon.can_view_employee(request.user, emp):
        raise Http404  # same answer for "does not exist" and "not allowed": no information leaks
    start, end, preset = _period(request)
    data = mon.employee_dashboard(emp, start, end)
    from core.crud import money

    s, ld = data["sales"], data["leads"]
    text = {  # card sub-lines and values built here, so templates stay simple
        "won_lost": f"{s['won']} won · {s['lost']} lost",
        "open_breakdown": f"{ld['new_now']} new · {ld['contacted_now']} contacted",
        "conversion": f"{ld['conversion_rate']}%" if ld["conversion_rate"] is not None else "—",
        "lead_won_lost": f"{ld['won']} won · {ld['lost']} lost (closed in period)",
        "average_deal": money(s["average_deal"]) if s["average_deal"] is not None else "—",
        "rejected": f"{s['rejected']} rejected",
    }
    return render(request, "performance/employee.html", {
        "text": text, "today": timezone.localdate(),
        "emp": emp, "profile": emp.profile, "d": data, "is_self": emp.pk == request.user.pk,
        "can_monitor": has_capability(request.user, "employees.monitor"),
        "recent_reports": DailyReport.objects.filter(employee=emp).exclude(
            status=DailyReport.Status.DRAFT if emp.pk != request.user.pk else "-").order_by("-report_date")[:7],
        **_period_ctx(request, start, end, preset)})


@capability_required("performance.view")
def me(request):
    return redirect("team:employee", pk=request.user.pk)


# ------------------------------------------------------------------ daily reports
class DailyReportForm(CrmFormMixin, forms.ModelForm):
    class Meta:
        model = DailyReport
        fields = ["report_date", "calls_followups", "visits_outcomes", "quotations_prepared",
                  "opportunities_progressed", "tasks_completed", "pending_work", "challenges", "next_day_plan"]
        widgets = {f: forms.Textarea(attrs={"rows": 3}) for f in fields[1:]}

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        self.fields["report_date"].widget = forms.DateInput(attrs={"type": "date", "class": "form-control"},
                                                            format="%Y-%m-%d")

    def clean_report_date(self):
        d = self.cleaned_data["report_date"]
        if d > timezone.localdate():
            raise ValidationError("A daily report cannot be for a future date.")
        if (timezone.localdate() - d).days > 31:
            raise ValidationError("Reports can be written for the last 31 days only.")
        if DailyReport.objects.filter(employee=self.employee, report_date=d).exclude(pk=self.instance.pk).exists():
            raise ValidationError("You already have a report for this date. Open it from Daily Reports.")
        return d


class EntryForm(forms.ModelForm):
    class Meta:
        model = DailyReportEntry
        fields = ["kind", "customer", "lead", "description", "outcome"]
        widgets = {"kind": forms.Select(attrs={"class": "form-select form-select-sm"}),
                   "customer": forms.Select(attrs={"class": "form-select form-select-sm"}),
                   "lead": forms.Select(attrs={"class": "form-select form-select-sm"}),
                   "description": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
                   "outcome": forms.TextInput(attrs={"class": "form-control form-control-sm"})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        apply_related_fields(self, {
            "customer": ("customers.Customer", "customers.view", owners("customers.customer"), Q(is_archived=False)),
            "lead": ("leads.Lead", "leads.view", owners("leads.lead"), Q(is_archived=False)),
        })


EntryFormSet = inlineformset_factory(DailyReport, DailyReportEntry, form=EntryForm, extra=0, can_delete=True)


def _visible_report(request, pk):
    report = get_object_or_404(DailyReport.objects.select_related("employee"), pk=pk)
    if report.employee_id == request.user.pk:
        return report
    if report.status == DailyReport.Status.DRAFT:  # drafts are private until submitted
        raise Http404
    if has_capability(request.user, "employees.monitor"):
        ids = mon.monitorable_ids(request.user)
        if ids is None or report.employee_id in ids:
            return report
    raise Http404


@capability_required("dailyreports.submit")
def report_edit(request, pk=None):
    report = get_object_or_404(DailyReport, pk=pk, employee=request.user) if pk else None
    if report is not None and not report.is_editable:
        raise PermissionDenied("This report has been reviewed and can no longer be changed.")
    initial = {"report_date": get_date(request.GET, "date") or timezone.localdate()}
    form = DailyReportForm(request.POST or None, instance=report, employee=request.user, user=request.user,
                           initial=initial)
    draft = report or DailyReport(employee=request.user)
    entries = EntryFormSet(request.POST or None, instance=draft, prefix="entries",
                           form_kwargs={"user": request.user})
    if request.method == "POST" and form.is_valid() and entries.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.employee = request.user
            if request.POST.get("action") == "submit" and obj.status == DailyReport.Status.DRAFT:
                obj.status = DailyReport.Status.SUBMITTED
                obj.submitted_at = timezone.now()
            obj.save()
            entries.instance = obj
            position = 0
            for f in entries.forms:
                if not f.cleaned_data:
                    continue
                if f.cleaned_data.get("DELETE"):
                    if f.instance.pk:
                        f.instance.delete()
                    continue
                e = f.save(commit=False)
                position += 1
                e.report, e.position = obj, position
                e.save()
        messages.success(request, "Daily report submitted." if obj.status != "draft" else "Daily report saved "
                                                                                           "as draft.")
        return redirect(obj.get_absolute_url())
    return render(request, "performance/report_form.html", {"form": form, "entries": entries, "report": report})


class ReviewForm(forms.Form):
    review_comment = forms.CharField(widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
                                     required=False, label="Comment for the employee")


@capability_required("performance.view")
def report_detail(request, pk):
    report = _visible_report(request, pk)
    can_review = (report.employee_id != request.user.pk and has_capability(request.user, "employees.monitor")
                  and report.status == DailyReport.Status.SUBMITTED)
    form = ReviewForm(request.POST or None)
    if request.method == "POST":
        if not can_review:
            raise PermissionDenied("You cannot review this report.")
        if form.is_valid():
            report.status = DailyReport.Status.REVIEWED
            report.reviewed_by, report.reviewed_at = request.user, timezone.now()
            report.review_comment = form.cleaned_data["review_comment"]
            report.save()
            messages.success(request, "Report marked as reviewed.")
            return redirect(report.get_absolute_url())
    start, end = report.report_date, report.report_date
    tracked = mon.employee_dashboard(report.employee, start, end)
    return render(request, "performance/report_detail.html", {
        "report": report, "entries": report.entries.select_related("customer", "lead"), "form": form,
        "can_review": can_review, "can_edit": report.employee_id == request.user.pk and report.is_editable,
        "tracked": tracked, "history": _report_history(report)})


def _report_history(report):
    """Every recorded change to the report and its activity rows (from the append-only audit log)."""
    from django.contrib.contenttypes.models import ContentType

    from core.models import AuditLog

    labels = {f.name: str(f.verbose_name).capitalize() for f in DailyReport._meta.fields}
    labels.update({f"entry.{f.name}": "Activity " + str(f.verbose_name) for f in DailyReportEntry._meta.fields})
    rct, ect = ContentType.objects.get_for_model(DailyReport), ContentType.objects.get_for_model(DailyReportEntry)
    entry_ids = [str(i) for i in report.entries.values_list("pk", flat=True)]
    logs = (AuditLog.objects.filter(content_type=rct, object_id=str(report.pk))
            | AuditLog.objects.filter(content_type=ect, object_id__in=entry_ids)).select_related("user")
    rows = []
    for log in logs.order_by("timestamp", "id")[:200]:
        prefix = "entry." if log.content_type_id == ect.pk else ""
        changes = [(labels.get(prefix + k, k), "" if v[0] is None else str(v[0]), "" if v[1] is None else str(v[1]))
                   for k, v in (log.changes or {}).items()
                   if isinstance(v, (list, tuple)) and len(v) == 2 and k not in ("report", "position", "employee")]
        rows.append({"when": log.timestamp, "user": log.user, "action": log.get_action_display(),
                     "what": "Activity row" if prefix else "Report", "changes": changes})
    return rows


@require_POST
@capability_required("dailyreports.submit")
def report_delete(request, pk):
    report = get_object_or_404(DailyReport, pk=pk, employee=request.user)
    if report.status != DailyReport.Status.DRAFT:
        raise PermissionDenied("Only a draft report can be deleted.")
    report.delete()
    messages.success(request, "Draft report deleted.")
    return redirect("dailyreports:list")


@capability_required("performance.view")
def reports(request):
    """Own reports, and (for managers) the reports of the employees they monitor, with a period summary."""
    u = request.user
    start, end, preset = _period(request)
    ids = mon.monitorable_ids(u)
    qs = DailyReport.objects.select_related("employee").annotate(n=Count("entries"))
    if ids is not None:
        qs = qs.filter(employee_id__in=ids)
    emp = get_int(request.GET, "employee")
    if emp:
        qs = qs.filter(employee_id=emp)
    status = get_choice(request.GET, "status", ["", "draft", "submitted", "reviewed"], "")
    if status:
        qs = qs.filter(status=status)
    qs = qs.filter(report_date__gte=start, report_date__lte=end).exclude(
        Q(status="draft") & ~Q(employee=u))  # managers do not see unsubmitted drafts
    employees = mon.sales_employees()
    if ids is not None:
        employees = employees.filter(pk__in=ids)
    # summary per employee: reports submitted vs working days (Mon–Fri) up to today in the period
    last = min(end, timezone.localdate())
    working = sum(1 for i in range((last - start).days + 1)
                  if (start + datetime.timedelta(days=i)).weekday() < 5) if last >= start else 0
    summary = []
    for e in employees:
        if emp and e.pk != emp:
            continue
        mine = DailyReport.objects.filter(employee=e, report_date__gte=start, report_date__lte=end,
                                          status__in=["submitted", "reviewed"])
        kinds = dict(DailyReportEntry.objects.filter(report__in=mine).values_list("kind").annotate(c=Count("pk")))
        summary.append({"user": e, "submitted": mine.count(), "reviewed": mine.filter(status="reviewed").count(),
                        "working_days": working, "kinds": kinds,
                        "pct": round(mine.count() / working * 100) if working else None})
    page = Paginator(qs.order_by("-report_date", "employee__first_name"), 30).get_page(request.GET.get("page"))
    return render(request, "performance/reports.html", {
        "page": page, "summary": summary, "employees": employees, "emp": emp, "status": status,
        "kinds": DailyReportEntry.Kind.choices, "can_submit": has_capability(u, "dailyreports.submit"),
        "monitor": has_capability(u, "employees.monitor"), "working_days": working,
        "today_report": DailyReport.objects.filter(employee=u, report_date=timezone.localdate()).first(),
        **_period_ctx(request, start, end, preset)})


def reports_url_for(employee_id):
    return reverse("dailyreports:list") + f"?employee={employee_id}"
