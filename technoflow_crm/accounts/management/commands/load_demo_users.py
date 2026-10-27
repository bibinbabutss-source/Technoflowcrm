"""
Create fictional demo users, one per role, for testing and demonstrations.

    python manage.py load_demo_users --password "Demo-Pass-2026!"           (laptop)
    python manage.py load_demo_users --password-env DEMO_USERS_PASSWORD \\
        --allow-production --no-password-change                              (online demo, run by build.sh)

Safe to run repeatedly: existing demo users are left alone, and a role that
is already full (for example System Administrator, once the real
administrator exists) is skipped instead of breaking the role limits.

Before the CRM is used for real business, deactivate the demo users in
User Management.
"""
import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts import capabilities as caps
from accounts.models import EmployeeProfile, Role
from accounts.services import create_employee

DEMO = [
    (caps.ADMIN, "demo.admin", "Alex", "Admin", "DEMO-001", "Administration"),
    (caps.DIRECTOR, "demo.director", "Dana", "Director", "DEMO-002", "Management"),
    (caps.ACCOUNTS, "demo.accounts", "Avery", "Accounts", "DEMO-003", "Accounts"),
    (caps.ENGINEER, "demo.engineer", "Elliot", "Engineer", "DEMO-004", "Sales"),
    (caps.COORDINATOR, "demo.coordinator", "Casey", "Coordinator", "DEMO-005", "Sales"),
]


class Command(BaseCommand):
    help = "Create fictional demo users (one per role) for testing or an online demonstration."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--password", help="Password given to every demo user")
        source.add_argument("--password-env", metavar="VARIABLE",
                            help="Read the password from this environment variable (used on Render)")
        parser.add_argument("--allow-production", action="store_true",
                            help="Allow running when DEBUG=False (online demonstration server)")
        parser.add_argument("--no-password-change", action="store_true",
                            help="Do not force demo users to change the password at first sign-in, "
                                 "so several people can use the same demo login")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["allow_production"]:
            raise CommandError("DEBUG is False. Add --allow-production to create demo users on this server.")
        password = opts["password"]
        if opts["password_env"]:
            password = os.environ.get(opts["password_env"], "")
            if not password:
                raise CommandError(f"Environment variable {opts['password_env']} is empty or not set.")

        engineer = EmployeeProfile.objects.filter(employee_id="DEMO-004").first()
        for code, username, first, last, emp_id, dept in DEMO:
            role = Role.objects.get(code=code)
            if EmployeeProfile.objects.filter(employee_id=emp_id).exists():
                self.stdout.write(f"  {username} already exists")
                continue
            if role.active_count() >= role.max_accounts:
                self.stdout.write(f"  {username} skipped: the {role.name} role is already full")
                continue
            try:
                user = create_employee(
                    username=username, email=f"{username}@example.com", first_name=first, last_name=last,
                    employee_id=emp_id, role=role, temporary_password=password, department=dept,
                )
            except ValidationError as exc:
                raise CommandError(f"Could not create {username}: {'; '.join(exc.messages)}")
            if opts["no_password_change"]:
                user.profile.must_change_password = False
                user.profile.save(update_fields=["must_change_password"])
            if code == caps.ENGINEER:
                engineer = user.profile
            if code == caps.COORDINATOR and engineer:
                user.profile.team_members.add(engineer)
            self.stdout.write(self.style.SUCCESS(f"  created {username} ({role.name})"))
        if not opts["no_password_change"]:
            self.stdout.write("Each demo user must change the password at first sign-in.")
