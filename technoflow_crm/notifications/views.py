from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required
from core.crud import safe_next

from .models import CATEGORIES, Notification, NotificationPreference


@capability_required("notifications.view")
def notification_list(request):
    qs = Notification.objects.filter(user=request.user)
    if request.GET.get("show") == "unread":
        qs = qs.filter(is_read=False)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {"page": page, "show": request.GET.get("show", "all")})


@require_POST
@capability_required("notifications.view")
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    url = n.url if n.url.startswith("/") and not n.url.startswith("//") else None
    return redirect(url or "notifications:list")


@require_POST
@capability_required("notifications.view")
def mark_all_read(request):
    count = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    messages.success(request, f"{count} notification{'s' if count != 1 else ''} marked as read.")
    return redirect(safe_next(request, "/notifications/"))


@capability_required("notifications.view")
def preferences(request):
    current = {p.category: p for p in NotificationPreference.objects.filter(user=request.user)}
    if request.method == "POST":
        for key, _ in CATEGORIES:
            pref = current.get(key) or NotificationPreference(user=request.user, category=key)
            pref.in_app = request.POST.get(f"{key}_app") == "on"
            pref.email = request.POST.get(f"{key}_email") == "on"
            pref.save()
        messages.success(request, "Notification preferences saved.")
        return redirect("notifications:preferences")
    rows = [{"key": k, "label": label, "in_app": current[k].in_app if k in current else True,
             "email": current[k].email if k in current else False} for k, label in CATEGORIES]
    from core.models import CompanyProfile
    from django.conf import settings

    return render(request, "notifications/preferences.html", {
        "rows": rows, "email_enabled": CompanyProfile.get().email_notifications_enabled,
        "smtp_configured": bool(settings.EMAIL_HOST)})
