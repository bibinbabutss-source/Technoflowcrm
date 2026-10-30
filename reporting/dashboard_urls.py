from django.urls import path

from . import dashboard_views
from .module_dashboards import MODULES

app_name = "dashboards"

urlpatterns = [path(f"{key}/", dashboard_views.module_dashboard, {"module": key}, name=key) for key in MODULES] + [
    path("<slug:module>/", dashboard_views.module_dashboard, name="module"),
]
