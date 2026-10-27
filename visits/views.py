import datetime

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import capability_required, has_capability, scope_queryset
from core import activity
from core.calendar_utils import build_month, month_from_request
from core.crud import (ChoiceFilter, Column, CrmCreateView, CrmListView, CrmUpdateView, DateRangeFilter,
                       ModelFilter, UserFilter, badge, employees_visible_to, get_scoped_or_404)
from core.models import LookupValue
from core.params import get_date, get_int
from tasks.services import create_follow_up

from .forms import CancelForm, CompleteForm, RescheduleForm, VisitForm
from .models import OWNER_FIELDS, Visit

TABS = [("List", "visits:list", "list-ul"), ("Calendar", "visits:calendar", "calendar3"),
        ("Week", "visits:schedule", "calendar-week")]


def status_cell(v):
    label = "Missed" if v.is_missed else v.get_status_display()
    return badge(label, v.tone())


class VisitList(CrmListView):
    model = Visit
    capability = "visits.view"
    title = "Customer visits"
    icon = "calendar-check"
    owner_fields = OWNER_FIELDS
    archive_field = None
    search_fields = ("code", "customer__company_name", "contact_person", "location", "site_name", "agenda")
    create_url = "visits:create"
    create_capability = "visits.create"
    create_label = "Schedule visit"
    view_tabs = TABS
    current_tab = "visits:list"
    columns = [
        Column("Visit", "code", link=True),
        Column("Date", "visit_date", date=True),
        Column("Time", lambda v: f"{v.start_time:%H:%M}–{v.end_time:%H:%M}"),
        Column("Customer", "customer.company_name"),
        Column("Purpose", "purpose"),
        Column("Location", "location"),
        Column("Employee", "assigned_to"),
        Column("Status", render=status_cell, text=lambda v: "Missed" if v.is_missed else v.get_status_display()),
    ]
    sort_options = {
        "date_desc": ("Date (newest first)", ["-visit_date", "-start_time"]),
        "date_asc": ("Date (oldest first)", ["visit_date", "start_time"]),
    }
    default_sort = "date_desc"

    def base_queryset(self):
        return Visit.objects.select_related("customer", "purpose", "assigned_to")

    def get_filters(self):
        today = timezone.localdate()
        return [
            ChoiceFilter("state", "Show", [("upcoming", "Upcoming"), ("missed", "Missed"),
                                           ("completed", "Completed"), ("cancelled", "Cancelled")],
                         lookups={"upcoming": Q(status__in=Visit.UPCOMING_STATUSES, visit_date__gte=today),
                                  "missed": Q(status__in=Visit.UPCOMING_STATUSES, visit_date__lt=today),
                                  "completed": Q(status="completed"), "cancelled": Q(status="cancelled")}),
            ChoiceFilter("status", "Status", Visit.Status.choices),
            ModelFilter("purpose", "Purpose", lambda: LookupValue.objects.filter(category="visit_purpose")),
            UserFilter("employee", "Employee", ["assigned_to"]),
            DateRangeFilter("date", "Visit date", "visit_date"),
        ]

    def summary(self, qs):
        today = timezone.localdate()
        base = self.scope(Visit.objects.all())
        month_start = today.replace(day=1)
        return [
            ("Upcoming", base.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__gte=today).count()),
            ("Missed (not completed)", base.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__lt=today).count()),
            ("Completed this month", base.filter(status="completed", visit_date__gte=month_start).count()),
            ("Today", base.filter(visit_date=today).exclude(status="cancelled").count()),
        ]


def _scoped(request):
    qs = scope_queryset(Visit.objects.select_related("customer", "assigned_to"), request.user, OWNER_FIELDS)
    emp = get_int(request.GET, "employee")
    if emp:
        qs = qs.filter(assigned_to_id=emp)
    return qs


