from django.contrib import messages
from django.shortcuts import render

from accounts.permissions import capability_required, has_capability
from core import activity
from core.crud import (ChoiceFilter, Column, CrmCreateView, CrmDeleteView, CrmListView, CrmUpdateView,
                       DateRangeFilter, UserFilter, get_scoped_or_404)
from tasks.services import create_follow_up

from .forms import CommunicationForm
from .models import OWNER_FIELDS, Communication


class CommunicationList(CrmListView):
    model = Communication
    capability = "communications.view"
    title = "Communication history"
    subtitle = "Calls, emails, WhatsApp messages and meetings logged by the team. Logged manually: "\
               "no email or WhatsApp integration is connected."
    icon = "chat-left-text"
    owner_fields = OWNER_FIELDS
    archive_field = None
    search_fields = ("code", "subject", "summary", "outcome", "customer__company_name")
    create_url = "communications:create"
    create_capability = "communications.create"
    create_label = "Log communication"
    columns = [
        Column("When", "occurred_at", date=True),
        Column("ID", "code", link=True),
        Column("Customer", "customer.company_name"),
        Column("Type", lambda c: c.get_kind_display()),
        Column("Subject", "subject"),
        Column("Employee", "employee"),
        Column("Outcome", "outcome"),
        Column("Follow-up", "follow_up_date", date=True),
    ]
    sort_options = {"newest": ("Newest first", ["-occurred_at"]), "oldest": ("Oldest first", ["occurred_at"])}
    default_sort = "newest"

    def base_queryset(self):
        return Communication.objects.select_related("customer", "employee")

    def get_filters(self):
        return [
            ChoiceFilter("kind", "Type", Communication.Kind.choices),
            UserFilter("employee", "Employee", ["employee"]),
            DateRangeFilter("date", "Date", "occurred_at"),
        ]


def _after_save(request, comm, form):
    comm.customer.touch_contact(comm.occurred_at.date(), comm.follow_up_date)
    if comm.lead_id:
        lead = comm.lead
        if not lead.last_contact_date or comm.occurred_at.date() > lead.last_contact_date:
            type(lead).objects.filter(pk=lead.pk).update(last_contact_date=comm.occurred_at.date())
    if form.cleaned_data.get("create_task"):
        create_follow_up(title=f"Follow up: {comm.subject}", assigned_to=comm.employee,
                         due_date=comm.follow_up_date, description=comm.next_action, customer=comm.customer,
                         lead=comm.lead, opportunity=comm.opportunity)
        messages.info(request, "Follow-up task created.")


class CommunicationCreate(CrmCreateView):
    model = Communication
    form_class = CommunicationForm
    capability = "communications.create"
    title = "Log communication"
    success_message = "Communication {obj} logged."
    cancel_url = "communications:list"

    def form_valid(self, form):
        response = super().form_valid(form)
        c = self.object
        activity.record(c, "communication", f"{c.get_kind_display()}: {c.subject}", customer=c.customer)
        _after_save(self.request, c, form)
        return response


class CommunicationUpdate(CrmUpdateView):
    model = Communication
    form_class = CommunicationForm
    capability = "communications.create"
    owner_fields = OWNER_FIELDS
    locked_message = "Only the employee who logged it, or an administrator, can edit this record."

    def can_edit(self, obj):
        u = self.request.user
        return obj.employee_id == u.pk or obj.created_by_id == u.pk or has_capability(u, "users.manage")

    def form_valid(self, form):
        response = super().form_valid(form)
        _after_save(self.request, self.object, form)
        return response


@capability_required("communications.view")
def communication_detail(request, pk):
    comm = get_scoped_or_404(Communication, request.user, pk, OWNER_FIELDS)
    u = request.user
    return render(request, "communications/detail.html", {
        "comm": comm,
        "can_edit": has_capability(u, "communications.create") and (
            comm.employee_id == u.pk or comm.created_by_id == u.pk or has_capability(u, "users.manage")),
        "can_delete": has_capability(u, "communications.delete"),
    })


class CommunicationDelete(CrmDeleteView):
    model = Communication
    capability = "communications.delete"
    owner_fields = OWNER_FIELDS
    success_url_name = "communications:list"
