"""Customer business rules: duplicate detection, archiving."""
from django.db.models import Q
from django.utils import timezone

from core.activity import record
from core.audit import log_action

from .models import Customer, normalize_name, normalize_phone


def find_duplicates(*, company_name="", email="", phone="", trn="", exclude_pk=None):
    """
    Possible duplicates of a customer, with the reason for each match.
    Same TRN is treated as a definite duplicate by the forms (it cannot be saved);
    other matches are warnings the user must confirm.
    """
    name = normalize_name(company_name)
    email = (email or "").strip().lower()
    phone_digits = normalize_phone(phone)
    trn = (trn or "").replace(" ", "").upper()
    cond = Q()
    if name:
        cond |= Q(normalized_name=name)
    if email:
        cond |= Q(email__iexact=email)
    if trn:
        cond |= Q(trn=trn)
    candidates = Customer.objects.filter(cond) if cond else Customer.objects.none()
    if exclude_pk:
        candidates = candidates.exclude(pk=exclude_pk)
    results = {}
    for c in candidates:
        reasons = []
        if name and c.normalized_name == name:
            reasons.append("same company name")
        if email and c.email == email:
            reasons.append("same email")
        if trn and c.trn == trn:
            reasons.append("same TRN")
        results[c.pk] = (c, reasons)
    if len(phone_digits) >= 7:
        qs = Customer.objects.exclude(phone="")
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        for c in qs.only("pk", "phone", "alt_phone", "company_name", "code", "email", "trn", "normalized_name"):
            if phone_digits in (normalize_phone(c.phone), normalize_phone(c.alt_phone)):
                results.setdefault(c.pk, (c, []))[1].append("same phone")
    return [{"customer": c, "reasons": r, "definite": "same TRN" in r} for c, r in results.values()]


def archive(customer, *, archived=True):
    customer.is_archived = archived
    customer.archived_at = timezone.now() if archived else None
    customer.save(update_fields=["is_archived", "archived_at", "updated_at", "updated_by"])
    record(customer, "status", "Archived" if archived else "Restored from archive")
    log_action("archive" if archived else "update", customer,
               message="Customer archived" if archived else "Customer restored")
