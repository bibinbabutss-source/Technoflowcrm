from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required, has_capability, scope_queryset
from core import activity
from core.calendar_utils import build_month, month_from_request
from core.crud import (ChoiceFilter, Column, CrmCreateView, CrmListView, CrmUpdateView, DateRangeFilter,
                       UserFilter, badge, get_scoped_or_404)

from .forms import CommentForm, TaskForm
from .models import OWNER_FIELDS, Task
from .services import notify_task_assigned

STATUS_TONE = {"open": "info", "in_progress": "warn", "waiting": "neutral", "completed": "good",
               "cancelled": "neutral"}
PRIORITY_TONE = {"urgent": "bad", "high": "bad", "medium": "warn", "low": "neutral"}
TABS = [("List", "tasks:list", "list-ul"), ("Calendar", "tasks:calendar", "calendar3")]


def due_cell(task):
    text = task.due_date.strftime("%d-%b-%Y")
    if task.is_overdue:
        return badge(f"{text} overdue", "bad")
    if task.is_open and task.due_date == timezone.localdate():
        return badge(f"{text} today", "warn")
    return text


def related_cell(task):
    records = task.related_records()
    return str(records[0]) if records else "—"


class TaskList(CrmListView):
    model = Task
    capability = "tasks.view"
    title = "Tasks & follow-ups"
    icon = "check2-square"
    owner_fields = OWNER_FIELDS
    archive_field = None
    search_fields = ("code", "title", "description", "customer__company_name", "lead__title")
    create_url = "tasks:create"
    create_capability = "tasks.create"
    create_label = "Add task"
    view_tabs = TABS
    current_tab = "tasks:list"
    columns = [
        Column("Task", "code", link=True),
        Column("Title", "title"),
        Column("Related to", render=related_cell, text=related_cell),
        Column("Assigned to", "assigned_to"),
        Column("Priority", render=lambda t: badge(t.get_priority_display(), PRIORITY_TONE[t.priority]),
               text=lambda t: t.get_priority_display()),
        Column("Due", render=due_cell, text=lambda t: t.due_date),
        Column("Status", render=lambda t: badge(t.get_status_display(), STATUS_TONE[t.status]),
               text=lambda t: t.get_status_display()),
    ]
    sort_options = {
        "due": ("Due date", ["due_date", "pk"]),
        "newest": ("Newest first", ["-created_at"]),
        "priority": ("Priority", ["priority", "due_date"]),
    }
    default_sort = "due"

    def get(self, request, *args, **kwargs):
        if not request.GET:
            return redirect(f"{request.path}?show=mine&state=open")
        return super().get(request, *args, **kwargs)

    def base_queryset(self):
        return Task.objects.select_related("assigned_to", "customer", "lead", "opportunity", "visit", "quotation",
                                           "invoice")

    def get_filters(self):
        user = self.request.user
        today = timezone.localdate()
        shows = [("mine", "My tasks"), ("created", "Created by me")]
        lookups = {"mine": Q(assigned_to=user), "created": Q(created_by=user)}
        if has_capability(user, "team.view") or user.profile.role.data_scope != "own":
            shows.append(("team", "Team (all I can see)"))
            lookups["team"] = Q()
        return [
            ChoiceFilter("show", "Show", shows, lookups=lookups),
            ChoiceFilter("state", "State", [("open", "Open"), ("overdue", "Overdue"), ("today", "Due today"),
                                            ("week", "Due in 7 days"), ("closed", "Completed / cancelled")],
                         lookups={"open": Q(status__in=Task.OPEN_STATUSES),
                                  "overdue": Q(status__in=Task.OPEN_STATUSES, due_date__lt=today),
                                  "today": Q(status__in=Task.OPEN_STATUSES, due_date=today),
                                  "week": Q(status__in=Task.OPEN_STATUSES, due_date__gte=today,
                                            due_date__lte=today + timezone.timedelta(days=7)),
                                  "closed": ~Q(status__in=Task.OPEN_STATUSES)}),
            ChoiceFilter("status", "Status", Task.Status.choices),
            ChoiceFilter("priority", "Priority", Task.Priority.choices),
            ChoiceFilter("category", "Category", Task.Category.choices),
            UserFilter("employee", "Assigned to", ["assigned_to"]),
            DateRangeFilter("due", "Due", "due_date"),
        ]

    def summary(self, qs):
        today = timezone.localdate()
        base = self.scope(Task.objects.filter(assigned_to=self.request.user, status__in=Task.OPEN_STATUSES))
        return [("My open tasks", base.count()), ("My overdue", base.filter(due_date__lt=today).count()),
                ("Due today", base.filter(due_date=today).count()),
                ("Due in 7 days", base.filter(due_date__gt=today,
                                              due_date__lte=today + timezone.timedelta(days=7)).count())]


