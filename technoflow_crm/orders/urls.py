from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("", views.OrderList.as_view(), name="list"),
    path("from-quotation/<int:pk>/", views.create_from_quotation, name="create_from_quotation"),
    path("<int:pk>/", views.order_detail, name="detail"),
    path("<int:pk>/edit/", views.OrderUpdate.as_view(), name="edit"),
    path("<int:pk>/confirm/", views.order_confirm, name="confirm"),
    path("<int:pk>/cancel/", views.order_cancel, name="cancel"),
    path("<int:pk>/progress/", views.order_progress, name="progress"),
    path("<int:pk>/milestones/", views.order_milestones, name="milestones"),
    path("<int:pk>/project/", views.order_create_project, name="create_project"),
]
