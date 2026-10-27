from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login as auth_login
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from core.params import get_choice, get_int

from .forms import (AdminResetPasswordForm, CrmPasswordChangeForm, CrmSetPasswordForm, EmployeeForm,
                    LoginForm, NewEmployeeForm, RoleForm)
from .models import Capability, EmployeeProfile, LoginHistory, Role
from .permissions import capability_required, get_profile
from core.audit import log_action
from core.middleware import get_client_ip

from . import mfa, services

User = get_user_model()


# ------------------------------------------------------ sign in / out
class CrmLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        profile = getattr(user, "profile", None)
        if profile is not None and profile.mfa_enabled and profile.mfa_secret:
            # Password is correct; the session is only created after the authenticator code is checked.
            mfa.start_pending(self.request, user, self.get_success_url())
            return redirect("accounts:mfa_verify")
        return super().form_valid(form)


def mfa_verify(request):
    user_id = request.session.get("mfa_user")
    started = request.session.get("mfa_started") or 0
    if not user_id or timezone.now().timestamp() - started > mfa.PENDING_SECONDS:
        mfa.clear_pending(request)
        messages.error(request, "Your sign-in timed out. Please sign in again.")
        return redirect("accounts:login")
    user = User.objects.filter(pk=user_id, is_active=True).select_related("profile").first()
    if user is None:
        mfa.clear_pending(request)
        return redirect("accounts:login")
    error = ""
    if request.method == "POST":
        attempts = request.session.get("mfa_attempts", 0) + 1
        request.session["mfa_attempts"] = attempts
        if mfa.confirm_for_profile(user.profile, request.POST.get("code")):
            backend = request.session.get("mfa_backend")
            next_url = request.session.get("mfa_next") or reverse("core:dashboard")
            mfa.clear_pending(request)
            auth_login(request, user, backend=backend)
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
                next_url = reverse("core:dashboard")
            return redirect(next_url)
        LoginHistory.objects.create(user=user, username=user.username, event="failed",
                                    ip_address=get_client_ip(request),
                                    user_agent=request.META.get("HTTP_USER_AGENT", "")[:255])
        if attempts >= mfa.MAX_ATTEMPTS:
            mfa.clear_pending(request)
            messages.error(request, "Too many incorrect codes. Please sign in again.")
            return redirect("accounts:login")
        error = "That code is not correct (or was already used). Enter the current 6-digit code."
    return render(request, "accounts/mfa_verify.html", {"error": error})


@login_required
def mfa_setup(request):
    profile = get_profile(request.user)
    if profile is None:
        return render(request, "core/no_profile.html", status=403)
    if profile.mfa_enabled:
        if request.method == "POST" and request.POST.get("action") == "disable":
            if not request.user.check_password(request.POST.get("password", "")):
                messages.error(request, "Your password is not correct.")
            elif not mfa.confirm_for_profile(profile, request.POST.get("code")):
                messages.error(request, "The authenticator code is not correct.")
            else:
                profile.mfa_enabled = False
                profile.mfa_secret = ""
                profile.mfa_last_counter = None
                profile.save(update_fields=["mfa_enabled", "mfa_secret", "mfa_last_counter"])
                log_action("update", profile, message="Two-step sign-in turned off by the user")
                messages.success(request, "Two-step sign-in is now off.")
                return redirect("accounts:mfa_setup")
        return render(request, "accounts/mfa_setup.html", {"profile": profile})
    secret = request.session.get("mfa_setup_secret")
    if not secret or request.GET.get("new"):
        secret = mfa.new_secret()
        request.session["mfa_setup_secret"] = secret
    if request.method == "POST":
        counter = mfa.verify(secret, request.POST.get("code"))
        if counter is None:
            messages.error(request, "That code is not correct. Check the time on your phone and try again.")
        else:
            profile.mfa_secret = secret
            profile.mfa_enabled = True
            profile.mfa_last_counter = counter
            profile.save(update_fields=["mfa_enabled", "mfa_secret", "mfa_last_counter"])
            request.session.pop("mfa_setup_secret", None)
            log_action("update", profile, message="Two-step sign-in turned on by the user")
            messages.success(request, "Two-step sign-in is on. You will be asked for a code each time you sign in.")
            return redirect("accounts:mfa_setup")
    uri = mfa.provisioning_uri(secret, request.user)
    return render(request, "accounts/mfa_setup.html", {"profile": profile, "qr": mfa.qr_svg(uri),
                                                         "secret": secret})


