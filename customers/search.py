from django.db.models import Q

from accounts.permissions import scope_queryset

from .models import OWNER_FIELDS, Customer


def search(user, q):
    qs = scope_queryset(Customer.objects.all(), user, OWNER_FIELDS).filter(
        Q(code__icontains=q) | Q(company_name__icontains=q) | Q(contact_person__icontains=q) |
        Q(email__icontains=q) | Q(phone__icontains=q) | Q(trn__icontains=q)).distinct()[:8]
    return [(c.company_name, f"{c.code} · {c.get_status_display()}" + (" · archived" if c.is_archived else ""),
             c.get_absolute_url()) for c in qs]
