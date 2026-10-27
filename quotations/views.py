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
from core.crud import (ChoiceFilter, Column, CrmListView, DateRangeFilter, UserFilter, badge, get_scoped_or_404,
                       money)
from core.params import get_int
from core.pdf import pdf_response
from customers.models import Customer
from sales.models import Opportunity

from . import services
from .forms import AcceptanceForm, DecisionForm, DeclineForm, LineFormSet, QuotationForm, ReviseForm, RevisionForm
from .models import OWNER_FIELDS, Quotation, QuotationRevision

S = QuotationRevision.Status
TONE = {"draft": "neutral", "submitted": "warn", "approved": "info", "rejected": "bad", "sent": "info",
        "accepted": "good", "declined": "bad", "expired": "neutral", "superseded": "neutral"}


def status_cell(q):
    return badge(S(q.status).label if q.status in S.values else q.status, TONE.get(q.status, "neutral"))


class QuotationList(CrmListView):
    model = Quotation
    capability = "quotations.view"
    title = "Quotations"
    icon = "file-earmark-text"
    owner_fields = OWNER_FIELDS
    archive_field = None
    search_fields = ("number", "customer__company_name", "opportunity__title", "revisions__lines__description")
    create_url = "quotations:create"
    create_capability = "quotations.edit"
    create_label = "New quotation"
    columns = [
        Column("Number", lambda q: q.display_number, link=True),
        Column("Date", "quotation_date", date=True),
        Column("Customer", "customer.company_name"),
        Column("Opportunity", lambda q: q.opportunity.title if q.opportunity_id else "—"),
        Column("Salesperson", "salesperson"),
        Column("Grand total", "grand_total", money=True),
        Column("Currency", "currency"),
        Column("Expiry", "expiry_date", date=True),
        Column("Status", render=status_cell, text=lambda q: S(q.status).label),
    ]
    sort_options = {"newest": ("Newest first", ["-created_at"]), "value": ("Highest value", ["-grand_total"]),
                    "expiry": ("Expiry date", ["expiry_date"])}
    default_sort = "newest"

    def base_queryset(self):
        return Quotation.objects.select_related("customer", "opportunity", "salesperson")

    def get_filters(self):
        soon = timezone.localdate() + timezone.timedelta(days=14)
        return [
            ChoiceFilter("status", "Status", [(k, v) for k, v in S.choices if k != "superseded"]),
            ChoiceFilter("special", "Show", [("expiring", "Expiring in 14 days"), ("open", "Not yet decided")],
                         lookups={"expiring": Q(status__in=["approved", "sent"], expiry_date__lte=soon),
                                  "open": Q(status__in=["draft", "submitted", "approved", "sent"])}),
            UserFilter("employee", "Salesperson", ["salesperson"]),
            DateRangeFilter("date", "Quotation date", "quotation_date"),
            DateRangeFilter("sent", "Sent to customer", "revisions__sent_at"),
        ]

    def summary(self, qs):
        def total(status):
            return money(qs.filter(status__in=status).aggregate(v=Sum("grand_total"))["v"] or 0)
        return [("Awaiting approval", qs.filter(status="submitted").count()),
                ("Approved / sent (value)", total(["approved", "sent"])),
                ("Accepted (value)", total(["accepted"])),
                ("Quotations", qs.count())]


def _render_editor(request, qform, rform, formset, title, quotation=None):
    from core.models import TaxRate

    return render(request, "quotations/edit.html", {
        "qform": qform, "rform": rform, "formset": formset, "title": title, "quotation": quotation,
        "no_tax_rates": not TaxRate.objects.filter(is_active=True).exists(),
    })


@capability_required("quotations.edit")
def quotation_create(request):
    initial = {}
    for key in ("customer", "opportunity"):
        pk = get_int(request.GET, key)
        if pk:
            initial[key] = pk
    if initial.get("opportunity") and not initial.get("customer"):
        opp = Opportunity.objects.filter(pk=initial["opportunity"]).first()
        if opp:
            initial["customer"] = opp.customer_id
    qform = QuotationForm(request.POST or None, initial=initial, user=request.user, prefix="q")
    draft = QuotationRevision(quotation_date=timezone.localdate())
    rform = RevisionForm(request.POST or None, user=request.user, prefix="r", initial={
        "quotation_date": timezone.localdate(),
        "expiry_date": timezone.localdate() + timezone.timedelta(days=_company().quotation_validity_days),
        "validity": f"This quotation is valid for {_company().quotation_validity_days} days from its date.",
        "payment_terms": f"{_company().default_payment_terms_days} days from invoice date."})
    formset = LineFormSet(request.POST or None, instance=draft, prefix="lines")
    if request.method == "POST" and qform.is_valid() and rform.is_valid() and formset.is_valid():
        try:
            with transaction.atomic():
                d = qform.cleaned_data
                q, rev = services.create_quotation(customer=d["customer"], opportunity=d["opportunity"],
                                                   salesperson=d["salesperson"], currency=d["currency"],
                                                   user=request.user)
                for field in rform.Meta.fields:
                    setattr(rev, field, rform.cleaned_data[field])
                rev.save()
                _save_lines(formset, rev)
                services.recalculate(rev)
        except (ValidationError, ValueError) as exc:
            rform.add_error(None, getattr(exc, "messages", [str(exc)]))
        else:
            messages.success(request, f"Quotation {q.number} saved as draft.")
            return redirect(q.get_absolute_url())
    return _render_editor(request, qform, rform, formset, "New quotation")


