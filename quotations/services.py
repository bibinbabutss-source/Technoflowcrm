"""
Quotation workflow (Phase 1 plan, workflow C):

  Draft → Submit → [Sales Director approves / rejects] → Approved → Sent → Accepted / Declined
                                                  ↘ Rejected → Revise (new version)
  Approved / Sent / Declined / Expired → Revise → new Draft version (old one Superseded)

Once a revision leaves Draft it is locked: its amounts cannot change. Changes need a new revision.
"""
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.activity import record
from core.audit import log_action
from core.models import CompanyProfile
from core.money import LineInput, calculate

from .models import Approval, Quotation, QuotationLine, QuotationRevision, QuotationTemplate, QuotationTerm

S = QuotationRevision.Status


def recalculate(revision):
    """Recalculate every line and the revision totals from the stored lines (the only way totals are set)."""
    lines = list(revision.lines.select_related("tax_rate"))
    inputs = [LineInput(ln.quantity, ln.unit_price, ln.discount_pct, ln.tax_rate.rate) for ln in lines]
    totals = calculate(inputs, revision.header_discount)
    for ln, res in zip(lines, totals.lines):
        ln.tax_rate_value = ln.tax_rate.rate
        ln.line_net = res.net
        ln.line_tax = res.tax
        QuotationLine.objects.filter(pk=ln.pk).update(tax_rate_value=ln.tax_rate_value, line_net=res.net,
                                                      line_tax=res.tax)
    revision.subtotal = totals.subtotal
    revision.discount_total = totals.discount_total
    revision.taxable_amount = totals.taxable
    revision.tax_amount = totals.tax
    revision.grand_total = totals.grand_total
    revision.save(update_fields=["subtotal", "discount_total", "taxable_amount", "tax_amount", "grand_total",
                                 "updated_at", "updated_by"])
    revision.quotation.sync_from_current()
    return totals


def tax_breakdown(revision):
    inputs = [LineInput(ln.quantity, ln.unit_price, ln.discount_pct, ln.tax_rate_value)
              for ln in revision.lines.all()]
    return calculate(inputs, revision.header_discount).tax_by_rate


def approval_needed(revision):
    """Returns (needed, reason) according to Settings > approval rules."""
    company = CompanyProfile.get()
    reasons = []
    if revision.grand_total >= company.approval_threshold:
        if company.approval_threshold > 0:
            reasons.append(f"grand total at or above {company.default_currency} {company.approval_threshold:,.2f}")
        else:
            reasons.append("all quotations need approval")
    max_disc = revision.max_discount_pct
    if max_disc > company.discount_approval_limit:
        reasons.append(f"line discount {max_disc}% above {company.discount_approval_limit}%")
    if revision.subtotal and revision.header_discount:
        pct = revision.header_discount / revision.subtotal * Decimal(100)
        if pct > company.discount_approval_limit:
            reasons.append(f"overall discount {pct:.1f}% above {company.discount_approval_limit}%")
    return bool(reasons), "; ".join(reasons)


def _set_status(rev, status, **fields):
    rev.status = status
    for k, v in fields.items():
        setattr(rev, k, v)
    rev.save()
    rev.quotation.sync_from_current()


def _approvers(exclude):
    """Who is asked to approve: the Owner(s); the Sales Director only when allowed as backup (see approvals)."""
    from owner.rules import approver_users

    return [u for u in approver_users() if u not in exclude]


def _check_current(rev):
    if not rev.is_current:
        raise ValidationError("Only the current revision can be changed. Open the latest revision.")


@transaction.atomic
def submit(rev, user):
    from notifications.services import notify

    rev = QuotationRevision.objects.select_for_update().get(pk=rev.pk)
    _check_current(rev)
    if rev.status != S.DRAFT:
        raise ValidationError("Only a draft can be submitted.")
    uploaded = rev.quotation.is_uploaded
    if uploaded:
        from .uploads import submit_checks

        submit_checks(rev)
    elif not rev.lines.exists():
        raise ValidationError("Add at least one line before submitting.")
    if rev.grand_total <= 0:
        raise ValidationError("The grand total must be greater than zero.")
    if rev.expiry_date < rev.quotation_date:
        raise ValidationError("The expiry date cannot be before the quotation date.")
    if rev.expiry_date < timezone.localdate():
        raise ValidationError("The expiry date has already passed. Change it before submitting.")
    if not uploaded:
        recalculate(rev)  # never trust stored totals at the moment of locking
    needed, reason = approval_needed(rev)
    rev.approval_required = needed
    rev.approval_reason = reason
    rev.is_locked = True
    rev.submitted_at = timezone.now()
    rev.submitted_by = user
    q = rev.quotation
    if needed:
        _set_status(rev, S.SUBMITTED)
        record(q, "approval", f"Rev {rev.version} submitted for approval ({reason}); "
                              f"grand total {q.currency} {rev.grand_total:,.2f}")
        approvers = _approvers({user, q.salesperson, rev.created_by})
        notify(approvers, "quotation_pending", f"Quotation awaiting approval: {q.number} Rev {rev.version}",
               f"{q.customer.company_name} · {q.currency} {rev.grand_total:,.2f}", q.get_absolute_url())
    else:
        Approval.objects.create(revision=rev, decision=Approval.Decision.AUTO, decided_by=None,
                                comments="Within approval limits", grand_total=rev.grand_total)
        _set_status(rev, S.APPROVED, decided_at=timezone.now(), decision_comments="Within approval limits")
        record(q, "approval", f"Rev {rev.version} approved automatically (within approval limits)")
    return rev


