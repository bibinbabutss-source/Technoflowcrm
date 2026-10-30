from django.urls import path

from . import views

app_name = "owner"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("approvals/", views.approvals, name="approvals"),
    path("calendar/", views.calendar_view, name="calendar"),
    path("modules/", views.modules, name="modules"),
]
