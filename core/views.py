import csv

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import LoginHistory, Role
from accounts.permissions import capability_required, get_profile, has_capability

from .audit import log_action
from .forms import CompanyProfileForm, LookupValueForm, NumberSequenceForm
from .models import AuditLog, CompanyProfile, LookupValue, NumberSequence
from .params import get_choice, get_date, get_int

User = get_user_model()


@login_required
def dashboard(request):
    profile = get_profile(request.user)
    if profile is None:
        return render(request, "core/no_profile.html", status=403)
    from notifications.reminders import run_if_due
    from reporting.views import business_context

    run_if_due()  # daily reminders: runs at most once a day, on the first dashboard visit
    ctx = {"profile": profile}
    if has_capability(request.user, "dashboard.view"):
        ctx.update(business_context(request))
    if has_capability(request.user, "users.manage"):
        ctx["roles"] = Role.objects.annotate(
            active=Count("profiles", filter=Q(profiles__user__is_active=True)),
            inactive=Count("profiles", filter=Q(profiles__user__is_active=False)),
        )
        ctx["total_active"] = sum(r.active for r in ctx["roles"])
        ctx["total_limit"] = sum(r.max_accounts for r in ctx["roles"])
        since = timezone.now() - timezone.timedelta(days=7)
        ctx["failed_logins_7d"] = LoginHistory.objects.filter(event="failed", timestamp__gte=since).count()
        ctx["pending_password_change"] = User.objects.filter(
            is_active=True, profile__must_change_password=True
        ).count()
    if has_capability(request.user, "audit.view"):
        ctx["recent_audit"] = AuditLog.objects.select_related("user")[:8]
    ctx["my_logins"] = LoginHistory.objects.filter(user=request.user)[:5]
    return render(request, "core/dashboard.html", ctx)


# ------------------------------------------------------------- settings
@capability_required("settings.manage")
def settings_home(request):
    company = CompanyProfile.get()
    form = CompanyProfileForm(request.POST or None, instance=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Company settings saved.")
        return redirect("core:settings_home")
    return render(request, "core/settings_company.html", {"form": form, "tab": "company"})


@capability_required("settings.manage")
def numbering(request):
    return render(request, "core/settings_numbering.html",
                  {"sequences": NumberSequence.objects.all(), "tab": "numbering"})


@capability_required("settings.manage")
def numbering_edit(request, pk):
    seq = get_object_or_404(NumberSequence, pk=pk)
    form = NumberSequenceForm(request.POST or None, instance=seq)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{seq.name} numbering saved. Next number: {seq.preview()}")
        return redirect("core:numbering")
    return render(request, "core/settings_numbering_edit.html", {"form": form, "seq": seq, "tab": "numbering"})


@capability_required("settings.manage")
def lookups(request):
    category = request.GET.get("category") or LookupValue.Category.CUSTOMER_CATEGORY
    if category not in LookupValue.Category.values:
        category = LookupValue.Category.CUSTOMER_CATEGORY
    form = LookupValueForm(request.POST or None, initial={"category": category})
    if request.method == "POST" and form.is_valid():
        if LookupValue.objects.filter(category=form.cleaned_data["category"],
                                      value__iexact=form.cleaned_data["value"]).exists():
            form.add_error("value", "This value already exists in the list.")
        else:
            obj = form.save()
            messages.success(request, f"Added '{obj.value}'.")
            return redirect(f"{request.path}?category={obj.category}")
    values = LookupValue.objects.filter(category=category)
    return render(request, "core/settings_lookups.html", {
        "form": form, "values": values, "category": category,
        "categories": LookupValue.Category.choices, "tab": "lookups",
    })


@require_POST
@capability_required("settings.manage")
def lookup_toggle(request, pk):
    obj = get_object_or_404(LookupValue, pk=pk)
    obj.is_active = not obj.is_active
    obj.save()
    messages.success(request, f"'{obj.value}' {'enabled' if obj.is_active else 'hidden from new records'}.")
    return redirect(f"{reverse('core:lookups')}?category={obj.category}")


# ------------------------------------------------------------ audit log
def _audit_queryset(request):
    qs = AuditLog.objects.select_related("user", "content_type")
    f = request.GET
    user_id = get_int(f, "user")
    if user_id:
        qs = qs.filter(user_id=user_id)
    action = get_choice(f, "action", AuditLog.Action.values)
    if action:
        qs = qs.filter(action=action)
    if f.get("q"):
        qs = qs.filter(Q(object_repr__icontains=f["q"]) | Q(message__icontains=f["q"]))
    date_from, date_to = get_date(f, "date_from"), get_date(f, "date_to")
    if date_from:
        qs = qs.filter(timestamp__date__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__date__lte=date_to)
    return qs


@capability_required("audit.view")
def audit_log(request):
    qs = _audit_queryset(request)
    if request.GET.get("export") == "csv":
        log_action("export", message=f"Audit log CSV export ({qs.count()} rows)")
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="audit_log.csv"'
        writer = csv.writer(response)
        writer.writerow(["Time", "User", "Action", "Record type", "Record", "Changes", "Message", "IP address"])
        for e in qs.iterator():
            writer.writerow([
                timezone.localtime(e.timestamp).strftime("%d-%b-%Y %H:%M:%S"),
                e.user.username if e.user else "",
                e.get_action_display(),
                e.content_type.name if e.content_type else "",
                _safe_csv(e.object_repr),
                _safe_csv(str(e.changes) if e.changes else ""),
                _safe_csv(e.message),
                e.ip_address or "",
            ])
        return response
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "core/audit_log.html", {
        "page": page,
        "users": User.objects.order_by("first_name", "username"),
        "actions": AuditLog.Action.choices,
    })


def _safe_csv(value):
    """Stop spreadsheet formula injection when the CSV is opened in Excel."""
    value = value or ""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value
