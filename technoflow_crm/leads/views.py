from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required, has_capability, scope_queryset
from core import activity
from core.crud import (BoolFilter, ChoiceFilter, Column, CrmCreateView, CrmListView, CrmUpdateView,
                       DateRangeFilter, ModelFilter, UserFilter, badge, get_scoped_or_404, money)
from core.models import LookupValue
from core.params import get_int
from customers.services import find_duplicates

from .forms import ConvertForm, LeadForm, StageForm
from .models import OWNER_FIELDS, Lead, LeadStage
from .services import change_stage, convert, record_assignment

PRIORITY_TONE = {"high": "bad", "medium": "warn", "low": "neutral"}

VIEW_TABS = [("List", "leads:list", "list-ul"), ("Kanban", "leads:kanban", "kanban")]


def stage_badge(lead):
    tone = "good" if lead.stage.is_won else "bad" if lead.stage.is_lost else "info"
    return badge(lead.stage.name, tone)


def follow_up_cell(lead):
    if not lead.next_follow_up:
        return "—"
    text = lead.next_follow_up.strftime("%d-%b-%Y")
    return badge(text, "bad") if lead.is_follow_up_overdue else text


class LeadList(CrmListView):
    model = Lead
    capability = "leads.view"
    title = "Leads"
    subtitle = "Enquiries from first contact to won or lost."
    icon = "funnel"
    owner_fields = OWNER_FIELDS
    search_fields = ("code", "title", "company_name", "contact_person", "email", "phone", "interest")
    search_placeholder = "Lead ID, title, company, contact"
    create_url = "leads:create"
    create_capability = "leads.create"
    create_label = "Add lead"
    view_tabs = VIEW_TABS
    current_tab = "leads:list"
    columns = [
        Column("Lead ID", "code", link=True),
        Column("Title", "title"),
        Column("Company", "company_name"),
        Column("Source", "source"),
        Column("Stage", render=stage_badge, text=lambda lead: lead.stage.name),
        Column("Priority", render=lambda lead: badge(lead.get_priority_display(), PRIORITY_TONE[lead.priority]),
               text=lambda lead: lead.get_priority_display()),
        Column("Est. value", "estimated_value", money=True),
        Column("Sales Engineer", "assigned_engineer"),
        Column("Next follow-up", render=follow_up_cell, text=lambda lead: lead.next_follow_up),
        Column("Created", "created_at", date=True),
    ]
    sort_options = {
        "newest": ("Newest first", ["-created_at"]),
        "value": ("Highest value", ["-estimated_value"]),
        "follow_up": ("Next follow-up", ["next_follow_up"]),
        "stage": ("Stage", ["stage__order", "-created_at"]),
    }
    default_sort = "newest"

    def base_queryset(self):
        return Lead.objects.select_related("stage", "source", "assigned_engineer")

    def get_filters(self):
        today = timezone.localdate()
        return [
            ModelFilter("stage", "Stage", LeadStage.objects.all()),
            ChoiceFilter("state", "Open / closed", [("open", "Open"), ("won", "Won"), ("lost", "Lost")],
                         lookups={"open": Q(stage__is_won=False, stage__is_lost=False),
                                  "won": Q(stage__is_won=True), "lost": Q(stage__is_lost=True)}),
            ChoiceFilter("priority", "Priority", Lead.Priority.choices),
            ModelFilter("source", "Source", lambda: LookupValue.objects.filter(category="lead_source")),
            UserFilter("employee", "Employee", ["assigned_engineer", "assigned_coordinator"]),
            BoolFilter("overdue", "Follow-up overdue",
                       Q(next_follow_up__lt=today, stage__is_won=False, stage__is_lost=False)),
            BoolFilter("unassigned", "Unassigned", Q(assigned_engineer__isnull=True)),
            BoolFilter("converted", "Converted", Q(customer__isnull=False)),
            DateRangeFilter("created", "Created", "created_at"),
        ]

    def summary(self, qs):
        open_qs = qs.filter(stage__is_won=False, stage__is_lost=False)
        return [("Leads", qs.count()), ("Open", open_qs.count()),
                ("Open value (AED)", money(open_qs.aggregate(v=Sum("estimated_value"))["v"] or 0)),
                ("Won", qs.filter(stage__is_won=True).count())]


