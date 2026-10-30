from django.urls import path

from . import views

app_name = "quotations"

urlpatterns = [
    path("", views.QuotationList.as_view(), name="list"),
    path("template/", views.template_settings, name="template"),
    path("new/", views.quotation_create, name="create"),
    path("upload/", views.quotation_upload, name="upload"),
    path("<int:pk>/upload-revision/", views.quotation_upload_revision, name="upload_revision"),
    path("<int:pk>/mark-final/", views.quotation_mark_final, name="mark_final"),
    path("<int:pk>/file/<int:version>/", views.quotation_file, name="file"),
    path("<int:pk>/", views.quotation_detail, name="detail"),
    path("<int:pk>/edit/", views.quotation_edit, name="edit"),
    path("<int:pk>/submit/", views.quotation_submit, name="submit"),
    path("<int:pk>/decide/", views.quotation_decide, name="decide"),
    path("<int:pk>/send/", views.quotation_send, name="send"),
    path("<int:pk>/accept/", views.quotation_accept, name="accept"),
    path("<int:pk>/decline/", views.quotation_decline, name="decline"),
    path("<int:pk>/revise/", views.quotation_revise, name="revise"),
    path("<int:pk>/pdf/", views.quotation_pdf, name="pdf"),
    path("<int:pk>/word/", views.quotation_docx, name="docx"),
    path("<int:pk>/preview/", views.quotation_preview, name="preview"),
    path("<int:pk>/delete/", views.quotation_delete, name="delete"),
]
