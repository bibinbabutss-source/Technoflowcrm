from django.urls import path

from . import views

app_name = "quotations"

urlpatterns = [
    path("", views.QuotationList.as_view(), name="list"),
    path("new/", views.quotation_create, name="create"),
    path("<int:pk>/", views.quotation_detail, name="detail"),
    path("<int:pk>/edit/", views.quotation_edit, name="edit"),
    path("<int:pk>/submit/", views.quotation_submit, name="submit"),
    path("<int:pk>/decide/", views.quotation_decide, name="decide"),
    path("<int:pk>/send/", views.quotation_send, name="send"),
    path("<int:pk>/accept/", views.quotation_accept, name="accept"),
    path("<int:pk>/decline/", views.quotation_decline, name="decline"),
    path("<int:pk>/revise/", views.quotation_revise, name="revise"),
    path("<int:pk>/pdf/", views.quotation_pdf, name="pdf"),
    path("<int:pk>/delete/", views.quotation_delete, name="delete"),
]
