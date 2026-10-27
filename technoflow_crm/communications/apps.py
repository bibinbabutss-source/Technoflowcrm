from django.apps import AppConfig


class CommunicationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "communications"
    verbose_name = "Communication history"

    def ready(self):
        from django.urls import reverse

        from accounts.permissions import scope_queryset
        from core.audit import track_model
        from core.crud import Column
        from core.registry import register_customer_section

        from .models import OWNER_FIELDS, Communication

        track_model(Communication)

        def customer_comms(customer, user):
            return scope_queryset(customer.communications.select_related("employee"), user, OWNER_FIELDS)

        register_customer_section("communications", "Communication history", "communications.view",
                                  customer_comms, [
                                      Column("When", "occurred_at", date=True),
                                      Column("Type", lambda c: c.get_kind_display()),
                                      Column("Subject", "subject", link=True), Column("Employee", "employee"),
                                      Column("Outcome", "outcome")],
                                  order=70, add_url=lambda c: reverse("communications:create") + f"?customer={c.pk}",
                                  add_capability="communications.create")
