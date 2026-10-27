from django.core.management.base import BaseCommand

from notifications import reminders


class Command(BaseCommand):
    help = "Run the daily reminders (once per day; --force runs again today)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Run even if it already ran today")

    def handle(self, *args, **opts):
        if opts["force"]:
            result = reminders.run()
            from core.models import SystemJobRun
            from django.utils import timezone

            SystemJobRun.objects.update_or_create(name=reminders.JOB, defaults={
                "last_run_date": timezone.localdate(), "last_run_at": timezone.now(), "last_result": result})
        else:
            result = reminders.run_if_due()
        self.stdout.write(result or "Already ran today. Use --force to run again.")
