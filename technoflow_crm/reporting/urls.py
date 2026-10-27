from django.urls import path

from . import import_views, views

app_name = "reporting"

urlpatterns = [
    path("reports/", views.report_index, name="index"),
    path("reports/<slug:key>/", views.report_view, name="report"),
    path("dashboard/chart/<slug:key>/", views.chart_json, name="chart"),
    path("search/", views.global_search, name="search"),
    path("import/", import_views.import_start, name="import_start"),
    path("import/<int:pk>/", import_views.import_detail, name="import_detail"),
    path("import/<int:pk>/run/", import_views.import_run, name="import_run"),
    path("import/<int:pk>/problems.csv", import_views.import_errors, name="import_errors"),
    path("import/<int:pk>/cancel/", import_views.import_cancel, name="import_cancel"),
]
