from django.urls import path

from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.TaskList.as_view(), name="list"),
    path("calendar/", views.task_calendar, name="calendar"),
    path("new/", views.TaskCreate.as_view(), name="create"),
    path("<int:pk>/", views.task_detail, name="detail"),
    path("<int:pk>/edit/", views.TaskUpdate.as_view(), name="edit"),
    path("<int:pk>/status/", views.task_set_status, name="set_status"),
    path("<int:pk>/delete/", views.task_delete, name="delete"),
]
