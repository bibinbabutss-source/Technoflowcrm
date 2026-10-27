from django.apps import AppConfig
from django.db.models.signals import post_migrate


class SalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sales"
    verbose_name = "Sales pipeline and projects"

    def ready(self):
        from django.db.models import Q
        from django.urls import reverse

        from accounts.permissions import scope_queryset
        from core.audit import track_model
        from core.crud import Column, badge
        from core.registry import register_customer_section, register_document_target, register_search

        from .models import OWNER_FIELDS, PROJECT_OWNER_FIELDS, Opportunity, OpportunityStage, Project

        track_model(Opportunity, exclude=["stage_changed_at"])
        track_model(OpportunityStage)
        track_model(Project)

        def customer_opps(customer, user):
            return scope_queryset(customer.opportunities.select_related("stage"), user, OWNER_FIELDS)

        register_customer_section("opportunities", "Opportunities", "pipeline.view", customer_opps, [
            Column("ID", "code", link=True), Column("Title", "title"),
            Column("Stage", render=lambda o: badge(o.stage.name, "good" if o.stage.is_won else
                                                   "bad" if o.stage.is_lost else "info")),
            Column("Value", "estimated_value", money=True), Column("Prob.", lambda o: f"{o.probability}%"),
            Column("Expected close", "expected_close_date", date=True)],
            order=30, add_url=lambda c: reverse("sales:opportunity_create") + f"?customer={c.pk}",
            add_capability="pipeline.edit")

        def customer_projects(customer, user):
            return scope_queryset(customer.projects.all(), user, PROJECT_OWNER_FIELDS)

        register_customer_section("projects", "Projects", "projects.view", customer_projects, [
            Column("Project", "code", link=True), Column("Name", "name"),
            Column("Status", lambda p: p.get_status_display()), Column("Progress", lambda p: f"{p.progress}%")],
            order=55)

        def search_opps(user, q):
            qs = scope_queryset(Opportunity.objects.select_related("customer", "stage"), user, OWNER_FIELDS).filter(
                Q(code__icontains=q) | Q(title__icontains=q) | Q(customer__company_name__icontains=q))[:8]
            return [(o.title, f"{o.code} · {o.customer.company_name} · {o.stage}", o.get_absolute_url()) for o in qs]

        def search_projects(user, q):
            qs = scope_queryset(Project.objects.select_related("customer"), user, PROJECT_OWNER_FIELDS).filter(
                Q(code__icontains=q) | Q(name__icontains=q) | Q(customer__company_name__icontains=q))[:8]
            return [(p.name, f"{p.code} · {p.customer.company_name} · {p.get_status_display()}",
                     p.get_absolute_url()) for p in qs]

        register_search("Opportunities", "pipeline.view", search_opps, order=30)
        register_search("Projects", "projects.view", search_projects, order=40)
        register_document_target(Opportunity, "Opportunity", "pipeline.view", OWNER_FIELDS)
        register_document_target(Project, "Project", "projects.view", PROJECT_OWNER_FIELDS)
        post_migrate.connect(_seed, sender=self)


def _seed(sender, **kwargs):
    from .services import seed_stages

    seed_stages()
