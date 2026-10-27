from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required, has_capability, scope_queryset
from core import activity
from core.crud import (BoolFilter, ChoiceFilter, Column, CrmListView, DateRangeFilter, ModelFilter, badge,
                       get_scoped_or_404, money)
from core.exports import xlsx_response
from core.params import get_date, get_int
from core.pdf import pdf_response
from customers.models import OWNER_FIELDS as CUSTOMER_OWNERS
from customers.models import Customer
from orders.models import OWNER_FIELDS as ORDER_OWNERS
from orders.models import PaymentMilestone, SalesOrder

from . import services
from .forms import (AllocateForm, DisputeForm, InvoiceForm, InvoiceLineFormSet, PaymentForm, ReasonForm,
                    StatementForm)
from .models import OWNER_FIELDS, PAYMENT_OWNER_FIELDS, Invoice, Payment

I = Invoice.Status


def _visible_customers(user):
    return scope_queryset(Customer.objects.all(), user, CUSTOMER_OWNERS).order_by("company_name")


def status_cell(inv):
    label = inv.display_status + (" · disputed" if inv.is_disputed else "")
    return badge(label, "bad" if inv.is_disputed else inv.tone())


class InvoiceList(CrmListView):
    model = Invoice
    capability = "invoices.view"
    title = "Invoices"
    icon = "receipt"
    owner_fields = OWNER_FIELDS
    archive_field = None
    search_fields = ("number", "customer__company_name", "reference", "order__number")
    columns = [
        Column("Invoice", "display_number", link=True), Column("Date", "invoice_date", date=True),
        Column("Customer", "customer.company_name"), Column("Order", "order.number"),
        Column("Due", "due_date", date=True),
        Column("Total", "total", money=True), Column("Paid", "amount_paid", money=True),
        Column("Outstanding", "outstanding", money=True),
        Column("Status", render=status_cell, text=lambda i: i.display_status),
    ]
    sort_options = {"newest": ("Newest first", ["-invoice_date", "-pk"]), "due": ("Due date", ["due_date"]),
                    "amount": ("Highest total", ["-total"])}
    default_sort = "newest"

    def base_queryset(self):
        return Invoice.objects.select_related("customer", "order")

    def get_filters(self):
        today = timezone.localdate()
        return [
            ChoiceFilter("status", "Status", list(I.choices) + [("overdue", "Overdue"), ("open", "Unpaid / part paid")],
                         lookups={"overdue": Q(status__in=Invoice.OPEN_STATUSES, due_date__lt=today),
                                  "open": Q(status__in=Invoice.OPEN_STATUSES)}),
            BoolFilter("disputed", "Disputed", Q(is_disputed=True)),
            ModelFilter("customer", "Customer", lambda: _visible_customers(self.request.user)),
            DateRangeFilter("date", "Invoice date", "invoice_date"),
            DateRangeFilter("due", "Due date", "due_date"),
        ]

    def summary(self, qs):
        live = qs.exclude(status__in=[I.DRAFT, I.CANCELLED])
        total = live.aggregate(t=Sum("total"), p=Sum("amount_paid"))
        overdue = [i for i in live.filter(status__in=Invoice.OPEN_STATUSES) if i.is_overdue]
        return [("Invoiced", money(total["t"] or 0)), ("Collected (allocated)", money(total["p"] or 0)),
                ("Outstanding", money((total["t"] or 0) - (total["p"] or 0))),
                ("Overdue", f"{len(overdue)} · {money(sum((i.outstanding for i in overdue), Decimal(0)))}")]


@capability_required("invoices.view")
def invoice_detail(request, pk):
    inv = get_scoped_or_404(Invoice, request.user, pk, OWNER_FIELDS)
    u = request.user
    manage = has_capability(u, "invoices.manage")
    return render(request, "invoicing/detail.html", {
        "inv": inv, "lines": inv.lines.all(), "tax_breakdown": services.tax_breakdown(inv),
        "allocations": inv.allocations.select_related("payment"),
        "tasks": inv.tasks.select_related("assigned_to") if has_capability(u, "tasks.view") else [],
        "activities": activity.for_object(inv, u)[:30],
        "can_edit": manage and inv.status == I.DRAFT,
        "can_cancel": manage and inv.status in Invoice.OPEN_STATUSES and inv.amount_paid == 0,
        "can_pay": has_capability(u, "payments.manage") and inv.status in Invoice.OPEN_STATUSES,
        "can_dispute": manage and inv.status in Invoice.OPEN_STATUSES,
        "manage": manage,
    })


