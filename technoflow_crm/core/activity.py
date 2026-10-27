"""
Business activity timeline.

    record(quotation, "approval", "Approved revision 2", customer=quotation.customer)

Entries appear on the record's own page and on the customer's timeline.
Financial entries (invoices, payments) are only shown to users who can see invoices.
"""
from django.contrib.contenttypes.models import ContentType

from .middleware import get_current_user
from .models import Activity

FINANCIAL_KINDS = {"invoice", "payment"}


def record(obj, kind, message, *, customer=None, user=None, financial=None):
    if user is None:
        current = get_current_user()
        user = current if current is not None and current.is_authenticated else None
    if customer is None:
        customer = getattr(obj, "customer", None)
        if customer is None and obj.__class__.__name__ == "Customer":
            customer = obj
    return Activity.objects.create(
        user=user, kind=kind, message=message[:500],
        content_type=ContentType.objects.get_for_model(obj.__class__), object_id=obj.pk,
        object_repr=str(obj)[:255], customer=customer,
        financial=kind in FINANCIAL_KINDS if financial is None else financial,
    )


def for_object(obj, user=None):
    qs = Activity.objects.filter(content_type=ContentType.objects.get_for_model(obj.__class__), object_id=obj.pk)
    return _visible(qs.select_related("user"), user)


def for_customer(customer, user=None):
    return _visible(Activity.objects.filter(customer=customer).select_related("user", "content_type"), user)


def _visible(qs, user):
    from accounts.permissions import has_capability

    if user is not None and not has_capability(user, "invoices.view"):
        qs = qs.filter(financial=False)
    return qs
