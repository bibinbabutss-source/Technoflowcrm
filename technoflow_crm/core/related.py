"""
Drop-downs of related records (customer, lead, opportunity...) limited to what the user may see.
Used by tasks, visits, communications, documents and quotations.
"""
from accounts.permissions import has_capability, scope_queryset


def scoped_choices(user, model_path, capability, owner_fields, *, extra_filter=None, current_id=None):
    from django.apps import apps
    from django.db.models import Q

    model = apps.get_model(model_path)
    if user is None or not has_capability(user, capability):
        qs = model.objects.none()
    else:
        qs = scope_queryset(model.objects.all(), user, owner_fields)
        if extra_filter is not None:
            qs = qs.filter(extra_filter)
    if current_id:
        # The scoped queryset may be DISTINCT (team scopes); combine through a sub-query.
        qs = model.objects.filter(Q(pk__in=qs.values("pk")) | Q(pk=current_id))
    return qs


def apply_related_fields(form, specs):
    """
    specs: {field_name: (model_path, capability, owner_fields, extra_filter)}
    Each listed form field is limited to records the user may see (plus the current value).
    """
    for name, spec in specs.items():
        if name not in form.fields:
            continue
        model_path, capability, owners, extra = (list(spec) + [None])[:4]
        current = getattr(form.instance, f"{name}_id", None) if getattr(form, "instance", None) else None
        initial = form.initial.get(name) if hasattr(form, "initial") else None
        try:
            initial = int(initial) if initial else None
        except (TypeError, ValueError):
            initial = None
        form.fields[name].queryset = scoped_choices(form.user, model_path, capability, owners,
                                                    extra_filter=extra, current_id=current)
        if initial and not form.fields[name].queryset.filter(pk=initial).exists():
            form.initial.pop(name, None)