@require_POST
@capability_required("invoices.manage")
def create_from_milestone(request, pk):
    milestone = PaymentMilestone.objects.select_related("order").filter(pk=pk).first()
    if milestone is None:
        raise PermissionDenied
    get_scoped_or_404(SalesOrder, request.user, milestone.order_id, ORDER_OWNERS)
    try:
        inv = services.create_from_milestone(milestone, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect(milestone.order.get_absolute_url())
    messages.success(request, f"Draft invoice prepared: {inv.currency} {inv.total:,.2f}. Review it and issue it.")
    return redirect(inv.get_absolute_url())


@capability_required("invoices.manage")
def invoice_edit(request, pk):
    inv = get_scoped_or_404(Invoice, request.user, pk, OWNER_FIELDS)
    if inv.status != I.DRAFT:
        raise PermissionDenied("Issued invoices cannot be edited.")
    form = InvoiceForm(request.POST or None, instance=inv, user=request.user)
    formset = InvoiceLineFormSet(request.POST or None, instance=inv, prefix="lines")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        try:
            with transaction.atomic():
                form.save()
                formset.save(commit=False)
                for obj in formset.deleted_objects:
                    obj.delete()
                pos = 0
                for f in formset.forms:
                    if not f.cleaned_data or f.cleaned_data.get("DELETE"):
                        continue
                    pos += 1
                    f.instance.invoice = inv
                    f.instance.position = pos
                    f.instance.save()
                services.recalculate(inv)
        except (ValidationError, ValueError) as exc:
            form.add_error(None, getattr(exc, "messages", [str(exc)]))
        else:
            messages.success(request, "Draft invoice saved.")
            return redirect(inv.get_absolute_url())
    return render(request, "invoicing/edit.html", {"inv": inv, "form": form, "formset": formset})


@require_POST
@capability_required("invoices.manage")
def invoice_issue(request, pk):
    inv = get_scoped_or_404(Invoice, request.user, pk, OWNER_FIELDS)
    try:
        inv = services.issue(inv, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"Invoice {inv.number} issued.")
    return redirect(reverse("invoicing:detail", args=[pk]))


@require_POST
@capability_required("invoices.manage")
def invoice_delete_draft(request, pk):
    inv = get_scoped_or_404(Invoice, request.user, pk, OWNER_FIELDS)
    if inv.status != I.DRAFT:
        raise PermissionDenied("Only drafts can be deleted.")
    order = inv.order
    inv.lines.all().delete()
    inv.delete()
    messages.success(request, "Draft invoice deleted.")
    return redirect(order.get_absolute_url())


@capability_required("invoices.manage")
def invoice_cancel(request, pk):
    inv = get_scoped_or_404(Invoice, request.user, pk, OWNER_FIELDS)
    form = ReasonForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            services.cancel(inv, request.user, form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"Invoice {inv.number} cancelled. Its number is not reused.")
            return redirect(inv.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Cancel invoice {inv.display_number}",
                                              "cancel_url": inv.get_absolute_url(), "submit_label": "Cancel invoice"})


@capability_required("invoices.manage")
def invoice_dispute(request, pk):
    inv = get_scoped_or_404(Invoice, request.user, pk, OWNER_FIELDS)
    form = DisputeForm(request.POST or None, user=request.user,
                       initial={"is_disputed": inv.is_disputed, "dispute_note": inv.dispute_note})
    if request.method == "POST" and form.is_valid():
        Invoice.objects.filter(pk=inv.pk).update(**form.cleaned_data)
        activity.record(inv, "invoice", ("Marked as disputed: " + form.cleaned_data["dispute_note"])
                        if form.cleaned_data["is_disputed"] else "Dispute cleared", customer=inv.customer)
        messages.success(request, "Dispute status saved.")
        return redirect(inv.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Dispute — {inv.display_number}",
                                              "cancel_url": inv.get_absolute_url()})


@capability_required("invoices.view")
def invoice_pdf(request, pk):
    inv = get_scoped_or_404(Invoice, request.user, pk, OWNER_FIELDS)
    return pdf_response("invoicing/pdf.html", {"inv": inv, "lines": inv.lines.all(),
                                               "tax_breakdown": services.tax_breakdown(inv),
                                               "draft": inv.status == I.DRAFT},
                        inv.number or f"draft-invoice-{inv.pk}", download=request.GET.get("download") == "1")


