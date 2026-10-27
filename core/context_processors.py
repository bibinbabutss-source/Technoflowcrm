from accounts.permissions import get_profile

from .models import CompanyProfile
from .navigation import build_nav


def crm_context(request):
    user = getattr(request, "user", None)
    ctx = {"company": CompanyProfile.get()}
    if user is not None and user.is_authenticated:
        profile = get_profile(user)
        ctx["crm_profile"] = profile
        ctx["crm_nav"] = build_nav(user)
        ctx["crm_caps"] = profile.capability_codes() if profile else set()
        if profile is not None:
            from notifications.models import Notification

            qs = Notification.objects.filter(user=user)
            ctx["crm_unread"] = qs.filter(is_read=False).count()
            ctx["crm_recent_notifications"] = qs[:6]
    return ctx
