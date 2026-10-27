"""
User-account business rules. Views call these functions; they never
change accounts directly, so the rules apply everywhere.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.audit import log_action

from .models import EmployeeProfile, check_role_capacity

User = get_user_model()


@transaction.atomic
def create_employee(*, username, email, first_name, last_name, employee_id, role,
                    temporary_password, department="", job_title="", phone="",
                    reporting_manager=None, team_members=()):
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError({"username": "This username is already in use."})
    if User.objects.filter(email__iexact=email).exists():
        raise ValidationError({"email": "This work email is already in use."})
    check_role_capacity(role)

    user = User(username=username, email=email.lower(), first_name=first_name, last_name=last_name, is_active=True)
    validate_password(temporary_password, user)
    user.set_password(temporary_password)
    user.is_staff = role.is_admin_role  # only the System Administrator reaches Django admin
    user.is_superuser = False
    user.save()
    profile = EmployeeProfile(
        user=user, employee_id=employee_id, role=role, department=department, job_title=job_title,
        phone=phone, reporting_manager=reporting_manager, must_change_password=True,
    )
    profile.full_clean(exclude=["user"])
    profile.save()
    if team_members:
        profile.team_members.set(team_members)
    return user


@transaction.atomic
def update_employee(profile, *, role, **fields):
    user = profile.user
    for name in ("first_name", "last_name", "email"):
        if name in fields:
            setattr(user, name, fields.pop(name))
    if User.objects.filter(email__iexact=user.email).exclude(pk=user.pk).exists():
        raise ValidationError({"email": "This work email is already in use."})
    user.email = user.email.lower()
    user.is_staff = role.is_admin_role
    user.save()
    team_members = fields.pop("team_members", None)
    for name, value in fields.items():
        setattr(profile, name, value)
    old_role = profile.role
    profile.role = role
    profile.full_clean(exclude=["user", "team_members"])
    profile.save()  # model save() enforces role limits and last-admin rule
    if team_members is not None:
        profile.team_members.set(team_members)
    if old_role != role:
        log_action("permission", user, changes={"role": [old_role.name, role.name]},
                   message=f"Role changed from {old_role.name} to {role.name}")
    return profile


@transaction.atomic
def deactivate_employee(profile, *, by_user):
    user = profile.user
    if user == by_user:
        raise ValidationError("You cannot deactivate your own account.")
    if profile.role.is_admin_role and profile.role.active_count(exclude_user_id=user.id) == 0:
        raise ValidationError("The last active System Administrator cannot be deactivated.")
    if not user.is_active:
        return
    user.is_active = False
    user.save(update_fields=["is_active"])
    profile.deactivated_at = timezone.now()
    profile.save(update_fields=["deactivated_at", "updated_at", "updated_by"])
    _end_sessions(user)
    log_action("deactivate", user, message="Account deactivated; historical records kept")


@transaction.atomic
def activate_employee(profile):
    user = profile.user
    if user.is_active:
        return
    check_role_capacity(profile.role, user_id=user.id)
    user.is_active = True
    user.save(update_fields=["is_active"])
    profile.deactivated_at = None
    profile.save(update_fields=["deactivated_at", "updated_at", "updated_by"])
    log_action("activate", user, message="Account activated")


def failed_sign_in_attempts(user):
    """Recent failed sign-ins recorded by the lockout protection for this username."""
    from axes.models import AccessAttempt

    return AccessAttempt.objects.filter(username=user.username)


def is_sign_in_locked(user):
    from django.conf import settings

    return failed_sign_in_attempts(user).filter(failures_since_start__gte=settings.AXES_FAILURE_LIMIT).exists()


def unlock_sign_in(user):
    from axes.utils import reset

    removed = reset(username=user.username)
    log_action("other", user, message=f"Sign-in lock cleared by administrator ({removed} record(s))")
    return removed


@transaction.atomic
def admin_reset_password(profile, temporary_password, by_user=None):
    user = profile.user
    if by_user is not None and by_user == user:
        raise ValidationError("Use 'Change password' in your own account menu to change your own password.")
    validate_password(temporary_password, user)
    user.set_password(temporary_password)
    user.save(update_fields=["password"])
    profile.must_change_password = True
    profile.save(update_fields=["must_change_password", "updated_at", "updated_by"])
    _end_sessions(user)
    log_action("password_reset", user, message="Password reset by administrator; change required at next login")


def record_password_change(user):
    profile = getattr(user, "profile", None)
    if profile:
        profile.must_change_password = False
        profile.password_changed_at = timezone.now()
        profile.save(update_fields=["must_change_password", "password_changed_at", "updated_at", "updated_by"])
    log_action("password_change", user, user=user, message="Password changed by user")


def _end_sessions(user):
    """Log the user out everywhere (used on deactivation and password reset)."""
    from django.contrib.sessions.models import Session

    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id") == str(user.pk):
            session.delete()
