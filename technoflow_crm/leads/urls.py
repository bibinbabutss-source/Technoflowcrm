from django.urls import path

from . import views

app_name = "leads"

urlpatterns = [
    path("", views.LeadList.as_view(), name="list"),
    path("kanban/", views.lead_kanban, name="kanban"),
    path("new/", views.LeadCreate.as_view(), name="create"),
    path("<int:pk>/", views.lead_detail, name="detail"),
    path("<int:pk>/edit/", views.LeadUpdate.as_view(), name="edit"),
    path("<int:pk>/stage/", views.lead_stage, name="stage"),
    path("<int:pk>/move/", views.lead_move, name="move"),
    path("<int:pk>/convert/", views.lead_convert, name="convert"),
    path("<int:pk>/archive/", views.lead_archive, name="archive"),
]
