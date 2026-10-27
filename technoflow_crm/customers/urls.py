from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("", views.CustomerList.as_view(), name="list"),
    path("new/", views.CustomerCreate.as_view(), name="create"),
    path("duplicate-check/", views.duplicate_check, name="duplicate_check"),
    path("<int:pk>/", views.customer_detail, name="detail"),
    path("<int:pk>/edit/", views.CustomerUpdate.as_view(), name="edit"),
    path("<int:pk>/archive/", views.customer_archive, name="archive"),
    path("<int:pk>/delete/", views.CustomerDelete.as_view(), name="delete"),
    path("<int:pk>/contacts/new/", views.contact_add, name="contact_add"),
    path("contacts/<int:pk>/", views.contact_edit, name="contact_edit"),
]
