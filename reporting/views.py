import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.permissions import capability_required, get_profile, has_capability, visible_user_ids
from core.crud import employees_visible_to
from core.params import get_date, get_int
from core.registry import search_providers

from . import dashboard as dash
from . import metrics


def dashboard_period(request):
    today = timezone.localdate()
    start = get_date(request.GET, "start") or today.replace(month=1, day=1)
    end = get_date(request.GET, "end") or today
    if end < start:
        start, end = end, start
    return start, end


def dashboard_employee(request):
    emp = get_int(request.GET, "employee")
    ids = visible_user_ids(request.user)
    if emp and (ids is None or emp in ids):
        return emp
    return None


def business_context(request):
    """Business part of the dashboard (cards, charts, work lists) for the logged-in user."""
    user = request.user
    start, end = dashboard_period(request)
    employee = dashboard_employee(request)
    figures = metrics.dashboard_figures(user, start, end, employee)
    ids = visible_user_ids(user)
    return {
        "start": start, "end": end, "employee_id": employee,
        "employees": employees_visible_to(user) if ids is None or len(ids) > 1 else [],
        "cards": dash.cards_for(user, figures, start, end, employee),
        "charts": dash.charts_for(user),
        "work_lists": dash.work_lists(user),
        "presets": [("This month", today_month()), ("This quarter", today_quarter()),
                    ("Year to date", (timezone.localdate().replace(month=1, day=1), timezone.localdate())),
                    ("Last 12 months", (timezone.localdate() - datetime.timedelta(days=365), timezone.localdate()))],
    }


def today_month():
    return metrics.month_range(timezone.localdate())


def today_quarter():
    return metrics.period_bounds("quarter", timezone.localdate())


@login_required
def chart_json(request, key):
    if get_profile(request.user) is None or not has_capability(request.user, "dashboard.view"):
        raise PermissionDenied
    if key not in dict(dash.charts_for(request.user)):
        raise Http404
    start, end = dashboard_period(request)
    data = dash.chart_data(request.user, key, start, end, dashboard_employee(request))
    if data is None:
        raise Http404
    return JsonResponse(data)


@login_required
def global_search(request):
    if get_profile(request.user) is None:
        raise PermissionDenied
    q = request.GET.get("q", "").strip()[:100]
    groups = []
    if len(q) >= 2:
        for provider in search_providers:
            if has_capability(request.user, provider["capability"]):
                results = provider["fn"](request.user, q)
                if results:
                    groups.append({"label": provider["label"], "results": results})
    return render(request, "reporting/search.html", {"q": q, "groups": groups,
                                                     "total": sum(len(g["results"]) for g in groups)})


@capability_required("reports.view")
def report_index(request):
    from .reports import REPORTS, report_groups

    return render(request, "reporting/index.html", {"groups": report_groups(request.user),
                                                    "count": len(REPORTS)})


@capability_required("reports.view")
def report_view(request, key):
    from .reports import get_report

    report = get_report(key)
    if report is None:
        raise Http404
    if not has_capability(request.user, report.capability):
        raise PermissionDenied
    return report.respond(request)
