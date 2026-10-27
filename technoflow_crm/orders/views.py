from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required, has_capability
from core import activity
from core.crud import (ChoiceFilter, Column, CrmListView, CrmUpdateView, DateRangeFilter, UserFilter, badge,
                       get_scoped_or_404, money)
from quotations.models import OWNER_FIELDS as QUOTATION_OWNERS
from quotations.models import Quotation

from . import services
from .forms import CancelOrderForm, CreateOrderForm, MilestoneFormSet, OrderForm
from .models import OWNER_FIELDS, SalesOrder


class OrderList(CrmListView):
    model = SalesOrder
    capability = "orders.view"
    title = "Sales orders"
    subtitle = "Confirmed orders are order bookings. Draft orders still need confirmation by a Sales Director."
    icon = "cart-check"
    owner_fields = OWNER_FIELDS
    archive_field = None
    search_fields = ("number", "customer__company_name", "customer_po_ref", "quotation__number")
    columns = [
        Column("Order", "number", link=True), Column("Date", "order_date", date=True),
        Column("Customer", "customer.company_name"), Column("Quotation", "quotation.number"),
        Column("Customer PO", "customer_po_ref"),
        Column("Value excl. VAT", "net_amount", money=True), Column("Total incl. VAT", "total_amount", money=True),
        Column("Assigned", "assigned_to"),
        Column("Status", render=lambda o: badge(o.get_status_display(), o.tone()),
               text=lambda o: o.get_status_display()),
    ]
    sort_options = {"newest": ("Newest first", ["-order_date", "-pk"]), "value": ("Highest value", ["-net_amount"])}
    default_sort = "newest"

    def base_queryset(self):
        return SalesOrder.objects.select_related("customer", "quotation", "assigned_to")

    def get_filters(self):
        return [
            ChoiceFilter("status", "Status", SalesOrder.Status.choices,
                         lookups={"booked": Q(status__in=SalesOrder.BOOKED_STATUSES)}),
            ChoiceFilter("invoicing", "Invoicing", [("ready", "Confirmed, not fully invoiced")],
                         lookups={"ready": Q(status__in=SalesOrder.BOOKED_STATUSES)}),
            UserFilter("employee", "Employee", ["assigned_to"]),
            DateRangeFilter("date", "Order date", "order_date"),
            DateRangeFilter("confirmed", "Confirmed", "confirmed_at"),
        ]

    def filtered_queryset(self):
        qs = super().filtered_queryset()
        if self.request.GET.get("invoicing") == "ready":
            ids = [o.pk for o in qs if o.uninvoiced_total() > 0]
            qs = qs.filter(pk__in=ids)
        return qs

    def summary(self, qs):
        booked = qs.filter(status__in=SalesOrder.BOOKED_STATUSES)
        return [("Orders booked", booked.count()),
                ("Booking value excl. VAT", money(booked.aggregate(v=Sum("net_amount"))["v"] or 0)),
                ("Awaiting confirmation", qs.filter(status="draft").count()),
                ("Cancelled", qs.filter(status="cancelled").count())]


@capability_required("quotations.convert")
def create_from_quotation(request, pk):
    q = get_scoped_or_404(Quotation, request.user, pk, QUOTATION_OWNERS)
    rev = q.current
    form = CreateOrderForm(request.POST or None, user=request.user, initial={
        "order_date": timezone.localdate(), "milestones": "100", "customer_po_ref": rev.customer_reference})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            order = services.create_from_quotation(q, user=request.user, order_date=d["order_date"],
                                                   preset=d["milestones"], customer_po_ref=d["customer_po_ref"],
                                                   delivery_details=d["delivery_details"], notes=d["notes"])
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"Sales order {order.number} created. A Sales Director must confirm it.")
            return redirect(order.get_absolute_url())
    return render(request, "orders/create.html", {"form": form, "q": q, "rev": rev})


