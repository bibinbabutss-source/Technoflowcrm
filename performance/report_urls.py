from django.urls import path

from . import team_views

app_name = "dailyreports"

urlpatterns = [
    path("", team_views.reports, name="list"),
    path("new/", team_views.report_edit, name="new"),
    path("<int:pk>/", team_views.report_detail, name="detail"),
    path("<int:pk>/edit/", team_views.report_edit, name="edit"),
    path("<int:pk>/delete/", team_views.report_delete, name="delete"),
]