def _company():
    from core.models import CompanyProfile

    return CompanyProfile.get()


def _save_lines(formset, rev):
    formset.instance = rev
    lines = formset.save(commit=False)
    for obj in formset.deleted_objects:
        obj.delete()
    position = 0
    for form in formset.ordered_forms if formset.can_order else formset.forms:
        if not form.cleaned_data or form.cleaned_data.get("DELETE"):
            continue
        obj = form.instance
        position += 1
        obj.revision = rev
        obj.position = position
        obj.save()
    return lines


@capability_required("quotations.edit")
def quotation_edit(request, pk):
    q = get_scoped_or_404(Quotation, request.user, pk, OWNER_FIELDS)
    rev = q.current
    if not rev.is_editable:
        raise PermissionDenied("Only a draft can be edited. Create a new revision to change an issued quotation.")
    qform = QuotationForm(request.POST or None, instance=q, user=request.user, prefix="q")
    if rev.version > 1:
        for name in ("customer", "currency"):
            qform.fields[name].disabled = True
    rform = RevisionForm(request.POST or None, instance=rev, user=request.user, prefix="r")
    formset = LineFormSet(request.POST or None, instance=rev, prefix="lines")
    if request.method == "POST" and qform.is_valid() and rform.is_valid() and formset.is_valid():
        try:
            with transaction.atomic():
                q = qform.save()
                rev = rform.save(commit=False)
                rev.currency = q.currency
                rev.save()
                _save_lines(formset, rev)
                services.recalculate(rev)
        except (ValidationError, ValueError) as exc:
            rform.add_error(None, getattr(exc, "messages", [str(exc)]))
        else:
            activity.record(q, "updated", f"Draft Rev {rev.version} edited — total {q.currency} {rev.grand_total:,.2f}")
            messages.success(request, f"{q.display_number} saved.")
            return redirect(q.get_absolute_url())
    return _render_editor(request, qform, rform, formset, f"Edit {q.display_number}", q)


@capability_required("quotations.view")
def quotation_detail(request, pk):
    q = get_scoped_or_404(Quotation, request.user, pk, OWNER_FIELDS)
    version = get_int(request.GET, "rev", q.current_version)
    rev = q.revisions.filter(version=version).first() or q.current
    u = request.user
    is_current = rev.version == q.current_version
    own = u.pk in (q.salesperson_id, rev.created_by_id, rev.submitted_by_id, q.created_by_id)
    can_edit = has_capability(u, "quotations.edit")
    can_submit = has_capability(u, "quotations.submit")
    actions = {
        "edit": is_current and can_edit and rev.status == S.DRAFT,
        "submit": is_current and can_submit and rev.status == S.DRAFT,
        "decide": is_current and has_capability(u, "quotations.approve") and rev.status == S.SUBMITTED and not own,
        "decide_blocked_own": is_current and has_capability(u, "quotations.approve") and rev.status == S.SUBMITTED
        and own,
        "send": is_current and can_submit and rev.status == S.APPROVED,
        "respond": is_current and can_submit and rev.status in (S.APPROVED, S.SENT),
        "revise": is_current and can_edit and rev.status in services.REVISABLE and not (
            rev.status == S.ACCEPTED and rev.orders.exclude(status="cancelled").exists()),
        "convert": is_current and has_capability(u, "quotations.convert") and rev.status == S.ACCEPTED
        and not rev.orders.exclude(status="cancelled").exists(),
        "delete": q.current_version == 1 and rev.status == S.DRAFT and (q.created_by_id == u.pk or
                                                                          has_capability(u, "users.manage")),
    }
    return render(request, "quotations/detail.html", {
        "q": q, "rev": rev, "lines": rev.lines.select_related("tax_rate"), "is_current": is_current,
        "revisions": q.revisions.all(), "approvals": rev.approvals.select_related("decided_by"),
        "tax_breakdown": services.tax_breakdown(rev) if rev.lines.exists() else {},
        "orders": rev.orders.all(), "actions": actions,
        "decision_form": DecisionForm(), "activities": activity.for_object(q, u)[:30],
    })


def _get_current(request, pk):
    q = get_scoped_or_404(Quotation, request.user, pk, OWNER_FIELDS)
    return q, q.current


