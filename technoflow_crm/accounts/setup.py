from django.db import transaction

from . import capabilities as caps
from .models import Capability, Role


@transaction.atomic
def sync_roles_and_capabilities():
    """
    Create any missing roles and capabilities. Safe to run repeatedly.
    Existing roles keep the limits and permissions set by the Administrator;
    default assignments are applied only to newly created capabilities.
    """
    roles = {}
    for order, (code, name, limit, scope, description) in enumerate(caps.ROLES):
        role, _ = Role.objects.get_or_create(
            code=code,
            defaults={"name": name, "max_accounts": limit, "data_scope": scope,
                      "description": description, "sort_order": order},
        )
        roles[code] = role

    for code, module, label, role_codes in caps.CAPABILITIES:
        cap, created = Capability.objects.get_or_create(code=code, defaults={"module": module, "label": label})
        if not created and (cap.module, cap.label) != (module, label):
            cap.module, cap.label = module, label
            cap.save(update_fields=["module", "label"])
        if created:
            for rc in role_codes:
                roles[rc].capabilities.add(cap)

    # The System Administrator must always be able to administer the system.
    admin = roles[caps.ADMIN]
    admin.capabilities.add(*Capability.objects.filter(
        code__in=["users.manage", "roles.manage", "settings.manage", "audit.view", "dashboard.view"]))
