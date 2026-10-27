from django.apps import AppConfig


class CustomersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "customers"
    verbose_name = "Customers"

    def ready(self):
        from core.audit import track_model
        from core.registry import register_document_target, register_search

        from .models import Customer, CustomerContact, OWNER_FIELDS
        from .search import search

        track_model(Customer, exclude=["normalized_name"])
        track_model(CustomerContact)
        register_search("Customers", "customers.view", search, order=10)
        register_document_target(Customer, "Customer", "customers.view", OWNER_FIELDS)
