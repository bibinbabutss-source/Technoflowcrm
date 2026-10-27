from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    path("", views.PipelineList.as_view(), name="pipeline"),
    path("kanban/", views.pipeline_kanban, name="kanban"),
    path("forecast/", views.pipeline_forecast, name="forecast"),
    path("opportunities/new/", views.OpportunityCreate.as_view(), name="opportunity_create"),
    path("opportunities/<int:pk>/", views.opportunity_detail, name="opportunity_detail"),
    path("opportunities/<int:pk>/edit/", views.OpportunityUpdate.as_view(), name="opportunity_edit"),
    path("opportunities/<int:pk>/stage/", views.opportunity_stage, name="opportunity_stage"),
    path("opportunities/<int:pk>/move/", views.opportunity_move, name="opportunity_move"),
    path("opportunities/<int:pk>/archive/", views.opportunity_archive, name="opportunity_archive"),
    path("projects/", views.ProjectList.as_view(), name="projects"),
    path("projects/new/", views.ProjectCreate.as_view(), name="project_create"),
    path("projects/<int:pk>/", views.project_detail, name="project_detail"),
    path("projects/<int:pk>/edit/", views.ProjectUpdate.as_view(), name="project_edit"),
]
