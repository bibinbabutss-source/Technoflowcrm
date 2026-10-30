"""
Who may approve (quotation approvals are the CRM's approval workflow).

    Owner                     always (with the "quotations.approve" permission, which the Owner role has)
    Sales Director            only when Settings > Modules & approvals > "Sales Director may approve as backup"
                              is ticked
    No active Owner account   the previous rule applies (anyone holding "quotations.approve"), so approvals never
                              get stuck before the Owner login has been created
Nobody may approve a quotation they prepared or are the salesperson for (checked in quotations.services).
"""
from django.contrib.auth import get_user_model

from accounts import capabilities as caps
from accounts.permissions import get_profile, has_capability


def owner_exists():
    return get_user_model().objects.filter(is_active=True, profile__role__code=caps.OWNER).exists()


def may_approve(user):
    """(allowed, reason-if-not)."""
    from core.models import CompanyProfile

    if not user or not user.is_authenticated or not has_capability(user, "quotations.approve"):
        return False, "You are not allowed to approve or reject requests."
    profile = get_profile(user)
    role = profile.role.code if profile and profile.role_id else None
    if role == caps.OWNER:
        return True, ""
    if not owner_exists():
        return True, ""
    if role == caps.DIRECTOR and CompanyProfile.get().director_backup_approval:
        return True, ""
    return False, ("Approvals are done by the Owner. The Sales Director can approve only when the Owner turns on "
                   "'Sales Director may approve as backup' in Settings.")


def approver_users():
    User = get_user_model()
    candidates = User.objects.filter(is_active=True, profile__role__capabilities__code="quotations.approve").distinct()
    return [u for u in candidates if may_approve(u)[0]]
