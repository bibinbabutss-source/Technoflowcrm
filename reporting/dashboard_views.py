"""One page per module dashboard; the figures come from reporting.module_dashboards."""
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import render

from accounts.permissions import has_capability
from core.params import get_choice, get_date, get_int
from performance import monitoring as mon

from . import module_dashboards as md


def module_dashboard(request, module):
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path())
    spec = md.MODULES.get(module)
    if spec is None:
        raise Http404
    title, icon, cap, fn, list_url = spec
    if not has_capability(request.user, cap):
        raise PermissionDenied
    preset = get_choice(request.GET, "period", [k for k, _ in mon.PRESETS], "this_month")
    start, end, preset = mon.period_for(preset, start=get_date(request.GET, "start"), end=get_date(request.GET, "end"))
    employees = md.employees_for(request.user)
    emp = get_int(request.GET, "employee")
    if emp and emp not in {u.pk for u in employees}:
        emp = None
    cards, charts = fn(request.user, start, end, emp)
    return render(request, "reporting/module_dashboard.html", {
        "module": module, "title": title, "icon": icon, "list_url": list_url, "cards": cards, "charts": charts,
        "start": start, "end": end, "preset": preset, "presets": mon.PRESETS, "employees": employees,
        "employee": emp, "modules": md.allowed_modules(request.user),
        "keep": _keep(request)})


def _keep(request):
    """The current query string without the period fields (used by the period chips)."""
    keep = request.GET.copy()
    for k in ("period", "start", "end", "page"):
        keep.pop(k, None)
    return keep.urlencode()
