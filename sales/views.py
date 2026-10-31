from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import change_history
from meetings import services as meeting_services
from accounts.permissions import capability_required, has_capability, scope_queryset
from core import activity
from core.crud import (BoolFilter, ChoiceFilter, Column, CrmCreateView, CrmListView, CrmUpdateView,
                       DateRangeFilter, ModelFilter, UserFilter, badge, get_scoped_or_404, money)
from core.models import LookupValue
from core.params import get_int
from customers.models import OWNER_FIELDS as CUSTOMER_OWNERS
from customers.models import Customer

from .forms import OpportunityForm, OpportunityStageForm, ProjectForm
from .models import OWNER_FIELDS, PROJECT_OWNER_FIELDS, Opportunity, OpportunityStage, Project, weighted
from .services import change_stage, forecast_by_month, record_creation

TABS = [("Opportunity list", "sales:pipeline", "list-ul"), ("Pipeline board", "sales:kanban", "kanban"),
        ("Forecast", "sales:forecast", "graph-up"), ("Pipeline dashboard", "dashboards:pipeline", "speedometer2"),
        ("Opportunities dashboard", "dashboards:opportunities", "speedometer2")]


def stage_badge(o):
    return badge(o.stage.name, "good" if o.stage.is_won else "bad" if o.stage.is_lost else "info")


def close_cell(o):
    if not o.expected_close_date:
        return "—"
    text = o.expected_close_date.strftime("%d-%b-%Y")
    return badge(f"{text} passed", "bad") if o.is_close_date_overdue else text


class PipelineList(CrmListView):
    model = Opportunity
    capability = "pipeline.view"
    title = "Opportunities"
    subtitle = "Qualified sales opportunities, linked to their lead and customer. Not an order or a project."
    icon = "lightning-charge"
    owner_fields = OWNER_FIELDS
    search_fields = ("code", "title", "customer__company_name", "location", "products_services", "competitors")
    create_url = "sales:opportunity_create"
    create_capability = "pipeline.edit"
    create_label = "New opportunity"
    view_tabs = TABS
    current_tab = "sales:pipeline"
    columns = [
        Column("ID", "code", link=True),
        Column("Opportunity", "title"),
        Column("Customer", "customer.company_name"),
        Column("Stage", render=stage_badge, text=lambda o: o.stage.name),
        Column("Value", "estimated_value", money=True),
        Column("Prob.", lambda o: f"{o.probability}%", align="end"),
        Column("Weighted", lambda o: o.weighted_value, money=True),
        Column("Expected close", render=close_cell, text=lambda o: o.expected_close_date),
        Column("Sales Engineer", "assigned_engineer"),
        Column("Meetings", "meeting_count", align="end"),
        Column("Next follow-up", "next_follow_up", date=True),
        Column("Next action", "next_action"),
    ]
    sort_options = {
        "close": ("Expected close", ["expected_close_date", "pk"]),
        "value": ("Highest value", ["-estimated_value"]),
        "newest": ("Newest first", ["-created_at"]),
        "stage": ("Stage", ["stage__order", "-estimated_value"]),
    }
    default_sort = "close"

    def base_queryset(self):
        return meeting_services.annotate_opportunity_meetings(
            Opportunity.objects.select_related("customer", "stage", "assigned_engineer"))

    def get_filters(self):
        today = timezone.localdate()
        return [
            ModelFilter("stage", "Stage", OpportunityStage.objects.all()),
            ChoiceFilter("state", "Open / closed", [("open", "Open"), ("won", "Won"), ("lost", "Lost")],
                         lookups={"open": Q(stage__is_won=False, stage__is_lost=False),
                                  "won": Q(stage__is_won=True), "lost": Q(stage__is_lost=True)}),
            UserFilter("employee", "Employee", ["assigned_engineer", "assigned_coordinator"]),
            ModelFilter("project_type", "Project type", lambda: LookupValue.objects.filter(category="project_type")),
            BoolFilter("overdue", "Close date passed",
                       Q(expected_close_date__lt=today, stage__is_won=False, stage__is_lost=False)),
            BoolFilter("followup_overdue", "Follow-up overdue",
                       Q(next_follow_up__lt=today, stage__is_won=False, stage__is_lost=False)),
            DateRangeFilter("close", "Expected close", "expected_close_date"),
            ModelFilter("customer", "Customer", lambda: scope_queryset(
                Customer.objects.filter(is_archived=False), self.request.user, CUSTOMER_OWNERS)),
        ]

    def summary(self, qs):
        open_qs = list(qs.filter(stage__is_won=False, stage__is_lost=False))
        value = sum((o.estimated_value for o in open_qs), Decimal(0))
        wtd = sum((weighted(o.estimated_value, o.probability) for o in open_qs), Decimal(0))
        return [("Open opportunities", len(open_qs)), ("Pipeline value (AED)", money(value)),
                ("Weighted forecast (AED)", money(wtd)),
                ("Won (AED)", money(qs.filter(stage__is_won=True).aggregate(v=Sum("estimated_value"))["v"] or 0))]