def _can_decide(rev, user):
    from owner.rules import may_approve

    q = rev.quotation
    allowed, why = may_approve(user)
    if not allowed:
        raise PermissionDenied(why)
    if user.pk in (q.salesperson_id, rev.created_by_id, rev.submitted_by_id, q.created_by_id):
        raise PermissionDenied("You cannot approve or reject a quotation you prepared or are the salesperson for.")


@transaction.atomic
def approve(rev, user, comments=""):
    from notifications.services import notify

    rev = QuotationRevision.objects.select_for_update().get(pk=rev.pk)
    _check_current(rev)
    _can_decide(rev, user)
    if rev.status != S.SUBMITTED:
        raise ValidationError("Only a quotation awaiting approval can be approved.")
    Approval.objects.create(revision=rev, decision=Approval.Decision.APPROVED, decided_by=user, comments=comments,
                            grand_total=rev.grand_total)
    _set_status(rev, S.APPROVED, decided_at=timezone.now(), decided_by=user, decision_comments=comments)
    q = rev.quotation
    record(q, "approval", f"Rev {rev.version} approved by {user.get_full_name()}" + (f": {comments}" if comments else ""))
    log_action("approve", q, message=f"Approved revision {rev.version} ({q.currency} {rev.grand_total:,.2f})")
    notify(_people(q, rev, user), "quotation_decision", f"Quotation approved: {q.number} Rev {rev.version}",
           comments or "Approved", q.get_absolute_url())
    return rev


@transaction.atomic
def reject(rev, user, comments):
    from notifications.services import notify

    if not (comments or "").strip():
        raise ValidationError("Give a reason when rejecting a quotation.")
    rev = QuotationRevision.objects.select_for_update().get(pk=rev.pk)
    _check_current(rev)
    _can_decide(rev, user)
    if rev.status != S.SUBMITTED:
        raise ValidationError("Only a quotation awaiting approval can be rejected.")
    Approval.objects.create(revision=rev, decision=Approval.Decision.REJECTED, decided_by=user, comments=comments,
                            grand_total=rev.grand_total)
    _set_status(rev, S.REJECTED, decided_at=timezone.now(), decided_by=user, decision_comments=comments)
    q = rev.quotation
    record(q, "approval", f"Rev {rev.version} rejected by {user.get_full_name()}: {comments}")
    log_action("reject", q, message=f"Rejected revision {rev.version}: {comments}")
    notify(_people(q, rev, user), "quotation_decision", f"Quotation rejected: {q.number} Rev {rev.version}",
           comments, q.get_absolute_url())
    return rev


def _people(q, rev, exclude):
    people = {q.salesperson, rev.created_by, rev.submitted_by}
    return [p for p in people if p is not None and p != exclude]


@transaction.atomic
def mark_sent(rev, user):
    rev = QuotationRevision.objects.select_for_update().get(pk=rev.pk)
    _check_current(rev)
    if rev.status != S.APPROVED:
        raise ValidationError("Only an approved quotation can be issued to the customer.")
    if rev.is_past_expiry:
        raise ValidationError("This quotation has expired. Create a revision with a new expiry date.")
    _set_status(rev, S.SENT, sent_at=timezone.now())
    record(rev.quotation, "status", f"Rev {rev.version} sent to the customer")
    return rev


@transaction.atomic
def record_acceptance(rev, user, *, date, accepted_by_name, customer_reference=""):
    rev = QuotationRevision.objects.select_for_update().get(pk=rev.pk)
    _check_current(rev)
    if rev.status not in (S.SENT, S.APPROVED):
        raise ValidationError("Only an approved or sent quotation can be accepted.")
    if date > timezone.localdate():
        raise ValidationError("The acceptance date cannot be in the future.")
    if date > rev.expiry_date:
        raise ValidationError("The customer accepted after the expiry date. Create a revision with a new validity.")
    _set_status(rev, S.ACCEPTED, customer_response_at=date, accepted_by_name=accepted_by_name,
                customer_reference=customer_reference)
    q = rev.quotation
    record(q, "status", f"Rev {rev.version} accepted by {accepted_by_name} on {date:%d-%b-%Y}"
                        + (f" (PO {customer_reference})" if customer_reference else ""))
    return rev


