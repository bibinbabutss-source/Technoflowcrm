from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.DocumentList.as_view(), name="list"),
    path("upload/", views.document_upload, name="upload"),
    path("<int:pk>/", views.document_detail, name="detail"),
    path("<int:pk>/download/", views.document_download, name="download"),
    path("<int:pk>/archive/", views.document_archive, name="archive"),
    path("<int:pk>/delete/", views.document_delete, name="delete"),
]
