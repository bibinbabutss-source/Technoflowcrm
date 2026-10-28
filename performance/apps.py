from django.apps import AppConfig
from django.db.models.signals import post_migrate


class PerformanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "performance"
    verbose_name = "Targets, KPIs and employee performance"

    def ready(self):
        from core.audit import track_model

        from .models import DailyReport, DailyReportEntry, KPIDefinition, SalesTarget

        track_model(KPIDefinition)
        track_model(SalesTarget)
        track_model(DailyReport, exclude=["updated_at"])  # edit history: every change with old -> new values
        track_model(DailyReportEntry)
        post_migrate.connect(_seed, sender=self)


def _seed(sender, **kwargs):
    from .services import seed_kpis

    seed_kpis()