# ------------------------------------------------------------------ payments
class PaymentList(CrmListView):
    model = Payment
    capability = "collections.view"
    title = "Payments received"
    icon = "cash-coin"
    owner_fields = PAYMENT_OWNER_FIELDS
    archive_field = None
    search_fields = ("number", "reference", "customer__company_name")
    create_url = "invoicing:payment_create"
    create_capability = "payments.manage"
    create_label = "Record payment"
    columns = [
        Column("Receipt", "number", link=True), Column("Date", "payment_date", date=True),
        Column("Customer", "customer.company_name"), Column("Method", lambda p: p.get_method_display()),
        Column("Reference", "reference"), Column("Amount", "amount", money=True),
        Column("Unallocated", "unallocated", money=True),
        Column("Type", render=lambda p: badge("Reversal", "bad") if p.is_reversal else
               badge("Reversed", "neutral") if p.is_reversed else badge("Receipt", "good"),
               text=lambda p: "Reversal" if p.is_reversal else "Reversed" if p.is_reversed else "Receipt"),
    ]
    sort_options = {"newest": ("Newest first", ["-payment_date", "-pk"])}
    default_sort = "newest"

    def base_queryset(self):
        return Payment.objects.select_related("customer")

    def get_filters(self):
        return [ChoiceFilter("method", "Method", Payment.Method.choices),
                ModelFilter("customer", "Customer", lambda: _visible_customers(self.request.user)),
                DateRangeFilter("date", "Payment date", "payment_date")]


def _open_invoices(user, customer):
    return scope_queryset(Invoice.objects.filter(customer=customer, status__in=Invoice.OPEN_STATUSES),
                          user, OWNER_FIELDS).order_by("due_date", "pk")


@capability_required("payments.manage")
def payment_create(request):
    customers = _visible_customers(request.user).filter(invoices__status__in=Invoice.OPEN_STATUSES).distinct()
    customer = None
    cid = get_int(request.POST, "customer") or get_int(request.GET, "customer")
    if cid:
        customer = _visible_customers(request.user).filter(pk=cid).first()
    preselect = get_int(request.GET, "invoice")
    form = PaymentForm(request.POST or None, user=request.user)
    invoices = list(_open_invoices(request.user, customer)) if customer else []
    rows, errors = [], []
    for inv in invoices:
        raw = request.POST.get(f"alloc_{inv.pk}", "") if request.method == "POST" else (
            str(inv.outstanding) if preselect == inv.pk else "")
        rows.append({"inv": inv, "value": raw})
    if request.method == "POST" and customer and form.is_valid():
        allocations = []
        for row in rows:
            raw = (row["value"] or "").strip()
            if not raw:
                continue
            try:
                amt = Decimal(raw)
            except InvalidOperation:
                errors.append(f"{row['inv'].display_number}: enter a number.")
                continue
            if amt < 0:
                errors.append(f"{row['inv'].display_number}: allocations cannot be negative.")
                continue
            if amt > 0:
                allocations.append((row["inv"], amt))
        if not errors:
            d = form.cleaned_data
            try:
                payment = services.record_payment(customer=customer, payment_date=d["payment_date"],
                                                  amount=d["amount"], method=d["method"], reference=d["reference"],
                                                  notes=d["notes"], allocations=allocations, user=request.user)
            except ValidationError as exc:
                errors.extend(exc.messages)
            else:
                messages.success(request, f"Payment {payment.number} recorded"
                                          + (f"; {payment.unallocated:,.2f} kept as unallocated credit."
                                             if payment.unallocated else "."))
                return redirect(payment.get_absolute_url())
    return render(request, "invoicing/payment_form.html", {
        "form": form, "customers": customers, "customer": customer, "rows": rows, "errors": errors})