@require_POST
@capability_required("users.manage")
def user_mfa_reset(request, pk):
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user"), pk=pk)
    profile.mfa_enabled = False
    profile.mfa_secret = ""
    profile.mfa_last_counter = None
    profile.save(update_fields=["mfa_enabled", "mfa_secret", "mfa_last_counter"])
    log_action("update", profile, message=f"Two-step sign-in reset by {request.user.username}")
    messages.success(request, f"Two-step sign-in removed for {profile.full_name}. They can set it up again.")
    return redirect("accounts:user_detail", pk=pk)


class CrmPasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = CrmPasswordChangeForm
    success_url = reverse_lazy("core:dashboard")

    def form_valid(self, form):
        response = super().form_valid(form)
        services.record_password_change(self.request.user)
        messages.success(self.request, "Your password has been changed.")
        return response


class CrmPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = CrmSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        services.record_password_change(form.user)
        return response


@login_required
def my_profile(request):
    profile = get_profile(request.user)
    if profile is None:
        return render(request, "core/no_profile.html", status=403)
    return render(request, "accounts/my_profile.html", {
        "profile": profile,
        "logins": LoginHistory.objects.filter(user=request.user)[:10],
    })


# ------------------------------------------------------ user management
@capability_required("users.manage")
def user_list(request):
    qs = EmployeeProfile.objects.select_related("user", "role", "reporting_manager__user")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) |
                       Q(user__email__icontains=q) | Q(employee_id__icontains=q) | Q(user__username__icontains=q))
    role_id = get_int(request.GET, "role")
    if role_id:
        qs = qs.filter(role_id=role_id)
    status = request.GET.get("status", "active")
    if status == "active":
        qs = qs.filter(user__is_active=True)
    elif status == "inactive":
        qs = qs.filter(user__is_active=False)
    sort = request.GET.get("sort", "name")
    order = {"name": ["user__first_name", "user__last_name"], "role": ["role__sort_order", "user__first_name"],
             "id": ["employee_id"], "login": ["-user__last_login"]}.get(sort, ["user__first_name"])
    page = Paginator(qs.order_by(*order), 25).get_page(request.GET.get("page"))
    roles = Role.objects.annotate(active=Count("profiles", filter=Q(profiles__user__is_active=True)))
    return render(request, "accounts/user_list.html",
                  {"page": page, "roles": roles, "q": q, "status": status, "sort": sort})


@capability_required("users.manage")
def user_create(request):
    form = NewEmployeeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            user = services.create_employee(
                username=d["username"], email=d["email"], first_name=d["first_name"], last_name=d["last_name"],
                employee_id=d["employee_id"], role=d["role"], temporary_password=d["temporary_password"],
                department=d["department"], job_title=d["job_title"], phone=d["phone"],
                reporting_manager=d["reporting_manager"], team_members=d["team_members"],
            )
        except ValidationError as exc:
            _add_errors(form, exc)
        else:
            messages.success(request, f"Account created for {user.get_full_name()}. "
                                      "Give them the temporary password securely; they must change it at first sign-in.")
            return redirect("accounts:user_detail", pk=user.profile.pk)
    return render(request, "accounts/user_form.html", {"form": form, "is_new": True})


@capability_required("users.manage")
def user_detail(request, pk):
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user", "role"), pk=pk)
    logins = Paginator(LoginHistory.objects.filter(user=profile.user), 15).get_page(request.GET.get("page"))
    return render(request, "accounts/user_detail.html", {
        "profile": profile, "logins": logins, "reset_form": AdminResetPasswordForm(),
        "is_locked": services.is_sign_in_locked(profile.user),
        "failed_attempts": services.failed_sign_in_attempts(profile.user).count(),
    })


