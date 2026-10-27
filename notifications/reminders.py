"""
Daily reminders and status housekeeping. Runs at most once per day:

- automatically, the first time anyone opens the dashboard each day (works on hosting without a scheduler), or
- from a scheduler: `python manage.py send_reminders` (cron / Windows Task Scheduler / Render Cron Job), or
- by the Administrator: Settings > Reminders > Run now.

What it does:
- expires approved / sent quotations past their expiry date and warns about those expiring soon
- reminds employees of visits in the next N days, tasks due within N days and overdue tasks
- reminds about overdue follow-up dates on leads, customers and opportunities
- reminds Accounts and the salesperson about overdue invoices on the configured days (e.g. 1, 7, 30 days late)
"""
import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import CompanyProfile, SystemJobRun

from .services import notify

log = logging.getLogger("technoflow")
JOB = "daily_reminders"


def run_if_due():
    today = timezone.localdate()
    job, _ = SystemJobRun.objects.get_or_create(name=JOB)
    if job.last_run_date == today:
        return None
    with transaction.atomic():
        job = SystemJobRun.objects.select_for_update().get(pk=job.pk)
        if job.last_run_date == today:
            return None
        job.last_run_date = today
        job.last_run_at = timezone.now()
        job.save()
    try:
        result = run()
    except Exception:
        log.exception("Daily reminders failed")
        SystemJobRun.objects.filter(pk=job.pk).update(last_result="Failed — see the error log")
        return None
    SystemJobRun.objects.filter(pk=job.pk).update(last_result=result)
    return result


def run():
    from invoicing.models import Invoice
    from leads.models import Lead
    from quotations.models import QuotationRevision
    from quotations.services import expire_overdue
    from sales.models import Opportunity
    from tasks.models import Task
    from visits.models import Visit

    company = CompanyProfile.get()
    today = timezone.localdate()
    key = today.isoformat()
    counts = {}

    counts["quotations expired"] = expire_overdue()

    soon = today + timezone.timedelta(days=company.quotation_expiry_warning_days)
    n = 0
    for rev in QuotationRevision.objects.filter(status__in=["approved", "sent"], expiry_date__gte=today,
                                                expiry_date__lte=soon).select_related("quotation__salesperson"):
        q = rev.quotation
        n += len(notify([q.salesperson], "quotation_expiring", f"Quotation expiring {rev.expiry_date:%d-%b-%Y}: "
                        f"{q.number}", q.customer.company_name, q.get_absolute_url(),
                        dedupe_key=f"qexp:{rev.pk}"))
    counts["expiry warnings"] = n

    horizon = today + timezone.timedelta(days=company.visit_reminder_days)
    n = 0
    for v in Visit.objects.filter(status__in=Visit.UPCOMING_STATUSES, visit_date__gte=today,
                                  visit_date__lte=horizon).select_related("assigned_to", "customer"):
        n += len(notify([v.assigned_to], "visit_upcoming", f"Visit {v.visit_date:%a %d-%b} {v.start_time:%H:%M}: "
                        f"{v.customer.company_name}", v.location, v.get_absolute_url(), dedupe_key=f"visit:{v.pk}"))
    counts["visit reminders"] = n

    due_by = today + timezone.timedelta(days=company.task_reminder_days)
    n = 0
    for t in Task.objects.filter(status__in=Task.OPEN_STATUSES, due_date__lte=due_by).select_related("assigned_to"):
        overdue = t.due_date < today
        n += len(notify([t.assigned_to], "task_due",
                        f"{'Overdue' if overdue else 'Due'} {t.due_date:%d-%b}: {t.title}", t.code,
                        t.get_absolute_url(), dedupe_key=f"task:{t.pk}:{key if overdue else 'due'}"))
    counts["task reminders"] = n

    n = 0
    for lead in Lead.objects.filter(next_follow_up__lt=today, is_archived=False, stage__is_won=False,
                                    stage__is_lost=False).select_related("assigned_engineer"):
        n += len(notify([lead.assigned_engineer], "followup_overdue", f"Lead follow-up overdue: {lead.title}",
                        f"Was due {lead.next_follow_up:%d-%b-%Y}", lead.get_absolute_url(),
                        dedupe_key=f"lfu:{lead.pk}:{lead.next_follow_up}"))
    for opp in Opportunity.objects.filter(next_follow_up__lt=today, is_archived=False, stage__is_won=False,
                                          stage__is_lost=False).select_related("assigned_engineer"):
        n += len(notify([opp.assigned_engineer], "followup_overdue", f"Opportunity follow-up overdue: {opp.title}",
                        f"Was due {opp.next_follow_up:%d-%b-%Y}", opp.get_absolute_url(),
                        dedupe_key=f"ofu:{opp.pk}:{opp.next_follow_up}"))
    counts["follow-up reminders"] = n

    User = get_user_model()
    accounts = list(User.objects.filter(is_active=True, profile__role__capabilities__code="invoices.manage")
                    .distinct())
    steps = company.overdue_reminder_list
    n = 0
    for inv in Invoice.objects.filter(status__in=Invoice.OPEN_STATUSES, due_date__lt=today).select_related(
            "order__assigned_to", "customer"):
        days = (today - inv.due_date).days
        reached = [s for s in steps if days >= s]
        if not reached:
            continue
        step = max(reached)
        if inv.last_reminder_days is not None and inv.last_reminder_days >= step:
            continue
        n += len(notify(accounts + [inv.order.assigned_to], "invoice_overdue",
                        f"Invoice {inv.number} overdue {days} days", f"{inv.customer.company_name} · outstanding "
                        f"{inv.currency} {inv.outstanding:,.2f}", inv.get_absolute_url(),
                        dedupe_key=f"inv:{inv.pk}:{step}"))
        Invoice.objects.filter(pk=inv.pk).update(last_reminder_days=step)
    counts["overdue invoice reminders"] = n

    return ", ".join(f"{v} {k}" for k, v in counts.items())
