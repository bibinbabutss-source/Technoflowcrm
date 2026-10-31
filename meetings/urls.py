from django.urls import path

from . import views

app_name = "meetings"

urlpatterns = [
    path("new/<slug:kind>/<int:pk>/", views.meeting_add, name="add"),
    path("<int:pk>/edit/", views.meeting_edit, name="edit"),
    path("<int:pk>/delete/", views.meeting_delete, name="delete"),
]
