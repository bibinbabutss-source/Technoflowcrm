from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required, has_capability
from core import activity
from core.crud import (BoolFilter, ChoiceFilter, Column, CrmCreateView, CrmDeleteView, CrmListView,
                       CrmUpdateView, DateRangeFilter, ModelFilter, UserFilter, badge, get_scoped_or_404)
from core.models import LookupValue
from core.params import get_int
from core.registry import customer_sections

from .forms import CustomerContactForm, CustomerForm
from .models import OWNER_FIELDS, Customer, CustomerContact
from .services import archive

STATUS_TONE = {"active": "good", "prospect": "info", "on_hold": "warn", "inactive": "neutral"}


def status_badge(c):
    return badge(c.get_status_display(), STATUS_TONE.get(c.status, "neutral"))


def follow_up_cell(c):
    if not c.next_follow_up:
        return "—"
    text = c.next_follow_up.strftime("%d-%b-%Y")
    return badge(text, "bad") if c.is_follow_up_overdue else text


class CustomerList(CrmListView):
    model = Customer
    capability = "customers.view"
    title = "Customers"
    subtitle = "All customer companies you are allowed to see."
    icon = "building"
    owner_fields = OWNER_FIELDS
    search_fields = ("code", "company_name", "contact_person", "email", "phone", "alt_phone", "trn",
                     "contacts__name", "contacts__email", "contacts__phone")
    search_placeholder = "Name, ID, contact, email, phone"
    create_url = "customers:create"
    create_capability = "customers.create"
    create_label = "Add customer"
    columns = [
        Column("Customer ID", "code", link=True),
        Column("Company", "company_name"),
        Column("Category", "category"),
        Column("Status", render=status_badge, text=lambda c: c.get_status_display()),
        Column("Contact", "contact_person"),
        Column("Phone", "phone"),
        Column("City", "city"),
        Column("Sales Engineer", "assigned_engineer"),
        Column("Last contact", "last_contact_date", date=True),
        Column("Next follow-up", render=follow_up_cell, text=lambda c: c.next_follow_up),
    ]
    sort_options = {
        "name": ("Company name", ["company_name"]),
        "newest": ("Newest first", ["-created_at"]),
        "follow_up": ("Next follow-up", ["next_follow_up", "company_name"]),
        "last_contact": ("Last contact (oldest first)", ["last_contact_date", "company_name"]),
    }
    default_sort = "name"

    def base_queryset(self):
        return Customer.objects.select_related("category", "assigned_engineer")

    def get_filters(self):
        return [
            ChoiceFilter("status", "Status", Customer.Status.choices),
            ModelFilter("category", "Category", lambda: LookupValue.objects.filter(category="customer_category")),
            UserFilter("employee", "Employee", ["assigned_engineer", "assigned_coordinator"]),
            BoolFilter("overdue", "Follow-up overdue", Q(next_follow_up__lt=timezone.localdate())),
            BoolFilter("inactive_90", "No contact in 90 days",
                       Q(last_contact_date__lt=timezone.localdate() - timezone.timedelta(days=90)) |
                       Q(last_contact_date__isnull=True)),
            DateRangeFilter("created", "Created", "created_at"),
        ]


class CustomerCreate(CrmCreateView):
    model = Customer
    form_class = CustomerForm
    capability = "customers.create"
    title = "Add customer"
    template_name = "customers/form.html"
    success_message = "Customer {obj} created."
    cancel_url = "customers:list"

    def form_valid(self, form):
        response = super().form_valid(form)
        activity.record(self.object, "created", "Customer created")
        return response


class CustomerUpdate(CrmUpdateView):
    model = Customer
    form_class = CustomerForm
    capability = "customers.edit"
    owner_fields = OWNER_FIELDS
    template_name = "customers/form.html"
    success_message = "Customer {obj} saved."

    def can_edit(self, obj):
        return not obj.is_archived

    locked_message = "Archived customers cannot be edited. Restore the customer first."

    def form_valid(self, form):
        changed = form.changed_data
        response = super().form_valid(form)
        if "assigned_engineer" in changed or "assigned_coordinator" in changed:
            activity.record(self.object, "assigned", f"Assigned to {self.object.assigned_engineer or '—'} / "
                                                     f"{self.object.assigned_coordinator or '—'}")
        elif changed:
            activity.record(self.object, "updated", "Details updated: " + ", ".join(
                form.fields[f].label or f for f in changed if f in form.fields and f != "confirm_duplicates"))
        return response


