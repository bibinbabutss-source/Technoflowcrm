"""
Audit logging helpers.

    from core.audit import log_action, track_model

    log_action("approve", quotation, message="Approved revision 2")
    track_model(Customer, exclude=["updated_at"])   # automatic create/update/delete

Sensitive fields (passwords, tokens) are never written to the log.
"""
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_delete, post_save, pre_save

from .middleware import get_client_ip, get_current_request, get_current_user

ALWAYS_EXCLUDED = {"password", "last_login", "updated_at", "created_at", "updated_by", "created_by"}
_tracked = {}


def _serialise(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def log_action(action, obj=None, *, user=None, changes=None, message="", request=None):
    from .models import AuditLog

    request = request or get_current_request()
    if user is None:
        current = get_current_user()
        user = current if current is not None and current.is_authenticated else None
    entry = AuditLog(
        user=user,
        action=action,
        changes=changes or {},
        message=message[:500],
        ip_address=get_client_ip(request),
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""),
    )
    if obj is not None:
        entry.content_type = ContentType.objects.get_for_model(obj.__class__)
        entry.object_id = str(obj.pk)
        entry.object_repr = str(obj)[:255]
    entry.save()
    return entry


def _field_values(instance, fields):
    values = {}
    for field in fields:
        attname = field.attname
        values[field.name] = _serialise(getattr(instance, attname, None))
    return values


def track_model(model, exclude=()):
    """Record create, update (with old -> new values) and delete for a model."""
    excluded = ALWAYS_EXCLUDED | set(exclude)
    fields = [f for f in model._meta.concrete_fields if f.name not in excluded and not f.primary_key]
    _tracked[model] = fields

    def before(sender, instance, **kwargs):
        if instance.pk and not instance._state.adding:
            try:
                old = sender.objects.get(pk=instance.pk)
            except sender.DoesNotExist:
                old = None
            instance._audit_old = _field_values(old, fields) if old else None

    def after(sender, instance, created, raw=False, **kwargs):
        if raw:
            return
        new = _field_values(instance, fields)
        if created:
            log_action("create", instance, changes={k: [None, v] for k, v in new.items() if v not in (None, "")})
            return
        old = getattr(instance, "_audit_old", None) or {}
        diff = {k: [old.get(k), v] for k, v in new.items() if old.get(k) != v}
        if diff:
            log_action("update", instance, changes=diff)

    def deleted(sender, instance, **kwargs):
        log_action("delete", instance)

    uid = f"audit_{model._meta.label_lower}"
    pre_save.connect(before, sender=model, weak=False, dispatch_uid=uid + "_pre")
    post_save.connect(after, sender=model, weak=False, dispatch_uid=uid + "_post")
    post_delete.connect(deleted, sender=model, weak=False, dispatch_uid=uid + "_del")
