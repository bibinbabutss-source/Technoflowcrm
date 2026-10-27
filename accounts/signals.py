from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import post_migrate, pre_save
from django.dispatch import receiver

from core.audit import log_action, track_model
from core.middleware import get_client_ip

from .models import EmployeeProfile, LoginHistory, Role, check_role_capacity

User = get_user_model()

track_model(User, exclude=["password", "last_login", "date_joined"])
track_model(EmployeeProfile, exclude=["password_changed_at"])
track_model(Role)


def _agent(request):
    return request.META.get("HTTP_USER_AGENT", "")[:300] if request else ""


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    LoginHistory.objects.create(user=user, username=user.username, event="login",
                                ip_address=get_client_ip(request), user_agent=_agent(request))
    log_action("login", user, user=user, request=request)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        LoginHistory.objects.create(user=user, username=user.username, event="logout",
                                    ip_address=get_client_ip(request), user_agent=_agent(request))


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials or {}).get("username", "")[:150]
    user = User.objects.filter(username__iexact=username).first()
    LoginHistory.objects.create(user=user, username=username, event="failed",
                                ip_address=get_client_ip(request), user_agent=_agent(request))


@receiver(pre_save, sender=User)
def guard_activation(sender, instance, **kwargs):
    """Re-activating a user (from any screen, including Django admin) must respect role limits."""
    if not instance.pk or not instance.is_active:
        return
    was_active = User.objects.filter(pk=instance.pk).values_list("is_active", flat=True).first()
    if was_active is False:
        profile = EmployeeProfile.objects.filter(user_id=instance.pk).select_related("role").first()
        if profile:
            check_role_capacity(profile.role, user_id=instance.pk)


@receiver(post_migrate)
def sync_roles(sender, app_config=None, **kwargs):
    if app_config is None or app_config.label != "accounts":
        return
    from .setup import sync_roles_and_capabilities

    sync_roles_and_capabilities()