@capability_required("customers.view")
def customer_detail(request, pk):
    customer = get_scoped_or_404(Customer, request.user, pk, OWNER_FIELDS)
    customer = Customer.objects.select_related(
        "category", "industry", "source", "assigned_engineer", "assigned_coordinator").get(pk=customer.pk)
    sections = []
    for s in customer_sections:
        if not has_capability(request.user, s["capability"]):
            continue
        qs = s["getter"](customer, request.user)
        items = list(qs[:10])
        sections.append({
            "key": s["key"], "label": s["label"], "count": qs.count(),
            "columns": s["columns"],
            "rows": [[c.html(o) for c in s["columns"]] for o in items],
            "add_url": s["add_url"](customer) if s["add_url"] and (
                not s["add_capability"] or has_capability(request.user, s["add_capability"])) else None,
        })
    return render(request, "customers/detail.html", {
        "customer": customer,
        "contacts": customer.contacts.all(),
        "sections": sections,
        "activities": activity.for_customer(customer, request.user)[:30],
        "can_edit": has_capability(request.user, "customers.edit") and not customer.is_archived,
        "can_archive": has_capability(request.user, "customers.archive"),
        "can_delete": has_capability(request.user, "customers.delete"),
        "can_see_notes": has_capability(request.user, "customers.edit"),
        "contact_form": CustomerContactForm(user=request.user),
    })


@require_POST
@capability_required("customers.archive")
def customer_archive(request, pk):
    customer = get_scoped_or_404(Customer, request.user, pk, OWNER_FIELDS)
    archive(customer, archived=not customer.is_archived)
    messages.success(request, f"{customer} {'archived' if customer.is_archived else 'restored'}.")
    return redirect(customer.get_absolute_url())


class CustomerDelete(CrmDeleteView):
    model = Customer
    capability = "customers.delete"
    owner_fields = OWNER_FIELDS
    success_url_name = "customers:list"


# ------------------------------------------------------------- contacts
@capability_required("customers.edit")
def contact_add(request, pk):
    customer = get_scoped_or_404(Customer, request.user, pk, OWNER_FIELDS)
    if customer.is_archived:
        raise PermissionDenied("Archived customers cannot be edited.")
    form = CustomerContactForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        contact = form.save(commit=False)
        contact.customer = customer
        contact.save()
        if contact.is_primary:
            customer.contacts.exclude(pk=contact.pk).update(is_primary=False)
        activity.record(customer, "updated", f"Contact added: {contact.name}")
        messages.success(request, f"Contact {contact.name} added.")
        return redirect(customer.get_absolute_url() + "#contacts")
    return render(request, "crud/form.html", {"form": form, "title": f"Add contact — {customer.company_name}",
                                              "cancel_url": customer.get_absolute_url()})


@capability_required("customers.edit")
def contact_edit(request, pk):
    contact = get_object_or_404(CustomerContact, pk=pk)
    customer = get_scoped_or_404(Customer, request.user, contact.customer_id, OWNER_FIELDS)
    form = CustomerContactForm(request.POST or None, instance=contact, user=request.user)
    if request.method == "POST":
        if request.POST.get("delete") == "1":
            name = contact.name
            contact.delete()
            activity.record(customer, "updated", f"Contact removed: {name}")
            messages.success(request, f"Contact {name} removed.")
            return redirect(customer.get_absolute_url() + "#contacts")
        if form.is_valid():
            contact = form.save()
            if contact.is_primary:
                customer.contacts.exclude(pk=contact.pk).update(is_primary=False)
            messages.success(request, f"Contact {contact.name} saved.")
            return redirect(customer.get_absolute_url() + "#contacts")
    return render(request, "customers/contact_form.html", {
        "form": form, "title": f"Edit contact — {customer.company_name}", "contact": contact,
        "cancel_url": customer.get_absolute_url()})


@capability_required("customers.create")
def duplicate_check(request):
    """Live duplicate check used by the customer form (returns a small HTML fragment)."""
    from .services import find_duplicates

    dups = find_duplicates(company_name=request.GET.get("company_name", ""), email=request.GET.get("email", ""),
                           phone=request.GET.get("phone", ""), trn=request.GET.get("trn", ""),
                           exclude_pk=get_int(request.GET, "exclude"))
    return render(request, "customers/_duplicates.html", {"duplicates": dups})