@require_POST
@capability_required("users.manage")
def user_unlock(request, pk):
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user"), pk=pk)
    services.unlock_sign_in(profile.user)
    messages.success(request, f"Sign-in lock cleared for {profile.full_name}. They can sign in again now.")
    return redirect("accounts:user_detail", pk=pk)


@capability_required("users.manage")
def user_edit(request, pk):
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user", "role"), pk=pk)
    form = EmployeeForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        d = dict(form.cleaned_data)
        role = d.pop("role")
        try:
            services.update_employee(profile, role=role, **d)
        except ValidationError as exc:
            _add_errors(form, exc)
        else:
            messages.success(request, "Employee details saved.")
            return redirect("accounts:user_detail", pk=profile.pk)
    return render(request, "accounts/user_form.html", {"form": form, "profile": profile, "is_new": False})


@require_POST
@capability_required("users.manage")
def user_toggle_active(request, pk):
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user", "role"), pk=pk)
    try:
        if profile.user.is_active:
            services.deactivate_employee(profile, by_user=request.user)
            messages.success(request, f"{profile.full_name} deactivated. Their records and history are kept.")
        else:
            services.activate_employee(profile)
            messages.success(request, f"{profile.full_name} activated.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("accounts:user_detail", pk=pk)


@require_POST
@capability_required("users.manage")
def user_reset_password(request, pk):
    profile = get_object_or_404(EmployeeProfile.objects.select_related("user"), pk=pk)
    form = AdminResetPasswordForm(request.POST)
    if form.is_valid():
        try:
            services.admin_reset_password(profile, form.cleaned_data["temporary_password"], by_user=request.user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, f"Temporary password set for {profile.full_name}. "
                                      "They have been signed out and must change it at next sign-in.")
    else:
        messages.error(request, "Enter a temporary password.")
    return redirect("accounts:user_detail", pk=pk)


@capability_required("users.manage")
def login_history(request):
    qs = LoginHistory.objects.select_related("user")
    event = get_choice(request.GET, "event", ["login", "logout", "failed"])
    if event:
        qs = qs.filter(event=event)
    if request.GET.get("q"):
        qs = qs.filter(username__icontains=request.GET["q"])
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "accounts/login_history.html", {"page": page})


# ------------------------------------------------------ roles and limits
@capability_required("roles.manage")
def role_list(request):
    roles = Role.objects.annotate(active=Count("profiles", filter=Q(profiles__user__is_active=True)))
    caps = Capability.objects.prefetch_related("roles")
    role_ids = {r.pk: {c.pk for c in r.capabilities.all()} for r in Role.objects.prefetch_related("capabilities")}
    matrix = [{"cap": c, "cells": [c.pk in role_ids[r.pk] for r in roles]} for c in caps]
    return render(request, "accounts/role_list.html", {"roles": roles, "matrix": matrix})


@capability_required("roles.manage")
def role_edit(request, pk):
    role = get_object_or_404(Role, pk=pk)
    form = RoleForm(request.POST or None, instance=role)
    if request.method == "POST" and form.is_valid():
        before = set(role.capabilities.values_list("code", flat=True))
        form.save()
        after = set(role.capabilities.values_list("code", flat=True))
        if before != after:
            from core.audit import log_action

            log_action("permission", role, changes={
                           "capabilities added": [None, ", ".join(sorted(after - before)) or None],
                           "capabilities removed": [", ".join(sorted(before - after)) or None, None]},
                       message=f"Permissions changed for {role.name}")
        messages.success(request, f"{role.name} saved.")
        return redirect("accounts:role_list")
    grouped = {}
    for cap in Capability.objects.all():
        grouped.setdefault(cap.module, []).append(cap)
    selected = {int(v) for v in (form["capabilities"].value() or [])}
    return render(request, "accounts/role_form.html",
                  {"form": form, "role": role, "grouped": grouped, "selected": selected})


def _add_errors(form, exc):
    if hasattr(exc, "message_dict"):
        for field, errs in exc.message_dict.items():
            form.add_error(field if field in form.fields else None, errs)
    else:
        form.add_error(None, exc.messages)
