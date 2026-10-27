from django.apps import AppConfig
from django.db.models.signals import post_migrate


class PerformanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "performance"
    verbose_name = "Targets and KPIs"

    def ready(self):
        from core.audit import track_model

        from .models import KPIDefinition, SalesTarget

        track_model(KPIDefinition)
        track_model(SalesTarget)
        post_migrate.connect(_seed, sender=self)


def _seed(sender, **kwargs):
    from .services import seed_kpis

    seed_kpis()
