from django.urls import path

from . import views

app_name = "performance"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("targets/", views.target_list, name="targets"),
    path("targets/set/", views.set_targets, name="set_targets"),
    path("kpis/", views.kpi_definitions, name="kpis"),
    path("kpis/<int:pk>/", views.kpi_edit, name="kpi_edit"),
]