@capability_required("visits.view")
def visit_calendar(request):
    year, month = month_from_request(request)
    probe = build_month(year, month, [])
    qs = _scoped(request).filter(visit_date__gte=probe["start"], visit_date__lte=probe["end"]).exclude(
        status="cancelled")
    events = [{"date": v.visit_date, "title": f"{v.start_time:%H:%M} {v.customer.company_name}",
               "url": v.get_absolute_url(), "tone": v.tone()} for v in qs.order_by("visit_date", "start_time")]
    return render(request, "visits/calendar.html", {
        "cal": build_month(year, month, events), "tabs": _tabs("visits:calendar"),
        "employees": employees_visible_to(request.user), "employee": get_int(request.GET, "employee"),
    })


@capability_required("visits.view")
def visit_schedule(request):
    """Daily / weekly schedule: one column per day, per employee filter."""
    start = get_date(request.GET, "start") or timezone.localdate()
    start = start - datetime.timedelta(days=start.weekday())  # Monday
    days = [start + datetime.timedelta(days=i) for i in range(7)]
    qs = _scoped(request).filter(visit_date__gte=days[0], visit_date__lte=days[-1]).order_by("start_time")
    by_day = {d: [] for d in days}
    for v in qs:
        by_day[v.visit_date].append(v)
    return render(request, "visits/schedule.html", {
        "days": [(d, by_day[d]) for d in days], "tabs": _tabs("visits:schedule"),
        "prev": days[0] - datetime.timedelta(days=7), "next": days[0] + datetime.timedelta(days=7),
        "employees": employees_visible_to(request.user), "employee": get_int(request.GET, "employee"),
        "today": timezone.localdate(),
    })


def _tabs(current):
    return [(label, reverse(url), icon, url == current) for label, url, icon in TABS]


class VisitCreate(CrmCreateView):
    model = Visit
    form_class = VisitForm
    capability = "visits.create"
    title = "Schedule visit"
    success_message = "Visit {obj} scheduled."
    cancel_url = "visits:list"

    def form_valid(self, form):
        response = super().form_valid(form)
        v = self.object
        activity.record(v, "visit", f"Visit scheduled for {v.visit_date:%d-%b-%Y} {v.start_time:%H:%M} "
                                    f"with {v.assigned_to.get_full_name()}", customer=v.customer)
        if v.assigned_to != self.request.user:
            from notifications.services import notify

            notify([v.assigned_to], "visit_assigned", f"Visit scheduled: {v.customer.company_name}",
                   f"{v.visit_date:%d-%b-%Y} {v.start_time:%H:%M}, {v.location}", v.get_absolute_url())
        return response


class VisitUpdate(CrmUpdateView):
    model = Visit
    form_class = VisitForm
    capability = "visits.edit"
    owner_fields = OWNER_FIELDS
    locked_message = "Completed or cancelled visits cannot be edited."

    def can_edit(self, obj):
        return obj.status in Visit.UPCOMING_STATUSES


@capability_required("visits.view")
def visit_detail(request, pk):
    visit = get_scoped_or_404(Visit, request.user, pk, OWNER_FIELDS)
    can_edit = has_capability(request.user, "visits.edit")
    return render(request, "visits/detail.html", {
        "visit": visit, "can_edit": can_edit and visit.status in Visit.UPCOMING_STATUSES,
        "activities": activity.for_object(visit, request.user)[:20],
        "tasks": visit.tasks.select_related("assigned_to") if has_capability(request.user, "tasks.view") else [],
    })


def _get_editable(request, pk):
    visit = get_scoped_or_404(Visit, request.user, pk, OWNER_FIELDS)
    if visit.status not in Visit.UPCOMING_STATUSES:
        raise PermissionDenied("This visit is already completed or cancelled.")
    return visit


