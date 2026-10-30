"""
Quotations prepared in the external quotation system and uploaded to the CRM.

    Original  -> R1 -> R2 -> ... ; any one of them can be marked Final (normally the latest).

Rules:
* Every revision keeps its own file; files are never replaced or deleted (a change = a new revision).
* The quotation number, customer, lead and opportunity stay the same across revisions, so a quotation is ONE
  quotation in every report however many revisions it has; only the current revision's value and status count.
* Uploaded quotations use the same approval flow as quotations prepared in the CRM (submit -> Owner approves).
* Quotation values are never sales revenue: revenue comes only from won opportunities.
"""
import hashlib
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.activity import record
from core.audit import log_action
from core.models import CompanyProfile

from .models import Quotation, QuotationFile, QuotationRevision

S = QuotationRevision.Status
QUOTATION_FILE_TYPES = {"pdf", "docx", "doc", "xlsx", "xls", "png", "jpg", "jpeg"}
HARD_LIMIT_MB = 15  # files are stored in the database; keep each one reasonable
UPLOAD_REVISABLE = (S.DRAFT, S.REJECTED, S.APPROVED, S.SENT, S.DECLINED, S.EXPIRED, S.ACCEPTED)


def validate_quotation_file(f):
    """Same checks as Documents (allowed type, size, real content) plus the quotation-specific type list."""
    from documents.services import MIME, validate_upload

    name, ext = validate_upload(f)
    if ext not in QUOTATION_FILE_TYPES:
        raise ValidationError("Upload the quotation as PDF, Word, Excel or an image (PDF recommended).")
    if f.size > HARD_LIMIT_MB * 1024 * 1024:
        raise ValidationError(f"Quotation files can be at most {HARD_LIMIT_MB} MB.")
    return name, MIME.get(ext, "application/octet-stream")


def _store(revision, f, user):
    name, mime = validate_quotation_file(f)
    f.seek(0)
    data = f.read()
    return QuotationFile.objects.create(revision=revision, original_name=name[:255], content_type=mime,
                                        size=len(data), sha256=hashlib.sha256(data).hexdigest(), data=data,
                                        uploaded_by=user)


def _validity_end(date):
    return date + timezone.timedelta(days=CompanyProfile.get().quotation_validity_days)


def _set_value(rev, value):
    value = Decimal(value).quantize(Decimal("0.01"))
    if value <= 0:
        raise ValidationError("Enter the quotation value (greater than zero).")
    rev.subtotal = rev.taxable_amount = rev.grand_total = value
    rev.discount_total = rev.tax_amount = Decimal("0.00")


@transaction.atomic
def create_uploaded(*, customer, salesperson, user, file, value, quotation_date, expiry_date=None,
                    external_number="", opportunity=None, lead=None, notes="", is_final=False, currency="AED"):
    q = Quotation(customer=customer, salesperson=salesperson, opportunity=opportunity, lead=lead,
                  currency=currency, source=Quotation.Source.UPLOADED, external_number=external_number.strip())
    q.save()
    rev = QuotationRevision(quotation=q, version=1, quotation_date=quotation_date, currency=currency,
                            expiry_date=expiry_date or _validity_end(quotation_date), revision_notes=notes,
                            is_final=is_final, internal_remarks=notes)
    _set_value(rev, value)
    rev.save()
    _store(rev, file, user)
    q.sync_from_current()
    record(q, "created", f"Quotation uploaded ({rev.label}): {file.name}")
    log_action("create", q, message=f"Uploaded quotation {q.number} {rev.label} ({currency} {rev.grand_total:,.2f})")
    return q


@transaction.atomic
def upload_revision(quotation, *, user, file, value, quotation_date, expiry_date=None, notes="", is_final=False):
    """Add R1, R2 … as a new revision; the previous revision and its file stay unchanged (superseded)."""
    q = Quotation.objects.select_for_update().get(pk=quotation.pk)
    if not q.is_uploaded:
        raise ValidationError("This quotation was prepared in the CRM. Use 'Create revision' instead.")
    old = q.revisions.get(version=q.current_version)
    if old.status == S.SUBMITTED:
        raise ValidationError("This quotation is waiting for approval. Wait for the decision before uploading "
                              "a revision.")
    if old.status not in UPLOAD_REVISABLE:
        raise ValidationError("A new revision cannot be uploaded at this stage.")
    if old.status == S.ACCEPTED and old.orders.exclude(status="cancelled").exists():
        raise ValidationError("A sales order exists for this quotation. Cancel the order before revising.")
    new = QuotationRevision(quotation=q, version=old.version + 1, quotation_date=quotation_date,
                            currency=old.currency, expiry_date=expiry_date or _validity_end(quotation_date),
                            revision_notes=notes, revision_reason=(notes or "")[:255], is_final=is_final,
                            internal_remarks=notes)
    _set_value(new, value)
    new.save()
    _store(new, file, user)
    if is_final:
        q.revisions.exclude(pk=new.pk).filter(is_final=True).update(is_final=False)
    old.status = S.SUPERSEDED
    old.save(update_fields=["status", "updated_at", "updated_by"])
    q.current_version = new.version
    q.save(update_fields=["current_version", "updated_at", "updated_by"])
    if hasattr(q, "_current"):
        del q._current
    q.sync_from_current()
    record(q, "revision", f"{new.label} uploaded ({file.name})" + (f": {notes}" if notes else ""))
    log_action("update", q, message=f"Uploaded {new.label} of {q.number} ({q.currency} {new.grand_total:,.2f})")
    return new


@transaction.atomic
def mark_final(quotation, user):
    """Mark the CURRENT revision as the Final quotation (only one revision can be Final)."""
    q = Quotation.objects.select_for_update().get(pk=quotation.pk)
    cur = q.revisions.get(version=q.current_version)
    if cur.status in (S.SUPERSEDED,):
        raise ValidationError("Only the latest revision can be marked as final.")
    q.revisions.exclude(pk=cur.pk).filter(is_final=True).update(is_final=False)
    cur.is_final = True
    cur.save(update_fields=["is_final", "updated_at", "updated_by"])
    record(q, "status", f"{cur.revision_code} marked as the final quotation")
    log_action("update", q, message=f"{cur.revision_code} of {q.number} marked as final")
    return cur


def submit_checks(rev):
    """Extra checks used by services.submit for an uploaded revision (instead of the line checks)."""
    if not QuotationFile.objects.filter(revision=rev).exists():
        raise ValidationError("Upload the quotation document before submitting.")
    if rev.grand_total <= 0:
        raise ValidationError("Enter the quotation value before submitting.")