@capability_required("leads.view")
def lead_kanban(request):
    view = LeadList()
    view.request = request
    view.kwargs = {}
    qs = view.filtered_queryset()
    stages = list(LeadStage.objects.filter(is_active=True))
    columns = []
    recent = timezone.now() - timezone.timedelta(days=90)
    for stage in stages:
        items = [lead for lead in qs if lead.stage_id == stage.pk
                 and (not stage.is_closed or lead.stage_changed_at >= recent)]
        columns.append({"stage": stage, "items": items, "total": sum(i.estimated_value for i in items)})
    return render(request, "leads/kanban.html", {
        "columns": columns, "stages": stages, "move_url": reverse("leads:move", args=[0]),
        "can_move": has_capability(request.user, "leads.edit"),
        "view_tabs": [(label, reverse(url), icon, url == "leads:kanban") for label, url, icon in VIEW_TABS],
        "filters": [f.context(request.GET, view) for f in view.get_filters() if f.key in ("employee", "priority",
                                                                                            "source")],
        "q": request.GET.get("q", ""),
    })


class LeadCreate(CrmCreateView):
    model = Lead
    form_class = LeadForm
    capability = "leads.create"
    title = "Add lead"
    template_name = "leads/form.html"
    success_message = "Lead {obj} created."
    cancel_url = "leads:list"

    def form_valid(self, form):
        form.instance.stage = LeadStage.first_open()
        response = super().form_valid(form)
        activity.record(self.object, "created", "Lead registered")
        record_assignment(self.object, note="Initial assignment")
        return response


class LeadUpdate(CrmUpdateView):
    model = Lead
    form_class = LeadForm
    capability = "leads.edit"
    owner_fields = OWNER_FIELDS
    template_name = "leads/form.html"
    success_message = "Lead {obj} saved."
    locked_message = "Archived leads cannot be edited."

    def can_edit(self, obj):
        return not obj.is_archived

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        self._prev = (obj.assigned_engineer, obj.assigned_coordinator)
        return obj

    def form_valid(self, form):
        response = super().form_valid(form)
        record_assignment(self.object, previous_engineer=self._prev[0], previous_coordinator=self._prev[1])
        return response


@capability_required("leads.view")
def lead_detail(request, pk):
    lead = get_scoped_or_404(Lead, request.user, pk, OWNER_FIELDS)
    opportunities = []
    if has_capability(request.user, "pipeline.view"):
        opportunities = lead.opportunities.select_related("stage")
    return render(request, "leads/detail.html", {
        "lead": lead,
        "assignments": lead.assignments.select_related("engineer", "coordinator", "assigned_by")[:10],
        "history": lead.stage_history.select_related("from_stage", "to_stage", "changed_by")[:15],
        "activities": activity.for_object(lead, request.user)[:30],
        "opportunities": opportunities,
        "can_edit": has_capability(request.user, "leads.edit") and not lead.is_archived,
        "can_convert": has_capability(request.user, "leads.convert") and not lead.is_converted
        and not lead.stage.is_lost and not lead.is_archived,
        "can_archive": has_capability(request.user, "leads.archive"),
        "stage_form": StageForm(initial={"stage": lead.stage}, user=request.user),
    })


def _can_change(request, lead):
    if not has_capability(request.user, "leads.edit"):
        raise PermissionDenied
    if lead.is_archived:
        raise PermissionDenied("Archived leads cannot be changed.")