@capability_required("visits.edit")
def visit_complete(request, pk):
    """Completing is always an explicit user action with meeting notes (never automatic)."""
    visit = _get_editable(request, pk)
    form = CompleteForm(request.POST or None, instance=visit, user=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            visit = form.save(commit=False)
            visit.status = Visit.Status.COMPLETED
            visit.completed_at = timezone.now()
            visit.completed_by = request.user
            visit.save()
            d = form.cleaned_data
            visit.customer.touch_contact(visit.visit_date, d.get("next_follow_up_date"))
            if visit.lead_id:
                type(visit.lead).objects.filter(pk=visit.lead_id).update(last_contact_date=visit.visit_date)
            activity.record(visit, "visit", f"Visit completed: {visit.meeting_notes[:150]}", customer=visit.customer)
            if d.get("create_task"):
                create_follow_up(title=f"Follow up visit {visit.code}: {visit.customer.company_name}",
                                 assigned_to=d["next_follow_up_owner"], due_date=d["next_follow_up_date"],
                                 description=visit.agreed_actions, customer=visit.customer, visit=visit,
                                 opportunity=visit.opportunity, lead=visit.lead)
            if d.get("update_opportunity") and visit.opportunity_id:
                opp = visit.opportunity
                opp.next_action = d["update_opportunity"]
                if d.get("next_follow_up_date"):
                    opp.next_follow_up = d["next_follow_up_date"]
                opp.save(update_fields=["next_action", "next_follow_up", "updated_at", "updated_by"])
                activity.record(opp, "updated", f"Next action from visit {visit.code}: {opp.next_action}")
        messages.success(request, f"Visit {visit.code} completed.")
        if d.get("schedule_next"):
            return redirect(reverse("visits:create") + f"?customer={visit.customer_id}"
                            + (f"&opportunity={visit.opportunity_id}" if visit.opportunity_id else ""))
        return redirect(visit.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Complete visit {visit.code} — "
                                                                      f"{visit.customer.company_name}",
                                              "cancel_url": visit.get_absolute_url(), "submit_label": "Complete visit"})


@capability_required("visits.edit")
def visit_reschedule(request, pk):
    visit = _get_editable(request, pk)
    form = RescheduleForm(request.POST or None, user=request.user, initial={
        "visit_date": visit.visit_date, "start_time": visit.start_time, "end_time": visit.end_time})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        old = visit.visit_date
        visit.previous_date = old
        visit.visit_date, visit.start_time, visit.end_time = d["visit_date"], d["start_time"], d["end_time"]
        visit.status = Visit.Status.RESCHEDULED
        visit.save()
        activity.record(visit, "status", f"Rescheduled from {old:%d-%b-%Y} to {visit.visit_date:%d-%b-%Y}"
                                         + (f" ({d['reason']})" if d["reason"] else ""), customer=visit.customer)
        messages.success(request, f"Visit {visit.code} rescheduled to {visit.visit_date:%d-%b-%Y}.")
        return redirect(visit.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Reschedule visit {visit.code}",
                                              "cancel_url": visit.get_absolute_url()})


@capability_required("visits.edit")
def visit_cancel(request, pk):
    visit = _get_editable(request, pk)
    form = CancelForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        visit.status = Visit.Status.CANCELLED
        visit.cancel_reason = form.cleaned_data["reason"]
        visit.save()
        activity.record(visit, "status", f"Visit cancelled: {visit.cancel_reason}", customer=visit.customer)
        messages.success(request, f"Visit {visit.code} cancelled.")
        return redirect(visit.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Cancel visit {visit.code}",
                                              "cancel_url": visit.get_absolute_url(), "submit_label": "Cancel visit"})


@capability_required("visits.edit")
def visit_confirm(request, pk):
    visit = _get_editable(request, pk)
    if request.method != "POST":
        raise PermissionDenied
    visit.status = Visit.Status.CONFIRMED
    visit.save()
    activity.record(visit, "status", "Visit confirmed with the customer", customer=visit.customer)
    messages.success(request, f"Visit {visit.code} confirmed.")
    return redirect(visit.get_absolute_url())