def _tabs(current):
    return [(label, reverse(url), icon, url == current) for label, url, icon in TABS]


@capability_required("pipeline.view")
def pipeline_kanban(request):
    view = PipelineList()
    view.request, view.kwargs = request, {}
    qs = view.filtered_queryset()
    stages = list(OpportunityStage.objects.filter(is_active=True))
    recent = timezone.now() - timezone.timedelta(days=90)
    columns = []
    for stage in stages:
        items = [o for o in qs if o.stage_id == stage.pk and (not stage.is_closed or o.stage_changed_at >= recent)]
        columns.append({"stage": stage, "items": items, "total": sum((i.estimated_value for i in items), Decimal(0))})
    return render(request, "sales/kanban.html", {
        "columns": columns, "stages": stages, "move_url": reverse("sales:opportunity_move", args=[0]),
        "can_move": has_capability(request.user, "pipeline.edit"), "view_tabs": _tabs("sales:kanban"),
        "filters": [f.context(request.GET, view) for f in view.get_filters() if f.key in ("employee",)],
        "q": request.GET.get("q", ""),
    })


@capability_required("pipeline.view")
def pipeline_forecast(request):
    view = PipelineList()
    view.request, view.kwargs = request, {}
    qs = view.filtered_queryset()
    rows = forecast_by_month(qs)
    by_stage = []
    for stage in OpportunityStage.objects.filter(is_won=False, is_lost=False):
        items = [o for o in qs if o.stage_id == stage.pk]
        by_stage.append({"stage": stage, "count": len(items),
                         "value": sum((o.estimated_value for o in items), Decimal(0)),
                         "weighted": sum((o.weighted_value for o in items), Decimal(0))})
    totals = {"count": sum(r["count"] for r in rows), "value": sum((r["value"] for r in rows), Decimal(0)),
              "weighted": sum((r["weighted"] for r in rows), Decimal(0))}
    return render(request, "sales/forecast.html", {
        "rows": rows, "by_stage": by_stage, "totals": totals, "view_tabs": _tabs("sales:forecast"),
        "filters": [f.context(request.GET, view) for f in view.get_filters() if f.key in ("employee",
                                                                                            "project_type")],
    })


class OpportunityCreate(CrmCreateView):
    model = Opportunity
    form_class = OpportunityForm
    capability = "pipeline.edit"
    title = "New opportunity"
    success_message = "Opportunity {obj} created."
    cancel_url = "sales:pipeline"

    def form_valid(self, form):
        form.instance.stage = OpportunityStage.first_open()
        if not form.instance.assigned_engineer_id and not has_capability(self.request.user, "records.assign"):
            form.instance.assigned_engineer = self.request.user
        response = super().form_valid(form)
        record_creation(self.object)
        activity.record(self.object, "created", f"Opportunity created ({money(self.object.estimated_value)})")
        return response


class OpportunityUpdate(CrmUpdateView):
    model = Opportunity
    form_class = OpportunityForm
    capability = "pipeline.edit"
    owner_fields = OWNER_FIELDS
    locked_message = "Archived opportunities cannot be edited."

    def can_edit(self, obj):
        return not obj.is_archived

    def form_valid(self, form):
        changed = [f for f in form.changed_data]
        response = super().form_valid(form)
        if changed:
            activity.record(self.object, "updated", "Updated: " + ", ".join(
                str(form.fields[f].label) for f in changed if f in form.fields))
        return response