@capability_required("leads.edit")
def lead_stage(request, pk):
    lead = get_scoped_or_404(Lead, request.user, pk, OWNER_FIELDS)
    _can_change(request, lead)
    initial = {"stage": get_int(request.GET, "stage") or lead.stage_id}
    form = StageForm(request.POST or None, initial=initial, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            change_stage(lead, form.cleaned_data["stage"], lost_reason=form.cleaned_data["lost_reason"],
                         lost_notes=form.cleaned_data["lost_notes"], note=form.cleaned_data["note"])
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"{lead.code} moved to {lead.stage}.")
            return redirect(lead.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Change stage — {lead}",
                                              "cancel_url": lead.get_absolute_url()})


@require_POST
@capability_required("leads.edit")
def lead_move(request, pk):
    """Kanban drag-and-drop. Moving to Lost needs a reason, so the user is sent to the stage form."""
    lead = scope_queryset(Lead.objects.all(), request.user, OWNER_FIELDS).filter(pk=pk).first()
    if lead is None:
        return JsonResponse({"error": "Lead not found."}, status=404)
    if lead.is_archived:
        return JsonResponse({"error": "Archived leads cannot be moved."}, status=403)
    stage = LeadStage.objects.filter(pk=get_int(request.POST, "stage"), is_active=True).first()
    if stage is None:
        return JsonResponse({"error": "Unknown stage."}, status=400)
    if stage.is_lost:
        return JsonResponse({"redirect": reverse("leads:stage", args=[lead.pk]) + f"?stage={stage.pk}"})
    change_stage(lead, stage)
    return JsonResponse({"ok": True})


@capability_required("leads.convert")
def lead_convert(request, pk):
    lead = get_scoped_or_404(Lead, request.user, pk, OWNER_FIELDS)
    if lead.is_converted:
        messages.info(request, "This lead is already converted.")
        return redirect(lead.get_absolute_url())
    if lead.stage.is_lost or lead.is_archived:
        raise PermissionDenied("Lost or archived leads cannot be converted.")
    duplicates = find_duplicates(company_name=lead.company_name, email=lead.email, phone=lead.phone)
    initial = {"company_name": lead.company_name, "contact_person": lead.contact_person, "email": lead.email,
               "phone": lead.phone, "city": lead.city, "opp_title": lead.title, "opp_value": lead.estimated_value,
               "opp_probability": 25, "create_opportunity": True}
    form = ConvertForm(request.POST or None, initial=initial, lead=lead, duplicates=duplicates, user=request.user)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        customer, new_data = None, None
        if d["mode"] == "existing":
            customer = d["existing_customer"]
        else:
            new_data = {"company_name": d["company_name"].strip(), "category": d["category"],
                        "contact_person": d["contact_person"], "email": d["email"], "phone": d["phone"],
                        "city": d["city"], "source": lead.source, "assigned_engineer": lead.assigned_engineer,
                        "assigned_coordinator": lead.assigned_coordinator, "designation": lead.designation}
        opp_data = None
        if d.get("create_opportunity"):
            opp_data = {"title": d["opp_title"].strip(), "estimated_value": d.get("opp_value") or 0,
                        "expected_close_date": d.get("opp_close"), "probability": d["opp_probability"]}
        try:
            customer, opportunity = convert(lead, customer=customer, new_customer_data=new_data,
                                            opportunity_data=opp_data, user=request.user)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"Lead converted: customer {customer.code}" +
                             (f", opportunity {opportunity.code}." if opportunity else "."))
            return redirect(opportunity.get_absolute_url() if opportunity else customer.get_absolute_url())
    return render(request, "leads/convert.html", {"lead": lead, "form": form, "duplicates": duplicates})


@require_POST
@capability_required("leads.archive")
def lead_archive(request, pk):
    lead = get_scoped_or_404(Lead, request.user, pk, OWNER_FIELDS)
    lead.is_archived = not lead.is_archived
    lead.save(update_fields=["is_archived", "updated_at", "updated_by"])
    activity.record(lead, "status", "Archived" if lead.is_archived else "Restored from archive")
    messages.success(request, f"{lead.code} {'archived' if lead.is_archived else 'restored'}.")
    return redirect(lead.get_absolute_url())
