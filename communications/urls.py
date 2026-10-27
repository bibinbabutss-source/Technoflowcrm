from django.urls import path

from . import views

app_name = "communications"

urlpatterns = [
    path("", views.CommunicationList.as_view(), name="list"),
    path("new/", views.CommunicationCreate.as_view(), name="create"),
    path("<int:pk>/", views.communication_detail, name="detail"),
    path("<int:pk>/edit/", views.CommunicationUpdate.as_view(), name="edit"),
    path("<int:pk>/delete/", views.CommunicationDelete.as_view(), name="delete"),
]
