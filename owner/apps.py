from django.apps import AppConfig


class OwnerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "owner"
    verbose_name = "Owner dashboard, approvals and team calendar"
