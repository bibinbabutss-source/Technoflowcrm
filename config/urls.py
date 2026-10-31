from django.conf import settings
from django.contrib import admin
from django.http import HttpResponse
from django.urls import include, path


def health(request):
    """Used by the hosting platform to check the app is running."""
    return HttpResponse("ok", content_type="text/plain")


admin.site.site_header = "Technoflow CRM — technical administration"
admin.site.site_title = "Technoflow CRM admin"

urlpatterns = [
    path(settings.ADMIN_URL.strip("/") + "/", admin.site.urls),
    path("healthz/", health, name="health"),
    path("accounts/", include("accounts.urls")),
    path("customers/", include("customers.urls")),
    path("leads/", include("leads.urls")),
    path("visits/", include("visits.urls")),
    path("communications/", include("communications.urls")),
    path("tasks/", include("tasks.urls")),
    path("pipeline/", include("sales.urls")),
    path("quotations/", include("quotations.urls")),
    path("orders/", include("orders.urls")),
    path("invoices/", include("invoicing.urls")),
    path("targets/", include("performance.urls")),
    path("team/", include("performance.team_urls")),
    path("daily-reports/", include("performance.report_urls")),
    path("documents/", include("documents.urls")),
    path("owner/", include("owner.urls")),
    path("meetings/", include("meetings.urls")),
    path("dashboards/", include("reporting.dashboard_urls")),
    path("notifications/", include("notifications.urls")),
    path("", include("reporting.urls")),
    path("", include("core.urls")),
]

handler403 = "core.errors.permission_denied"
handler404 = "core.errors.not_found"
handler500 = "core.errors.server_error"
