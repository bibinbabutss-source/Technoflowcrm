from django.apps import AppConfig


class VisitsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "visits"
    verbose_name = "Customer visits"

    def ready(self):
        from django.urls import reverse

        from accounts.permissions import scope_queryset
        from core.audit import track_model
        from core.crud import Column, badge
        from core.registry import register_customer_section, register_document_target

        from .models import OWNER_FIELDS, Visit

        track_model(Visit)

        def customer_visits(customer, user):
            return scope_queryset(customer.visits.select_related("assigned_to", "purpose"), user, OWNER_FIELDS)

        register_customer_section("visits", "Visits", "visits.view", customer_visits, [
            Column("Visit", "code", link=True), Column("Date", "visit_date", date=True),
            Column("Purpose", "purpose"), Column("Employee", "assigned_to"),
            Column("Status", render=lambda v: badge("Missed" if v.is_missed else v.get_status_display(), v.tone()))],
            order=20, add_url=lambda c: reverse("visits:create") + f"?customer={c.pk}", add_capability="visits.create")
        register_document_target(Visit, "Customer visit", "visits.view", OWNER_FIELDS)
