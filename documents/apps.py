from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "documents"
    verbose_name = "Documents"

    def ready(self):
        from communications.models import OWNER_FIELDS as COMM_OWNERS
        from communications.models import Communication
        from core.registry import register_document_target

        register_document_target(Communication, "Communication", "communications.view", COMM_OWNERS)
