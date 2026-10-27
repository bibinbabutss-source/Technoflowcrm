from django.urls import path

from . import views

app_name = "invoicing"

urlpatterns = [
    path("", views.InvoiceList.as_view(), name="list"),
    path("from-milestone/<int:pk>/", views.create_from_milestone, name="create_from_milestone"),
    path("<int:pk>/", views.invoice_detail, name="detail"),
    path("<int:pk>/edit/", views.invoice_edit, name="edit"),
    path("<int:pk>/issue/", views.invoice_issue, name="issue"),
    path("<int:pk>/delete/", views.invoice_delete_draft, name="delete"),
    path("<int:pk>/cancel/", views.invoice_cancel, name="cancel"),
    path("<int:pk>/dispute/", views.invoice_dispute, name="dispute"),
    path("<int:pk>/pdf/", views.invoice_pdf, name="pdf"),
    path("payments/", views.PaymentList.as_view(), name="payments"),
    path("payments/new/", views.payment_create, name="payment_create"),
    path("payments/<int:pk>/", views.payment_detail, name="payment_detail"),
    path("collections/", views.collections, name="collections"),
    path("statement/<int:customer_pk>/", views.statement, name="statement"),
]