@capability_required("pipeline.view")
def opportunity_detail(request, pk):
    opp = get_scoped_or_404(Opportunity, request.user, pk, OWNER_FIELDS)
    u = request.user
    from core.scopes import owners

    quotations = []
    if has_capability(u, "quotations.view"):
        quotations = scope_queryset(opp.quotations.select_related("salesperson"), u, owners("quotations.quotation"))
    orders = []
    if has_capability(u, "orders.view"):
        orders = scope_queryset(opp.orders.all(), u, owners("orders.salesorder"))
    return render(request, "sales/opportunity_detail.html", {
        "opp": opp,
        "history": opp.stage_history.select_related("from_stage", "to_stage", "changed_by")[:20],
        "quotations": quotations, "orders": orders,
        "projects": opp.projects.all() if has_capability(u, "projects.view") else [],
        "visits": scope_queryset(opp.visits.select_related("assigned_to"), u, owners("visits.visit"))
        if has_capability(u, "visits.view") else [],
        "activities": activity.for_object(opp, u)[:30],
        "change_rows": change_history(opp, skip=("code", "stage_changed_at")),
        "steps": _steps(opp),
        "meetings": meeting_services.with_permissions(meeting_services.for_opportunity(opp), u), "meeting_counts": meeting_services.counts(opportunity=opp),
        "kind": "opportunity", "meeting_parent": opp, "today": timezone.localdate(),
        "can_add_meeting": has_capability(u, "pipeline.edit") and not opp.is_archived,
        "can_edit": has_capability(u, "pipeline.edit") and not opp.is_archived,
        "can_archive": has_capability(u, "pipeline.archive"),
    })


def _steps(opp):
    """The opportunity's progress through the fixed sales order, for the step bar at the top of its page."""
    from meetings import services as meeting_services

    quotes = list(opp.quotations.all())
    statuses = {q.status for q in quotes}
    n_meet = meeting_services.counts(opportunity=opp)["total"]
    latest = max(quotes, key=lambda q: q.created_at, default=None)
    outcome = "Won" if opp.stage.is_won else "Lost" if opp.stage.is_lost else "Open"
    return [
        {"label": "Customer & lead", "done": True, "note": opp.customer.company_name},
        {"label": "Meetings", "done": n_meet > 0, "note": f"{n_meet} held" if n_meet else "none yet"},
        {"label": "Quotation", "done": bool(quotes), "note": latest.display_number if latest else "not uploaded"},
        {"label": "Approval", "done": bool(statuses & {"approved", "sent", "accepted", "declined", "expired"}),
         "note": "approved" if statuses & {"approved", "sent", "accepted"} else
         "waiting" if "submitted" in statuses else "—"},
        {"label": "Customer answer", "done": bool(statuses & {"accepted", "declined"}),
         "note": "accepted" if "accepted" in statuses else "declined" if "declined" in statuses else
         "sent" if "sent" in statuses else "—"},
        {"label": "Won / Lost", "done": opp.stage.is_closed, "note": outcome,
         "tone": "good" if opp.stage.is_won else "bad" if opp.stage.is_lost else None},
    ]


@capability_required("pipeline.edit")
def opportunity_stage(request, pk):
    opp = get_scoped_or_404(Opportunity, request.user, pk, OWNER_FIELDS)
    if opp.is_archived:
        raise PermissionDenied("Archived opportunities cannot be changed.")
    form = OpportunityStageForm(request.POST or None, user=request.user,
                                initial={"stage": get_int(request.GET, "stage") or opp.stage_id,
                                         "probability": opp.probability})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            change_stage(opp, d["stage"], probability=d["probability"], lost_reason=d["lost_reason"],
                         lost_notes=d["lost_notes"], note=d["note"])
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"{opp.code} moved to {opp.stage} ({opp.probability}%).")
            return redirect(opp.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Change stage — {opp}",
                                              "cancel_url": opp.get_absolute_url()})