@transaction.atomic
def record_decline(rev, user, *, date, reason):
    rev = QuotationRevision.objects.select_for_update().get(pk=rev.pk)
    _check_current(rev)
    if rev.status not in (S.SENT, S.APPROVED):
        raise ValidationError("Only an approved or sent quotation can be declined.")
    _set_status(rev, S.DECLINED, customer_response_at=date, decline_reason=reason)
    record(rev.quotation, "status", f"Rev {rev.version} declined by the customer: {reason}")
    return rev


REVISABLE = (S.REJECTED, S.APPROVED, S.SENT, S.DECLINED, S.EXPIRED, S.ACCEPTED)

COPY_FIELDS = ("currency", "payment_terms", "delivery_terms", "scope_of_work", "exclusions", "warranty_terms",
               "validity", "customer_notes", "internal_remarks", "header_discount") + QuotationRevision.DOCUMENT_FIELDS


@transaction.atomic
def revise(quotation, user, reason=""):
    """Create a new draft revision copying the current one; the old revision stays unchanged (superseded)."""
    quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
    old = quotation.revisions.get(version=quotation.current_version)
    if old.status not in REVISABLE:
        raise ValidationError("This quotation cannot be revised while it is a draft or awaiting approval.")
    if old.status == S.ACCEPTED and old.orders.exclude(status="cancelled").exists():
        raise ValidationError("A sales order exists for this revision. Cancel the order before revising.")
    company = CompanyProfile.get()
    new = QuotationRevision(quotation=quotation, version=old.version + 1, quotation_date=timezone.localdate(),
                            expiry_date=timezone.localdate() + timezone.timedelta(days=company.quotation_validity_days),
                            revision_reason=reason, **{f: getattr(old, f) for f in COPY_FIELDS})
    new.save()
    for ln in old.lines.all():
        QuotationLine.objects.create(revision=new, position=ln.position, part_no=ln.part_no,
                                     description=ln.description,
                                     quantity=ln.quantity, unit=ln.unit, unit_price=ln.unit_price,
                                     discount_pct=ln.discount_pct, tax_rate=ln.tax_rate)
    from .document import legacy_terms

    terms = [(t.heading, t.content) for t in old.terms.all()] or legacy_terms(old)
    for pos, (heading, content) in enumerate(terms, start=1):
        QuotationTerm.objects.create(revision=new, position=pos, heading=heading, content=content)
    old.status = S.SUPERSEDED
    old.save(update_fields=["status", "updated_at", "updated_by"])
    quotation.current_version = new.version
    quotation.save(update_fields=["current_version", "updated_at", "updated_by"])
    if hasattr(quotation, "_current"):
        del quotation._current
    recalculate(new)
    record(quotation, "revision", f"Revision {new.version} created from Rev {old.version}"
                                  + (f": {reason}" if reason else ""))
    return new


def expire_overdue():
    """Daily job: approved / sent quotations past their expiry date become Expired."""
    today = timezone.localdate()
    count = 0
    for rev in QuotationRevision.objects.filter(status__in=(S.APPROVED, S.SENT), expiry_date__lt=today).select_related(
            "quotation"):
        if not rev.is_current:
            continue
        _set_status(rev, S.EXPIRED)
        record(rev.quotation, "status", f"Rev {rev.version} expired on {rev.expiry_date:%d-%b-%Y}", user=None)
        count += 1
    return count


@transaction.atomic
def create_quotation(*, customer, opportunity, salesperson, currency, user, with_template=True):
    company = CompanyProfile.get()
    q = Quotation.objects.create(customer=customer, opportunity=opportunity, salesperson=salesperson,
                                 currency=currency or company.default_currency)
    rev = QuotationRevision.objects.create(
        quotation=q, version=1, currency=q.currency, quotation_date=timezone.localdate(),
        expiry_date=timezone.localdate() + timezone.timedelta(days=company.quotation_validity_days),
        validity=f"This quotation is valid for {company.quotation_validity_days} days from its date.",
        payment_terms=f"{company.default_payment_terms_days} days from invoice date.")
    if with_template:
        apply_template_defaults(rev)
    q.sync_from_current()
    record(q, "created", f"Quotation {q.number} created")
    return q, rev


def apply_template_defaults(rev):
    """New revision: cover-letter wording and commercial terms from Settings > Quotation template."""
    tpl = QuotationTemplate.get()
    for field in ("letter_body", "letter_closing", "signatory_designation", "schedule_note"):
        if not getattr(rev, field):
            setattr(rev, field, getattr(tpl, field))
    rev.save()
    if not rev.terms.exists():
        for pos, row in enumerate(tpl.default_terms or [], start=1):
            if len(row) == 2 and str(row[0]).strip():
                QuotationTerm.objects.create(revision=rev, position=pos, heading=str(row[0])[:100],
                                             content=str(row[1]))
