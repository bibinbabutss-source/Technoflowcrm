from django.urls import path

from . import settings_views, views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", views.settings_home, name="settings_home"),
    path("settings/numbering/", views.numbering, name="numbering"),
    path("settings/numbering/<int:pk>/", views.numbering_edit, name="numbering_edit"),
    path("settings/lists/", views.lookups, name="lookups"),
    path("settings/lists/<int:pk>/toggle/", views.lookup_toggle, name="lookup_toggle"),
    path("settings/workflow/", settings_views.workflow, name="settings_workflow"),
    path("settings/workflow/run-reminders/", settings_views.run_reminders, name="run_reminders"),
    path("settings/tax-rates/", settings_views.tax_rates, name="tax_rates"),
    path("settings/tax-rates/<int:pk>/", settings_views.tax_rates, name="tax_rate_edit"),
    path("settings/stages/<slug:kind>/", settings_views.stages, name="stages"),
    path("settings/stages/<slug:kind>/<int:pk>/", settings_views.stages, name="stage_edit"),
    path("audit-log/", views.audit_log, name="audit_log"),
]