@require_POST
@capability_required("pipeline.edit")
def opportunity_move(request, pk):
    opp = scope_queryset(Opportunity.objects.all(), request.user, OWNER_FIELDS).filter(pk=pk).first()
    if opp is None:
        return JsonResponse({"error": "Opportunity not found."}, status=404)
    if opp.is_archived:
        return JsonResponse({"error": "Archived opportunities cannot be moved."}, status=403)
    stage = OpportunityStage.objects.filter(pk=get_int(request.POST, "stage"), is_active=True).first()
    if stage is None:
        return JsonResponse({"error": "Unknown stage."}, status=400)
    if stage.is_lost:
        return JsonResponse({"redirect": reverse("sales:opportunity_stage", args=[opp.pk]) + f"?stage={stage.pk}"})
    change_stage(opp, stage)
    return JsonResponse({"ok": True})


@require_POST
@capability_required("pipeline.archive")
def opportunity_archive(request, pk):
    opp = get_scoped_or_404(Opportunity, request.user, pk, OWNER_FIELDS)
    opp.is_archived = not opp.is_archived
    opp.save(update_fields=["is_archived", "updated_at", "updated_by"])
    activity.record(opp, "status", "Archived" if opp.is_archived else "Restored from archive")
    messages.success(request, f"{opp.code} {'archived' if opp.is_archived else 'restored'}.")
    return redirect(opp.get_absolute_url())


# ------------------------------------------------------------- projects
PROJECT_TONE = {"planned": "info", "in_progress": "warn", "on_hold": "neutral", "completed": "good",
                "cancelled": "neutral"}


class ProjectList(CrmListView):
    model = Project
    capability = "projects.view"
    title = "Projects"
    subtitle = "Projects under execution (delivery), normally created from confirmed orders."
    icon = "briefcase"
    owner_fields = PROJECT_OWNER_FIELDS
    archive_field = None
    search_fields = ("code", "name", "customer__company_name", "location")
    create_url = "sales:project_create"
    create_capability = "projects.edit"
    create_label = "New project"
    view_tabs = [("List", "sales:projects", "list-ul"), ("Dashboard", "dashboards:projects", "speedometer2")]
    current_tab = "sales:projects"
    columns = [
        Column("Project", "code", link=True), Column("Name", "name"), Column("Customer", "customer.company_name"),
        Column("Order", lambda p: p.sales_order.number if p.sales_order_id else "—"),
        Column("Status", render=lambda p: badge(p.get_status_display(), PROJECT_TONE[p.status]),
               text=lambda p: p.get_status_display()),
        Column("Progress", lambda p: f"{p.progress}%", align="end"),
        Column("Manager", "project_manager"), Column("Start", "start_date", date=True),
        Column("Planned completion", "end_date", date=True),
    ]
    sort_options = {"newest": ("Newest first", ["-created_at"]), "end": ("Planned completion", ["end_date"])}
    default_sort = "newest"

    def base_queryset(self):
        return Project.objects.select_related("customer", "sales_order", "project_manager")

    def get_filters(self):
        return [ChoiceFilter("status", "Status", Project.Status.choices),
                UserFilter("employee", "Manager", ["project_manager"])]


class ProjectCreate(CrmCreateView):
    model = Project
    form_class = ProjectForm
    capability = "projects.edit"
    title = "New project"
    success_message = "Project {obj} created."
    cancel_url = "sales:projects"

    def form_valid(self, form):
        response = super().form_valid(form)
        activity.record(self.object, "created", "Project created")
        return response


class ProjectUpdate(CrmUpdateView):
    model = Project
    form_class = ProjectForm
    capability = "projects.edit"
    owner_fields = PROJECT_OWNER_FIELDS

    def form_valid(self, form):
        response = super().form_valid(form)
        if "status" in form.changed_data or "progress" in form.changed_data:
            activity.record(self.object, "status",
                            f"Status: {self.object.get_status_display()}, {self.object.progress}% complete")
        return response


@capability_required("projects.view")
def project_detail(request, pk):
    project = get_scoped_or_404(Project, request.user, pk, PROJECT_OWNER_FIELDS)
    return render(request, "sales/project_detail.html", {
        "project": project, "activities": activity.for_object(project, request.user)[:30],
        "can_edit": has_capability(request.user, "projects.edit"),
    })
