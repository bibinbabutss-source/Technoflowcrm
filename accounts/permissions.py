"""
Server-side permission checks.

Every protected view uses one of these. Hiding a menu item or button is
only cosmetic; the check here is what actually blocks the request.

    @capability_required("users.manage")
    def user_list(request): ...

    class UserListView(CapabilityRequiredMixin, ListView):
        capability = "users.manage"

    class SomeApi(APIView):
        permission_classes = [HasCapability]
        capability = "data.export"
"""
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


def get_profile(user):
    if not user or not user.is_authenticated or not user.is_active:
        return None
    try:
        return user.profile
    except Exception:  # no EmployeeProfile -> no CRM access
        return None


def has_capability(user, code):
    profile = get_profile(user)
    return bool(profile and code in profile.capability_codes())


def require(user, code):
    if not has_capability(user, code):
        raise PermissionDenied("You do not have permission to perform this action.")


def capability_required(*codes):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            for code in codes:
                require(request.user, code)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def any_capability_required(*codes):
    """The user needs at least ONE of the capabilities (checked on the server for every request)."""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not any(has_capability(request.user, c) for c in codes):
                raise PermissionDenied("You do not have permission to perform this action.")
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


class CapabilityRequiredMixin(LoginRequiredMixin):
    capability = None  # str or tuple of str; all are required

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        codes = (self.capability,) if isinstance(self.capability, str) else (self.capability or ())
        for code in codes:
            require(request.user, code)
        return super().dispatch(request, *args, **kwargs)


class HasCapability(BasePermission):
    """DRF permission: view sets `capability = "..."`."""

    def has_permission(self, request, view):
        code = getattr(view, "capability", None)
        return bool(code) and has_capability(request.user, code)


# --------------------------------------------------------- record scope
def visible_user_ids(user):
    """
    IDs of users whose records `user` may see, according to the role's
    data scope. None means no restriction (all records).
    """
    profile = get_profile(user)
    if profile is None:
        return set()
    if profile.role.data_scope == "all":
        return None
    ids = {user.id}
    if profile.role.data_scope == "team":
        ids |= set(profile.team_members.values_list("user_id", flat=True))
        ids |= set(profile.direct_reports.values_list("user_id", flat=True))
    return ids


def scope_queryset(queryset, user, owner_fields=("created_by",)):
    """
    Restrict a queryset to records the user may see. Each module passes
    the fields that link a record to people, e.g.
        scope_queryset(Lead.objects.all(), user,
                       ("assigned_engineer", "assigned_coordinator", "created_by"))
    """
    from django.db.models import Q

    ids = visible_user_ids(user)
    if ids is None:
        return queryset
    if not ids:
        return queryset.none()
    condition = Q()
    for field in owner_fields:
        condition |= Q(**{f"{field}__in": ids})
    return queryset.filter(condition).distinct()
