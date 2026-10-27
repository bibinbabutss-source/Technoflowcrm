from django.apps import AppConfig
from django.db.models.signals import post_migrate


class LeadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "leads"
    verbose_name = "Leads"

    def ready(self):
        from django.db.models import Q

        from accounts.permissions import scope_queryset
        from core.audit import track_model
        from core.crud import Column, badge
        from core.registry import register_customer_section, register_document_target, register_search

        from .models import Lead, LeadStage, OWNER_FIELDS

        track_model(Lead, exclude=["stage_changed_at"])
        track_model(LeadStage)

        def customer_leads(customer, user):
            return scope_queryset(customer.leads.select_related("stage"), user, OWNER_FIELDS)

        register_customer_section("leads", "Leads", "leads.view", customer_leads, [
            Column("Lead", "code", link=True), Column("Title", "title"),
            Column("Stage", render=lambda o: badge(o.stage.name, "good" if o.stage.is_won else
                                                   "bad" if o.stage.is_lost else "info")),
            Column("Value", "estimated_value", money=True), Column("Created", "created_at", date=True)], order=10)

        def search(user, q):
            qs = scope_queryset(Lead.objects.select_related("stage"), user, OWNER_FIELDS).filter(
                Q(code__icontains=q) | Q(title__icontains=q) | Q(company_name__icontains=q) |
                Q(contact_person__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))[:8]
            return [(lead.title, f"{lead.code} · {lead.company_name} · {lead.stage}", lead.get_absolute_url())
                    for lead in qs]

        register_search("Leads", "leads.view", search, order=20)
        register_document_target(Lead, "Lead", "leads.view", OWNER_FIELDS)
        post_migrate.connect(_seed, sender=self)


def _seed(sender, **kwargs):
    from .services import seed_stages

    seed_stages()
