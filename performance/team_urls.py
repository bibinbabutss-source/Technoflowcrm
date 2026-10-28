from django.urls import path

from . import team_views

app_name = "team"

urlpatterns = [
    path("", team_views.team, name="list"),
    path("me/", team_views.me, name="me"),
    path("<int:pk>/", team_views.employee, name="employee"),
]
