import getpass

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from accounts import capabilities as caps
from accounts.models import Role
from accounts.services import create_employee


class Command(BaseCommand):
    help = "Create the System Administrator account (first-time setup)."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--first-name", required=True)
        parser.add_argument("--last-name", required=True)
        parser.add_argument("--employee-id", default="TF-ADMIN-01")
        parser.add_argument(
            "--password-env", metavar="VARIABLE",
            help="Read the temporary password from this environment variable instead of asking "
                 "(for hosts without an interactive shell).",
        )
        parser.add_argument("--if-missing", action="store_true",
                            help="Do nothing if a System Administrator already exists.")

    def handle(self, *args, **opts):
        import os

        role = Role.objects.get(code=caps.ADMIN)
        if opts["if_missing"] and role.active_count() > 0:
            self.stdout.write("A System Administrator already exists; nothing to do.")
            return
        if opts["password_env"]:
            password = os.environ.get(opts["password_env"], "")
            if not password:
                raise CommandError(f"Environment variable {opts['password_env']} is empty or not set.")
        else:
            password = getpass.getpass("Temporary password: ")
            if password != getpass.getpass("Repeat password: "):
                raise CommandError("Passwords do not match.")
        try:
            user = create_employee(
                username=opts["username"], email=opts["email"], first_name=opts["first_name"],
                last_name=opts["last_name"], employee_id=opts["employee_id"], role=role,
                temporary_password=password, department="Administration",
            )
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages))
        self.stdout.write(self.style.SUCCESS(
            f"System Administrator '{user.username}' created. A password change is required at first sign-in."))
