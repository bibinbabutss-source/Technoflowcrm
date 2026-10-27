from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tasks"
    verbose_name = "Tasks and follow-ups"

    def ready(self):
        from django.db.models import Q
        from django.urls import reverse

        from accounts.permissions import scope_queryset
        from core.audit import track_model
        from core.crud import Column, badge
        from core.registry import register_customer_section, register_search

        from .models import OWNER_FIELDS, Task

        track_model(Task)

        def customer_tasks(customer, user):
            return scope_queryset(customer.tasks.select_related("assigned_to"), user, OWNER_FIELDS).order_by(
                "-due_date")

        register_customer_section("tasks", "Tasks & follow-ups", "tasks.view", customer_tasks, [
            Column("Task", "code", link=True), Column("Title", "title"), Column("Assigned to", "assigned_to"),
            Column("Due", "due_date", date=True),
            Column("Status", render=lambda t: badge(t.get_status_display(),
                                                    "bad" if t.is_overdue else "good" if t.status == "completed"
                                                    else "info"))],
            order=80, add_url=lambda c: reverse("tasks:create") + f"?customer={c.pk}", add_capability="tasks.create")

        def search(user, q):
            qs = scope_queryset(Task.objects.all(), user, OWNER_FIELDS).filter(
                Q(code__icontains=q) | Q(title__icontains=q))[:8]
            return [(t.title, f"{t.code} · due {t.due_date:%d-%b-%Y} · {t.get_status_display()}",
                     t.get_absolute_url()) for t in qs]

        register_search("Tasks", "tasks.view", search, order=80)