@capability_required("tasks.view")
def task_calendar(request):
    year, month = month_from_request(request)
    qs = scope_queryset(Task.objects.all(), request.user, OWNER_FIELDS)
    if request.GET.get("show") != "team":
        qs = qs.filter(assigned_to=request.user)
    cal_probe = build_month(year, month, [])
    qs = qs.filter(due_date__gte=cal_probe["start"], due_date__lte=cal_probe["end"])
    events = [{"date": t.due_date, "title": f"{t.title}", "url": t.get_absolute_url(),
               "tone": "good" if t.status == "completed" else "bad" if t.is_overdue else
               "warn" if t.priority in ("high", "urgent") else ""} for t in qs]
    return render(request, "tasks/calendar.html", {
        "cal": build_month(year, month, events),
        "view_tabs": [(label, reverse(url), icon, url == "tasks:calendar") for label, url, icon in TABS],
        "show": request.GET.get("show", "mine"),
    })


class TaskCreate(CrmCreateView):
    model = Task
    form_class = TaskForm
    capability = "tasks.create"
    title = "Add task"
    success_message = "Task {obj} created."
    cancel_url = "tasks:list"

    def form_valid(self, form):
        response = super().form_valid(form)
        activity.record(self.object, "task", f"Task created for {self.object.assigned_to.get_full_name()}",
                        customer=self.object.customer)
        notify_task_assigned(self.object)
        return response


def _can_edit_task(user, task):
    return task.assigned_to_id == user.pk or task.created_by_id == user.pk or has_capability(user, "records.assign")


class TaskUpdate(CrmUpdateView):
    model = Task
    form_class = TaskForm
    capability = "tasks.create"
    owner_fields = OWNER_FIELDS
    locked_message = "Only the assignee, the creator or a manager can edit this task."

    def can_edit(self, obj):
        return _can_edit_task(self.request.user, obj)

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        self._prev_assignee = obj.assigned_to
        return obj

    def form_valid(self, form):
        response = super().form_valid(form)
        if self._prev_assignee != self.object.assigned_to:
            activity.record(self.object, "assigned", f"Reassigned to {self.object.assigned_to.get_full_name()}",
                            customer=self.object.customer)
            notify_task_assigned(self.object, previous=self._prev_assignee)
        if "status" in form.changed_data:
            activity.record(self.object, "status", f"Status: {self.object.get_status_display()}",
                            customer=self.object.customer)
        return response


@capability_required("tasks.view")
def task_detail(request, pk):
    task = get_scoped_or_404(Task, request.user, pk, OWNER_FIELDS)
    form = CommentForm(request.POST or None)
    if request.method == "POST":
        if not has_capability(request.user, "tasks.create"):
            raise PermissionDenied
        if form.is_valid():
            comment = form.save(commit=False)
            comment.task = task
            comment.user = request.user
            comment.save()
            activity.record(task, "comment", f"Comment: {comment.text[:120]}", customer=task.customer)
            if task.assigned_to != request.user:
                from notifications.services import notify

                notify([task.assigned_to], "task_comment", f"Comment on {task.code}", comment.text[:150],
                       task.get_absolute_url())
            messages.success(request, "Comment added.")
            return redirect(task.get_absolute_url() + "#comments")
    return render(request, "tasks/detail.html", {
        "task": task, "comments": task.comments.select_related("user"), "form": form,
        "activities": activity.for_object(task, request.user)[:20],
        "can_edit": has_capability(request.user, "tasks.create") and _can_edit_task(request.user, task),
        "can_delete": task.created_by_id == request.user.pk or has_capability(request.user, "users.manage"),
    })


@require_POST
@capability_required("tasks.create")
def task_set_status(request, pk):
    task = get_scoped_or_404(Task, request.user, pk, OWNER_FIELDS)
    if not _can_edit_task(request.user, task):
        raise PermissionDenied
    status = request.POST.get("status")
    if status not in Task.Status.values:
        messages.error(request, "Unknown status.")
    else:
        task.status = status
        task.save()
        activity.record(task, "status", f"Status: {task.get_status_display()}", customer=task.customer)
        messages.success(request, f"{task.code} marked {task.get_status_display().lower()}.")
    nxt = request.POST.get("next")
    return redirect(nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else task.get_absolute_url())


@require_POST
@capability_required("tasks.create")
def task_delete(request, pk):
    task = get_scoped_or_404(Task, request.user, pk, OWNER_FIELDS)
    if not (task.created_by_id == request.user.pk or has_capability(request.user, "users.manage")):
        raise PermissionDenied("Only the person who created the task or the System Administrator can delete it.")
    label = str(task)
    task.delete()
    messages.success(request, f"Task {label} deleted.")
    return redirect("tasks:list")