@capability_required("collections.view")
def payment_detail(request, pk):
    payment = get_scoped_or_404(Payment, request.user, pk, PAYMENT_OWNER_FIELDS)
    can_manage = has_capability(request.user, "payments.manage")
    alloc_form = None
    if can_manage and not payment.is_reversal and not payment.is_reversed and payment.unallocated > 0:
        alloc_form = AllocateForm(request.POST or None, user=request.user,
                                  invoices=_open_invoices(request.user, payment.customer))
        if request.method == "POST" and request.POST.get("action") == "allocate" and alloc_form.is_valid():
            try:
                services.allocate(payment, alloc_form.cleaned_data["invoice"], alloc_form.cleaned_data["amount"],
                                  request.user)
            except ValidationError as exc:
                alloc_form.add_error(None, exc.messages)
            else:
                messages.success(request, "Payment allocated.")
                return redirect(payment.get_absolute_url())
    reverse_form = ReasonForm(request.POST if request.POST.get("action") == "reverse" else None, user=request.user)
    if can_manage and request.method == "POST" and request.POST.get("action") == "reverse" and reverse_form.is_valid():
        try:
            rev = services.reverse(payment, request.user, reverse_form.cleaned_data["reason"])
        except ValidationError as exc:
            reverse_form.add_error(None, exc.messages)
        else:
            messages.success(request, f"Payment reversed by {rev.number}. Both entries stay in the history.")
            return redirect(rev.get_absolute_url())
    return render(request, "invoicing/payment_detail.html", {
        "p": payment, "allocations": payment.allocations.select_related("invoice"),
        "alloc_form": alloc_form, "reverse_form": reverse_form,
        "can_reverse": can_manage and not payment.is_reversal and not payment.is_reversed,
        "activities": activity.for_object(payment, request.user)[:20],
    })


# ------------------------------------------------------------------ statement and collections
@capability_required("statements.view")
def statement(request, customer_pk):
    customer = get_scoped_or_404(Customer, request.user, customer_pk, CUSTOMER_OWNERS)
    today = timezone.localdate()
    start = get_date(request.GET, "start") or today.replace(month=1, day=1)
    end = get_date(request.GET, "end") or today
    if end < start:
        start, end = end, start
    form = StatementForm(initial={"start": start, "end": end}, user=request.user)
    data = services.statement(customer, start, end)
    ctx = {"customer": customer, "start": start, "end": end, "form": form, **data}
    fmt = request.GET.get("format")
    if fmt == "pdf":
        activity.record(customer, "invoice", f"Statement of account {start:%d-%b-%Y} – {end:%d-%b-%Y} generated",
                        financial=True)
        return pdf_response("invoicing/statement_pdf.html", ctx, f"statement-{customer.code}-{end:%Y%m%d}",
                            download=request.GET.get("download") == "1")
    if fmt == "xlsx":
        if not has_capability(request.user, "data.export"):
            raise PermissionDenied
        rows = [[e["date"], e["kind"], e["ref"], e["detail"], e["debit"] or None, e["credit"] or None, e["balance"]]
                for e in data["entries"]]
        rows.insert(0, [start, "Opening balance", "", "", None, None, data["opening"]])
        return xlsx_response(f"statement-{customer.code}", ["Date", "Type", "Reference", "Details", "Debit",
                                                            "Credit", "Balance"], rows,
                             title=f"Statement of account — {customer.company_name}",
                             subtitle=f"{start:%d-%b-%Y} to {end:%d-%b-%Y}",
                             totals=["", "Totals", "", "", data["total_debit"], data["total_credit"],
                                     data["closing"]])
    return render(request, "invoicing/statement.html", ctx)


@capability_required("collections.view")
def collections(request):
    u = request.user
    invoices = list(scope_queryset(Invoice.objects.filter(status__in=Invoice.OPEN_STATUSES).select_related(
        "customer", "order"), u, OWNER_FIELDS).order_by("due_date"))
    overdue = [i for i in invoices if i.is_overdue]
    month_start = timezone.localdate().replace(day=1)
    payments = scope_queryset(Payment.objects.all(), u, PAYMENT_OWNER_FIELDS)
    credits = [p for p in payments.filter(is_reversal=False).select_related("customer") if not p.is_reversed
               and p.unallocated > 0]
    ctx = {
        "ageing": services.ageing(invoices),
        "overdue": overdue, "disputed": [i for i in invoices if i.is_disputed],
        "outstanding_total": sum((i.outstanding for i in invoices), Decimal(0)),
        "overdue_total": sum((i.outstanding for i in overdue), Decimal(0)),
        "collected_month": payments.filter(payment_date__gte=month_start).aggregate(t=Sum("amount"))["t"] or 0,
        "credits": credits,
        "can_pay": has_capability(u, "payments.manage"),
    }
    return render(request, "invoicing/collections.html", ctx)

