from django.utils import timezone

from core.activity import record

from .models import Task


def create_follow_up(*, title, assigned_to, due_date, description="", customer=None, lead=None, visit=None,
                     opportunity=None, quotation=None, invoice=None, category=Task.Category.FOLLOW_UP,
                     priority=Task.Priority.MEDIUM):
    task = Task.objects.create(
        title=title[:200], description=description, assigned_to=assigned_to, due_date=due_date,
        start_date=timezone.localdate(), customer=customer, lead=lead, visit=visit, opportunity=opportunity,
        quotation=quotation, invoice=invoice, category=category, priority=priority)
    record(task, "task", f"Task created: {task.title} (due {due_date:%d-%b-%Y}, {assigned_to.get_full_name()})",
           customer=customer)
    notify_task_assigned(task)
    return task


def notify_task_assigned(task, previous=None):
    from core.middleware import get_current_user
    from notifications.services import notify

    current = get_current_user()
    if task.assigned_to_id and task.assigned_to_id != getattr(previous, "pk", None) and task.assigned_to != current:
        notify([task.assigned_to], "task_assigned", f"New task: {task.title}",
               f"Due {task.due_date:%d-%b-%Y}", task.get_absolute_url())
