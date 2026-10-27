from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts import capabilities as caps
from accounts.permissions import capability_required, has_capability
from core.audit import log_action
from core.crud import CrmFormMixin, active_employees
from core.params import get_choice, get_date, get_int
from reporting.metrics import period_bounds

from .models import KPIDefinition, SalesTarget
from .services import ranking, scorecard

User = get_user_model()
TEAM_ROLES = [caps.ENGINEER, caps.COORDINATOR, caps.DIRECTOR]


def _period(request):
    ptype = get_choice(request.GET, "period", ["month", "quarter", "year"], "month")
    ref = get_date(request.GET, "date") or timezone.localdate()
    return ptype, ref


@capability_required("targets.view")
def overview(request):
    u = request.user
    ptype, ref = _period(request)
    team = has_capability(u, "team.view")
    employees = list(active_employees(TEAM_ROLES)) if team else [u]
    emp_id = get_int(request.GET, "employee")
    if emp_id == 0 and team:
        subject = None  # company
    elif emp_id and team:
        subject = next((e for e in employees if e.pk == emp_id), u)
    else:
        subject = u if not team else (None if emp_id is None else u)
    card = scorecard(subject, ptype, ref)
    start, end = card["start"], card["end"]
    return render(request, "performance/overview.html", {
        "card": card, "subject": subject, "ptype": ptype, "ref": ref, "team": team, "employees": employees,
        "employee_id": emp_id, "ranking": ranking(employees, ptype, ref) if team else None,
        "start": start, "end": end, "can_manage": has_capability(u, "targets.manage"),
        "periods": [("month", "Month"), ("quarter", "Quarter"), ("year", "Year")],
    })


class TargetSetForm(CrmFormMixin, forms.Form):
    employee = forms.ModelChoiceField(queryset=User.objects.none(), required=False,
                                      empty_label="Company-wide (all employees)")
    period_type = forms.ChoiceField(choices=SalesTarget.Period.choices)
    period_date = forms.DateField(label="Any date in the period", help_text="E.g. any day of the month you set.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].queryset = active_employees(TEAM_ROLES)
        self.fields["employee"].label_from_instance = lambda x: x.get_full_name() or x.username


@capability_required("targets.manage")
def set_targets(request):
    kpis = list(KPIDefinition.objects.filter(is_active=True))
    form = TargetSetForm(request.POST or request.GET or None, user=request.user,
                         initial={"period_type": "month", "period_date": timezone.localdate()})
    values, errors = {}, []
    start = None
    if form.is_bound and form.is_valid():
        d = form.cleaned_data
        start, _ = period_bounds(d["period_type"], d["period_date"])
        existing = {t.kpi_id: t for t in SalesTarget.objects.filter(employee=d["employee"],
                                                                    period_type=d["period_type"], period_start=start)}
        values = {k.pk: (existing[k.pk].target_value if k.pk in existing else "") for k in kpis}
        if request.method == "POST":
            changed = []
            for k in kpis:
                raw = request.POST.get(f"kpi_{k.pk}", "").strip()
                values[k.pk] = raw
                if raw == "":
                    if k.pk in existing:
                        existing[k.pk].delete()
                        changed.append(f"{k.name}: removed")
                    continue
                try:
                    val = Decimal(raw)
                except InvalidOperation:
                    errors.append(f"{k.name}: enter a number.")
                    continue
                t = existing.get(k.pk) or SalesTarget(employee=d["employee"], kpi=k, period_type=d["period_type"],
                                                      period_start=start)
                t.target_value = val
                try:
                    t.full_clean()
                except ValidationError as exc:
                    errors.extend(f"{k.name}: {m}" for m in exc.messages)
                    continue
                t.save()
                changed.append(f"{k.name}: {val}")
            if not errors:
                who = d["employee"].get_full_name() if d["employee"] else "Company"
                log_action("update", None, message=f"Targets set for {who}, {d['period_type']} {start}: "
                                                   + "; ".join(changed))
                messages.success(request, f"Targets saved for {who} ({start:%b %Y} {d['period_type']}).")
                return redirect(f"{request.path}?employee={d['employee'].pk if d['employee'] else ''}"
                                f"&period_type={d['period_type']}&period_date={d['period_date']:%Y-%m-%d}")
    return render(request, "performance/set_targets.html", {
        "form": form, "kpis": [(k, values.get(k.pk, "")) for k in kpis], "errors": errors, "start": start,
        "loaded": form.is_bound and form.is_valid()})


class KPIForm(CrmFormMixin, forms.ModelForm):
    class Meta:
        model = KPIDefinition
        fields = ["name", "weight", "is_active", "sort_order"]


@capability_required("targets.manage")
def kpi_definitions(request):
    kpis = KPIDefinition.objects.all()
    total = sum((k.weight for k in kpis if k.is_active), Decimal(0))
    return render(request, "performance/kpis.html", {"kpis": kpis, "total_weight": total})


@capability_required("targets.manage")
def kpi_edit(request, pk):
    kpi = get_object_or_404(KPIDefinition, pk=pk)
    form = KPIForm(request.POST or None, instance=kpi, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{kpi.name} saved.")
        return redirect("performance:kpis")
    return render(request, "crud/form.html", {"form": form, "title": f"KPI — {kpi.name}",
                                              "cancel_url": reverse("performance:kpis")})


@capability_required("targets.view")
def target_list(request):
    u = request.user
    qs = SalesTarget.objects.select_related("employee", "kpi")
    if not has_capability(u, "team.view"):
        qs = qs.filter(employee=u)
    emp = get_int(request.GET, "employee")
    if emp:
        qs = qs.filter(employee_id=emp)
    ptype = get_choice(request.GET, "period", ["month", "quarter", "year"])
    if ptype:
        qs = qs.filter(period_type=ptype)
    year = get_int(request.GET, "year")
    if year:
        qs = qs.filter(period_start__year=year)
    if request.method == "POST":
        if not has_capability(u, "targets.manage"):
            raise PermissionDenied
        t = get_object_or_404(SalesTarget, pk=get_int(request.POST, "delete"))
        log_action("delete", t, message=f"Target deleted: {t}")
        t.delete()
        messages.success(request, "Target deleted.")
        return redirect(request.get_full_path())
    return render(request, "performance/targets.html", {
        "targets": qs[:500], "employees": active_employees(TEAM_ROLES) if has_capability(u, "team.view") else [],
        "can_manage": has_capability(u, "targets.manage")})
