"""
Remove the FICTIONAL demonstration records so the CRM can start fresh.

    python manage.py remove_demo_data            # preview only: shows what would be removed, changes nothing
    python manage.py remove_demo_data --confirm  # removes it (one transaction: all or nothing)

What counts as demo data:
  * customers and leads whose company name starts with "Demo: " (as created by load_demo_data), and every
    record linked to them: contacts, opportunities, quotations, orders, invoices, payments, visits, tasks,
    communications, projects, documents and activity entries;
  * targets, daily reports, imports and notifications of the demo logins (usernames "demo.*" with employee
    IDs "DEMO-*").
The demo logins are DEACTIVATED, not deleted: the audit log keeps referring to them and can never be erased.
Records your own employees created for real customers are never touched. Document numbering (QT-, INV-, ...)
restarts at 0001 only for document types that have no records left.
"""
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from core.audit import log_action

DEMO_PREFIX = "Demo: "


class Command(BaseCommand):
    help = "Preview (default) or remove (--confirm) the fictional demo records and deactivate the demo logins."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", action="store_true", help="Actually remove the demo data.")

    def handle(self, *args, **opts):
        from communications.models import Communication
        from core.models import Activity, NumberSequence
        from customers.models import Customer
        from documents.models import Document
        from invoicing.models import Invoice, Payment, PaymentAllocation
        from leads.models import Lead
        from notifications.models import Notification
        from orders.models import SalesOrder
        from performance.models import DailyReport, SalesTarget
        from quotations.models import Quotation, QuotationFile
        from reporting.models import ImportBatch
        from sales.models import Opportunity, Project
        from tasks.models import Task
        from visits.models import Visit

        User = get_user_model()
        demo_users = User.objects.filter(username__startswith="demo.", profile__employee_id__startswith="DEMO-")
        customers = Customer.objects.filter(company_name__startswith=DEMO_PREFIX)
        leads = Lead.objects.filter(Q(company_name__startswith=DEMO_PREFIX) | Q(customer__in=customers))
        opps = Opportunity.objects.filter(Q(customer__in=customers) | Q(lead__in=leads))
        quotes = Quotation.objects.filter(Q(customer__in=customers) | Q(opportunity__in=opps) | Q(lead__in=leads))
        quote_files = QuotationFile.objects.filter(revision__quotation__in=quotes)
        orders = SalesOrder.objects.filter(Q(customer__in=customers) | Q(quotation__in=quotes))
        invoices = Invoice.objects.filter(Q(customer__in=customers) | Q(order__in=orders))
        payments = Payment.objects.filter(customer__in=customers)
        allocations = PaymentAllocation.objects.filter(Q(payment__in=payments) | Q(invoice__in=invoices))
        visits = Visit.objects.filter(Q(customer__in=customers) | Q(lead__in=leads) | Q(opportunity__in=opps))
        comms = Communication.objects.filter(Q(customer__in=customers) | Q(lead__in=leads) | Q(opportunity__in=opps))
        projects = Project.objects.filter(Q(customer__in=customers) | Q(opportunity__in=opps) | Q(sales_order__in=orders))
        tasks = Task.objects.filter(Q(customer__in=customers) | Q(lead__in=leads) | Q(visit__in=visits)
                                    | Q(opportunity__in=opps) | Q(quotation__in=quotes) | Q(invoice__in=invoices))
        doc_q = Q(customer__in=customers)
        for model, qs in ((Customer, customers), (Lead, leads), (Opportunity, opps), (Quotation, quotes),
                          (SalesOrder, orders), (Invoice, invoices), (Visit, visits), (Communication, comms),
                          (Project, projects)):
            doc_q |= Q(target_type=ContentType.objects.get_for_model(model), target_id__in=qs.values("pk"))
        documents = Document.objects.filter(doc_q)
        targets = SalesTarget.objects.filter(employee__in=demo_users)
        reports = DailyReport.objects.filter(employee__in=demo_users)
        imports = ImportBatch.objects.filter(uploaded_by__in=demo_users)
        notes = Notification.objects.filter(user__in=demo_users)

        plan = [("Payment allocations", allocations), ("Payments", payments), ("Tasks", tasks),
                ("Documents", documents), ("Invoices", invoices), ("Projects", projects), ("Sales orders", orders),
                ("Visits", visits), ("Communications", comms), ("Quotation files", quote_files),
                ("Quotations", quotes), ("Opportunities", opps),
                ("Leads", leads), ("Customers", customers), ("Targets of demo logins", targets),
                ("Daily reports of demo logins", reports), ("Imports by demo logins", imports),
                ("Notifications of demo logins", notes)]
        counts = [(label, qs.count()) for label, qs in plan]
        active_demo = list(demo_users.filter(is_active=True).values_list("username", flat=True))

        self.stdout.write("Demo data found:")
        for label, n in counts:
            self.stdout.write(f"  {label:32} {n}")
        self.stdout.write(f"  {'Demo logins to deactivate':32} {len(active_demo)} {', '.join(active_demo)}")
        still = self._still_assigned(demo_users, customers, leads, opps, tasks)
        if still:
            self.stdout.write("Real records assigned to demo logins (kept; reassign them to real employees):")
            for label, n in still:
                self.stdout.write(f"  {label:32} {n}")

        if not opts["confirm"]:
            self.stdout.write(self.style.WARNING("Preview only - nothing was changed. Add --confirm to remove."))
            return
        if not any(n for _, n in counts) and not active_demo:
            self.stdout.write(self.style.SUCCESS("No demo data left; nothing to do."))
            return

        file_names = list(documents.values_list("file", flat=True))
        with transaction.atomic():
            # children first; reversal payments before the payments they reverse
            removed = {}
            for label, qs in plan:
                ids = list(qs.values_list("pk", flat=True))
                model = qs.model
                if model is Payment:
                    Payment.objects.filter(pk__in=ids, reverses__isnull=False).delete()
                if model is Document:
                    model.objects.filter(pk__in=ids).update(previous=None)
                model.objects.filter(pk__in=ids).delete()  # bulk delete on purpose: bypasses the
                removed[label] = len(ids)                   # "never delete" guards, for demo records only
            Activity.objects.filter(customer__isnull=True, user__in=demo_users).delete()
            demo_users.update(is_active=False)
            reset = []
            for code, model in (("quotation", Quotation), ("order", SalesOrder), ("invoice", Invoice),
                                ("payment", Payment), ("customer", Customer), ("lead", Lead),
                                ("opportunity", Opportunity), ("visit", Visit), ("task", Task),
                                ("project", Project), ("communication", Communication)):
                if not model.objects.exists():
                    reset += [s.code for s in NumberSequence.objects.filter(code=code, last_number__gt=0)]
                    NumberSequence.objects.filter(code=code).update(last_number=0, current_year=None)
            log_action("delete", message=("Demo data removed: " + ", ".join(f"{k} {v}" for k, v in removed.items()
                                                                          if v) + f"; demo logins deactivated: "
                                          f"{', '.join(active_demo) or 'none'}")[:500])
        storage = Document._meta.get_field("file").storage
        for name in file_names:
            try:
                if name and storage.exists(name):
                    storage.delete(name)
            except OSError:
                pass
        self.stdout.write(self.style.SUCCESS("Demo data removed. Demo logins deactivated."))
        if reset:
            self.stdout.write("Numbering restarted at 0001 for: " + ", ".join(reset))

    @staticmethod
    def _still_assigned(demo_users, customers, leads, opps, tasks):
        from customers.models import Customer
        from leads.models import Lead
        from sales.models import Opportunity
        from tasks.models import Task

        rows = [
            ("Customers", Customer.objects.exclude(pk__in=customers.values("pk")).filter(
                Q(assigned_engineer__in=demo_users) | Q(assigned_coordinator__in=demo_users)).count()),
            ("Leads", Lead.objects.exclude(pk__in=leads.values("pk")).filter(
                Q(assigned_engineer__in=demo_users) | Q(assigned_coordinator__in=demo_users)).count()),
            ("Opportunities", Opportunity.objects.exclude(pk__in=opps.values("pk")).filter(
                Q(assigned_engineer__in=demo_users) | Q(assigned_coordinator__in=demo_users)).count()),
            ("Open tasks", Task.objects.filter(assigned_to__in=demo_users).exclude(pk__in=tasks.values("pk")).exclude(
                status__in=["completed", "cancelled"]).count()),
        ]
        return [r for r in rows if r[1]]