@capability_required("orders.view")
def order_detail(request, pk):
    order = get_scoped_or_404(SalesOrder, request.user, pk, OWNER_FIELDS)
    u = request.user
    milestones = []
    for m in order.milestones.all():
        inv = m.active_invoice
        milestones.append({"m": m, "invoice": inv})
    can_manage_invoices = has_capability(u, "invoices.manage") and order.is_booked
    return render(request, "orders/detail.html", {
        "order": order, "lines": order.lines.all(), "milestones": milestones,
        "invoices": order.invoices.all() if has_capability(u, "invoices.view") else [],
        "projects": order.projects.all() if has_capability(u, "projects.view") else [],
        "activities": activity.for_object(order, u)[:30],
        "can_confirm": has_capability(u, "orders.confirm") and order.status == "draft",
        "can_cancel": has_capability(u, "orders.confirm") and order.status not in ("cancelled", "completed"),
        "can_edit": has_capability(u, "orders.edit") and order.status != "cancelled",
        "progress_options": [(s, SalesOrder.Status(s).label) for s in services.PROGRESS_FLOW.get(order.status, [])]
        if has_capability(u, "orders.edit") else [],
        "can_edit_milestones": (has_capability(u, "orders.edit") or has_capability(u, "invoices.manage"))
        and order.status != "cancelled" and not any(x["invoice"] for x in milestones),
        "can_invoice": can_manage_invoices,
        "can_project": has_capability(u, "projects.edit") and order.is_booked and not order.projects.exists(),
        "invoiced": order.invoiced_total(), "uninvoiced": order.uninvoiced_total(),
    })


@require_POST
@capability_required("orders.confirm")
def order_confirm(request, pk):
    order = get_scoped_or_404(SalesOrder, request.user, pk, OWNER_FIELDS)
    try:
        services.confirm(order, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"Order {order.number} confirmed. Accounts have been notified.")
    return redirect(order.get_absolute_url())


@capability_required("orders.confirm")
def order_cancel(request, pk):
    order = get_scoped_or_404(SalesOrder, request.user, pk, OWNER_FIELDS)
    form = CancelOrderForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            services.cancel(order, request.user, form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"Order {order.number} cancelled.")
            return redirect(order.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Cancel order {order.number}",
                                              "cancel_url": order.get_absolute_url(), "submit_label": "Cancel order"})


@require_POST
@capability_required("orders.edit")
def order_progress(request, pk):
    order = get_scoped_or_404(SalesOrder, request.user, pk, OWNER_FIELDS)
    try:
        services.set_progress(order, request.POST.get("status"), request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"{order.number}: {order.get_status_display()}.")
    return redirect(order.get_absolute_url())


class OrderUpdate(CrmUpdateView):
    model = SalesOrder
    form_class = OrderForm
    capability = "orders.edit"
    owner_fields = OWNER_FIELDS
    locked_message = "Cancelled orders cannot be edited."

    def can_edit(self, obj):
        return obj.status != "cancelled"


@capability_required("orders.view")
def order_milestones(request, pk):
    order = get_scoped_or_404(SalesOrder, request.user, pk, OWNER_FIELDS)
    u = request.user
    if not (has_capability(u, "orders.edit") or has_capability(u, "invoices.manage")):
        raise PermissionDenied
    if order.status == "cancelled" or any(m.active_invoice for m in order.milestones.all()):
        raise PermissionDenied("Milestones cannot be changed after invoicing has started.")
    formset = MilestoneFormSet(request.POST or None, instance=order, prefix="ms")
    if request.method == "POST" and formset.is_valid():
        items = [(f.cleaned_data["name"], f.cleaned_data["percentage"], f.cleaned_data.get("due_date"))
                 for f in formset.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        try:
            services.set_milestones(order, [(n, p) for n, p, _ in items])
            for m, (_, _, due) in zip(order.milestones.all(), items):
                if due:
                    m.due_date = due
                    m.save(update_fields=["due_date"])
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            activity.record(order, "updated", "Payment milestones changed: " +
                            ", ".join(f"{n} {p}%" for n, p, _ in items), customer=order.customer)
            messages.success(request, "Payment milestones saved.")
            return redirect(order.get_absolute_url())
    return render(request, "orders/milestones.html", {"order": order, "formset": formset})


@require_POST
@capability_required("projects.edit")
def order_create_project(request, pk):
    from sales.services import create_from_order

    order = get_scoped_or_404(SalesOrder, request.user, pk, OWNER_FIELDS)
    if not order.is_booked:
        raise PermissionDenied("Projects are created from confirmed orders only.")
    project = create_from_order(order)
    messages.success(request, f"Project {project.code} created.")
    return redirect(project.get_absolute_url())