def _run(request, q, fn, success):
    try:
        fn()
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, success)
    return redirect(q.get_absolute_url())


@require_POST
@capability_required("quotations.submit")
def quotation_submit(request, pk):
    q, rev = _get_current(request, pk)

    def go():
        result = services.submit(rev, request.user)
        if result.status == S.APPROVED:
            messages.info(request, "No approval was needed: the quotation is within the approval limits.")
    return _run(request, q, go, f"{q.number} Rev {rev.version} submitted.")


@require_POST
@capability_required("quotations.approve")
def quotation_decide(request, pk):
    q, rev = _get_current(request, pk)
    form = DecisionForm(request.POST)
    form.is_valid()
    comments = form.cleaned_data.get("comments", "")
    if request.POST.get("decision") == "approve":
        return _run(request, q, lambda: services.approve(rev, request.user, comments), f"{q.number} approved.")
    if request.POST.get("decision") == "reject":
        return _run(request, q, lambda: services.reject(rev, request.user, comments), f"{q.number} rejected.")
    messages.error(request, "Choose approve or reject.")
    return redirect(q.get_absolute_url())


@require_POST
@capability_required("quotations.submit")
def quotation_send(request, pk):
    q, rev = _get_current(request, pk)
    return _run(request, q, lambda: services.mark_sent(rev, request.user),
                f"{q.number} marked as sent to the customer.")


@capability_required("quotations.submit")
def quotation_accept(request, pk):
    q, rev = _get_current(request, pk)
    form = AcceptanceForm(request.POST or None, user=request.user, initial={
        "date": timezone.localdate(), "accepted_by_name": q.customer.contact_person})
    if request.method == "POST" and form.is_valid():
        try:
            services.record_acceptance(rev, request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"{q.number} accepted by the customer.")
            return redirect(q.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Record customer acceptance — "
                                                                      f"{q.display_number}",
                                              "cancel_url": q.get_absolute_url(), "submit_label": "Record acceptance"})


@capability_required("quotations.submit")
def quotation_decline(request, pk):
    q, rev = _get_current(request, pk)
    form = DeclineForm(request.POST or None, user=request.user, initial={"date": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        try:
            services.record_decline(rev, request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"{q.number} recorded as declined.")
            return redirect(q.get_absolute_url())
    return render(request, "crud/form.html", {"form": form, "title": f"Customer declined — {q.display_number}",
                                              "cancel_url": q.get_absolute_url()})


@capability_required("quotations.edit")
def quotation_revise(request, pk):
    q, rev = _get_current(request, pk)
    form = ReviseForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            new = services.revise(q, request.user, form.cleaned_data["reason"])
        except ValidationError as exc:
            form.add_error(None, exc.messages)
        else:
            messages.success(request, f"Revision {new.version} created as a draft. Rev {rev.version} is kept unchanged.")
            return redirect(reverse("quotations:edit", args=[q.pk]))
    return render(request, "crud/form.html", {"form": form, "title": f"Revise {q.display_number}",
                                              "cancel_url": q.get_absolute_url(), "submit_label": "Create revision"})


@capability_required("quotations.view")
def quotation_pdf(request, pk):
    q = get_scoped_or_404(Quotation, request.user, pk, OWNER_FIELDS)
    rev = q.revisions.filter(version=get_int(request.GET, "rev", q.current_version)).first() or q.current
    activity.record(q, "status", f"PDF of Rev {rev.version} generated")
    return pdf_response("quotations/pdf.html", {
        "q": q, "rev": rev, "lines": rev.lines.select_related("tax_rate"),
        "tax_breakdown": services.tax_breakdown(rev) if rev.lines.exists() else {},
        "draft": rev.status in (S.DRAFT, S.SUBMITTED, S.REJECTED),
    }, f"{q.number}-Rev{rev.version}", download=request.GET.get("download") == "1")


@require_POST
@capability_required("quotations.edit")
def quotation_delete(request, pk):
    q, rev = _get_current(request, pk)
    if not (q.current_version == 1 and rev.status == S.DRAFT and (
            q.created_by_id == request.user.pk or has_capability(request.user, "users.manage"))):
        raise PermissionDenied("Only an unsubmitted first draft can be deleted, by its author or the administrator.")
    number = q.number
    from core.audit import log_action

    from django.db.models import ProtectedError

    try:
        with transaction.atomic():
            log_action("delete", q, message=f"Draft quotation {number} deleted (number not reused)")
            q.delete()
    except ProtectedError:
        messages.error(request, "This quotation has linked tasks or documents. Remove them first.")
        return redirect(q.get_absolute_url())
    messages.success(request, f"Draft quotation {number} deleted.")
    return redirect("quotations:list")


def scoped_customers(user):
    from customers.models import OWNER_FIELDS as CO

    return scope_queryset(Customer.objects.filter(is_archived=False), user, CO)
