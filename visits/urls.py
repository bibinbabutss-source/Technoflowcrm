from django.urls import path

from . import views

app_name = "visits"

urlpatterns = [
    path("", views.VisitList.as_view(), name="list"),
    path("calendar/", views.visit_calendar, name="calendar"),
    path("week/", views.visit_schedule, name="schedule"),
    path("new/", views.VisitCreate.as_view(), name="create"),
    path("<int:pk>/", views.visit_detail, name="detail"),
    path("<int:pk>/edit/", views.VisitUpdate.as_view(), name="edit"),
    path("<int:pk>/complete/", views.visit_complete, name="complete"),
    path("<int:pk>/reschedule/", views.visit_reschedule, name="reschedule"),
    path("<int:pk>/cancel/", views.visit_cancel, name="cancel"),
    path("<int:pk>/confirm/", views.visit_confirm, name="confirm"),
]
