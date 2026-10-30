"""
Load FICTIONAL demonstration records (no real customers) and run them through the real workflow services:
lead → customer + opportunity → quotation → approval → sent → accepted → order → milestones → invoices →
payments, plus visits, tasks, communications and targets.

    python manage.py load_demo_users --password-env DEMO_USERS_PASSWORD
    python manage.py load_demo_data

Refuses to run twice (it checks for the demo marker customer) and, when DEBUG is False, unless
--allow-production is given.
"""
import datetime
import types
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core import middleware

MARKER = "Demo: Falcon Ridge Facilities LLC"

# All names, phone numbers, emails and TRNs below are invented. example.com / .test domains are reserved.
CUSTOMERS = [
    (MARKER, "Facility management", "Dubai", "info@falconridge.example.com", "+971 4 555 0101"),
    ("Demo: Oasis Crest Hospitality", "Hospitality", "Abu Dhabi", "projects@oasiscrest.example.com",
     "+971 2 555 0102"),
    ("Demo: Bluewater Marine Works", "Marine", "Sharjah", "procurement@bluewater.example.com", "+971 6 555 0103"),
    ("Demo: Sandstone Developments", "Real estate", "Dubai", "tenders@sandstone.example.com", "+971 4 555 0104"),
    ("Demo: Northgate District Cooling", "Utilities", "Ras Al Khaimah", "ops@northgate.example.com",
     "+971 7 555 0105"),
]

DEALS = [
    # customer index, title, lines [(description, qty, unit, price, discount%)], outcome, milestones preset
    (0, "Chiller plant maintenance contract", [("Annual preventive maintenance – chillers", 1, "lot", 180000, 0),
                                               ("Emergency call-out allowance", 12, "visit", 2500, 0)],
     "paid", "50-50"),
    (1, "Kitchen exhaust ventilation upgrade", [("Exhaust fan supply & install", 6, "nos", 14500, 5),
                                                ("Ductwork modification", 1, "lot", 38000, 0)],
     "partial", "30-70"),
    (2, "Seawater pump overhaul", [("Pump overhaul – 75 kW", 2, "nos", 26000, 0),
                                   ("Spare parts kit", 2, "set", 6500, 10)], "invoiced", "100"),
    (3, "BMS integration – Tower B", [("BMS controllers", 24, "nos", 3200, 0),
                                      ("Programming & commissioning", 1, "lot", 45000, 0)], "confirmed", "30-40-30"),
    (4, "Cooling tower water treatment", [("Dosing system", 1, "set", 52000, 0),
                                          ("Chemicals – 12 months", 12, "month", 4200, 0)], "sent", None),
    (0, "Fire pump replacement", [("Fire pump set", 1, "set", 96000, 0)], "approval", None),
    (1, "Lighting retrofit – lobby", [("LED fittings", 140, "nos", 380, 0)], "draft", None),
    (2, "Dock crane hydraulic service", [("Hydraulic service", 1, "lot", 61000, 0)], "declined", None),
]

LEADS = [
    ("Demo: Palm Vista Schools", "HVAC replacement – 3 campuses", "Dubai", 420000, "high", 2),
    ("Demo: Harbor Line Logistics", "Warehouse ventilation", "Jebel Ali", 150000, "medium", 1),
    ("Demo: Summit Clinics Group", "Medical gas & HVAC AMC", "Abu Dhabi", 275000, "high", 3),
    ("Demo: Desert Bloom Malls", "Escalator area cooling", "Al Ain", 98000, "low", 0),
    ("Demo: Coral Bay Residences", "Pump room upgrade", "Fujairah", 64000, "medium", 4),
]


def _as(user):
    """Run the following code as `user` so created_by / updated_by are filled like a real request."""
    middleware._local.request = types.SimpleNamespace(user=user, META={}, path="/demo-data/")


class Command(BaseCommand):
    help = "Load fictional demonstration data through the real CRM workflow (for demos and testing only)."

    def add_arguments(self, parser):
        parser.add_argument("--allow-production", action="store_true",
                            help="Allow running when DEBUG is False (e.g. on a demo server).")
        parser.add_argument("--if-missing", action="store_true",
                            help="Do nothing (and succeed) when the demo data is already loaded.")

    def handle(self, *args, **opts):
        from customers.models import Customer

        if not settings.DEBUG and not opts["allow_production"]:
            raise CommandError("DEBUG is False. Add --allow-production to load demo data on this server.")
        if Customer.objects.filter(company_name=MARKER).exists():
            if opts["if_missing"]:
                self.stdout.write("Demo data is already loaded; nothing to do.")
                return
            raise CommandError("Demo data is already loaded.")
        User = get_user_model()
        users = {u.username: u for u in User.objects.filter(username__startswith="demo.")}
        needed = ["demo.director", "demo.accounts", "demo.engineer", "demo.coordinator"]
        missing = [n for n in needed if n not in users]
        if missing:
            raise CommandError("Create the demo users first: python manage.py load_demo_users "
                               "--password-env DEMO_USERS_PASSWORD  (missing: " + ", ".join(missing) + ")")
        try:
            with transaction.atomic():
                summary = self._load(users)
        finally:
            middleware._local.request = None
        self.stdout.write(self.style.SUCCESS("Demo data loaded: " + ", ".join(f"{v} {k}" for k, v in summary.items())))

    # ------------------------------------------------------------------
    def _load(self, u):
        from communications.models import Communication
        from core.models import TaxRate
        from customers.models import Customer, CustomerContact
        from invoicing import services as inv
        from invoicing.models import Payment
        from leads import services as lead_services
        from leads.models import Lead, LeadStage
        from orders import services as order_services
        from performance.models import KPIDefinition, SalesTarget
        from quotations import services as q_services
        from quotations.models import QuotationLine
        from sales import services as sales_services
        from sales.models import Opportunity, OpportunityStage
        from tasks.models import Task
        from visits.models import Visit

        today = timezone.localdate()
        eng, coord, director, accounts = u["demo.engineer"], u["demo.coordinator"], u["demo.director"], \
            u["demo.accounts"]
        approver = u.get("demo.owner") or director  # approvals are the Owner's (Director when no Owner)
        vat = TaxRate.default()
        counts = dict.fromkeys(["customers", "leads", "opportunities", "quotations", "orders", "invoices",
                                "payments", "visits", "tasks", "communications"], 0)

        # customers + contacts
        _as(eng)
        customers = []
        for i, (name, industry, city, email, phone) in enumerate(CUSTOMERS):
            c = Customer(company_name=name, city=city, country="United Arab Emirates", email=email, phone=phone,
                         status="active", assigned_engineer=eng, assigned_coordinator=coord,
                         contact_person=f"Demo Contact {i + 1}", designation="Facilities Manager",
                         billing_address=f"Office {100 + i}, Demo Business Park, {city}",
                         trn=f"1000000000{i:05d}", notes="Fictional demonstration customer.")
            c.save()
            CustomerContact.objects.create(customer=c, name=f"Demo Contact {i + 1}", designation="Facilities Manager",
                                           email=f"contact{i + 1}@example.com", phone=f"+971 50 555 01{i:02d}",
                                           is_primary=True)
            customers.append(c)
            counts["customers"] += 1

        # leads at various stages
        stages = list(LeadStage.objects.filter(is_won=False, is_lost=False, is_active=True))
        for company, title, city, value, prio, stage_idx in LEADS:
            lead = Lead(company_name=company, title=title, city=city, estimated_value=Decimal(value), priority=prio,
                        contact_person="Demo Enquirer", email="enquiry@example.com", phone="+971 55 555 0199",
                        assigned_engineer=eng, assigned_coordinator=coord, stage=stages[0],
                        next_follow_up=today + datetime.timedelta(days=stage_idx + 1),
                        interest="HVAC / MEP services")
            lead.save()
            lead_services.record_assignment(lead, note="Demo data")
            if stage_idx:
                lead_services.change_stage(lead, stages[min(stage_idx, len(stages) - 1)], note="Demo progress")
            counts["leads"] += 1

        # one lead converted end-to-end into the first deal's customer + opportunity
        conv = Lead(company_name=CUSTOMERS[0][0], title="Chiller plant enquiry", city="Dubai",
                    estimated_value=Decimal(210000), assigned_engineer=eng, stage=stages[-1], priority="high")
        conv.save()
        counts["leads"] += 1

        open_stages = list(OpportunityStage.objects.filter(is_won=False, is_lost=False, is_active=True))
        for n, (ci, title, lines, outcome, preset) in enumerate(DEALS):
            cust = customers[ci]
            _as(eng)
            if n == 0:
                lead_services.convert(conv, customer=cust, user=eng, opportunity_data={
                    "title": title, "estimated_value": Decimal(204000),
                    "expected_close_date": today + datetime.timedelta(days=20)})
                opp = Opportunity.objects.get(lead=conv)
            else:
                opp = Opportunity(title=title, customer=cust, assigned_engineer=eng, assigned_coordinator=coord,
                                  stage=open_stages[min(2 + n % 3, len(open_stages) - 1)],
                                  estimated_value=Decimal(sum(q * p for _, q, _, p, _ in lines)),
                                  expected_close_date=today + datetime.timedelta(days=15 * (n + 1)),
                                  location=cust.city)
                opp.probability = opp.stage.default_probability
                opp.save()
                sales_services.record_creation(opp)
            counts["opportunities"] += 1

            quote, rev = q_services.create_quotation(customer=cust, opportunity=opp, salesperson=eng,
                                                     currency="AED", user=eng)
            rev.scope_of_work = f"Supply, installation and commissioning for: {title}."
            rev.save()
            for pos, (desc, qty, unit, price, disc) in enumerate(lines, start=1):
                QuotationLine.objects.create(revision=rev, position=pos, description=desc, quantity=Decimal(qty),
                                             unit=unit, unit_price=Decimal(price), discount_pct=Decimal(disc),
                                             tax_rate=vat)
            q_services.recalculate(rev)
            counts["quotations"] += 1
            if outcome == "draft":
                continue
            rev.refresh_from_db()
            q_services.submit(rev, eng)
            rev.refresh_from_db()
            if outcome == "approval":
                continue
            if rev.status == "submitted":
                _as(approver)
                q_services.approve(rev, approver, "Approved (demo).")
                rev.refresh_from_db()
            _as(eng)
            q_services.mark_sent(rev, eng)
            rev.refresh_from_db()
            if outcome == "sent":
                continue
            if outcome == "declined":
                q_services.record_decline(rev, eng, date=today, reason="Budget postponed (demo)")
                continue
            q_services.record_acceptance(rev, eng, date=today, accepted_by_name="Demo Procurement Manager",
                                         customer_reference=f"PO-DEMO-{n + 1:03d}")
            quote.refresh_from_db()
            order = order_services.create_from_quotation(quote, user=eng, preset=preset,
                                                         customer_po_ref=f"PO-DEMO-{n + 1:03d}")
            counts["orders"] += 1
            _as(director)
            order_services.confirm(order, director)
            if outcome == "confirmed":
                continue
            _as(accounts)
            milestones = list(order.milestones.order_by("sequence"))
            to_invoice = milestones if outcome == "paid" else milestones[:1]
            invoices = []
            for m in to_invoice:
                invoice = inv.create_from_milestone(m, accounts)
                invoice = inv.issue(invoice, accounts)
                invoices.append(invoice)
                counts["invoices"] += 1
            if outcome in ("paid", "partial"):
                for invoice in invoices:
                    invoice.refresh_from_db()
                    amount = invoice.total if outcome == "paid" else (invoice.total / 2).quantize(Decimal("0.01"))
                    inv.record_payment(customer=cust, payment_date=today, amount=amount, method="bank",
                                       reference=f"DEMO-TRF-{invoice.pk:04d}", allocations=[(invoice, amount)],
                                       user=accounts)
                    counts["payments"] += 1

        # an overdue invoice for the collections screen: back-date the first open invoice
        from invoicing.models import Invoice

        overdue = Invoice.objects.filter(status__in=["issued", "partially_paid"]).order_by("pk").first()
        if overdue:
            Invoice.objects.filter(pk=overdue.pk).update(invoice_date=today - datetime.timedelta(days=50),
                                                         due_date=today - datetime.timedelta(days=20))

        # visits (past completed, upcoming scheduled)
        _as(coord)
        from core.models import LookupValue

        purpose = LookupValue.objects.filter(category="visit_purpose", is_active=True).first()
        for i, cust in enumerate(customers):
            past = i % 2 == 0
            v = Visit(customer=cust, assigned_to=eng, location=cust.city, purpose=purpose,
                      visit_date=today + datetime.timedelta(days=(-7 - i) if past else (i + 1)),
                      start_time=datetime.time(10, 0), end_time=datetime.time(11, 0),
                      agenda="Review requirements and site conditions.",
                      status="completed" if past else "scheduled")
            if past:
                v.meeting_notes = "Discussed scope and timeline (demo)."
                v.completed_at = timezone.now()
                v.completed_by = eng
            v.save()
            counts["visits"] += 1

        # tasks and communications
        for i, cust in enumerate(customers):
            Task.objects.create(title=f"Follow up with {cust.company_name}", customer=cust, assigned_to=eng,
                                due_date=today + datetime.timedelta(days=i - 2), category="follow_up",
                                priority="high" if i < 2 else "medium")
            counts["tasks"] += 1
            Communication.objects.create(customer=cust, employee=eng, kind="call", direction="out",
                                         occurred_at=timezone.now() - datetime.timedelta(days=i + 1),
                                         subject="Introductory call", summary="Discussed upcoming requirements "
                                                                              "(fictional demo record).",
                                         outcome="Positive", next_action="Send company profile")
            counts["communications"] += 1
        Task.objects.create(title="Chase overdue invoice", assigned_to=accounts, category="collection",
                            due_date=today - datetime.timedelta(days=1), priority="high", customer=customers[1])
        counts["tasks"] += 1

        # monthly targets for the engineer
        _as(director)
        month_start = today.replace(day=1)
        defaults = {"amount": Decimal(500000), "count": Decimal(10), "percent": Decimal(30)}
        for kpi in KPIDefinition.objects.filter(is_active=True):
            SalesTarget.objects.get_or_create(employee=eng, kpi=kpi, period_type="month", period_start=month_start,
                                              defaults={"target_value": defaults[kpi.unit]})

        # lead categories (every lead has one) and uploaded quotations with revisions (fictional documents)
        cats = [c for c, _ in Lead.Category.choices]
        for i, ld in enumerate(Lead.objects.filter(company_name__startswith="Demo: ").order_by("pk")):
            Lead.objects.filter(pk=ld.pk).update(category=cats[i % 3])
        from django.core.files.uploadedfile import SimpleUploadedFile
        from quotations import uploads as q_uploads

        def demo_pdf(label):
            return SimpleUploadedFile(f"demo_quotation_{label}.pdf", b"%PDF-1.4\n% fictional demo quotation "
                                      + label.encode() + b"\n%%EOF\n", "application/pdf")
        _as(eng)
        uq = q_uploads.create_uploaded(customer=customers[2], salesperson=eng, user=eng, file=demo_pdf("original"),
                                       value=Decimal("48500"), quotation_date=today - datetime.timedelta(days=12),
                                       external_number="TF-Q-DEMO-101", notes="First offer (demo).")
        submitted = q_services.submit(uq.current, eng)
        _as(approver)
        if submitted.status == "submitted":
            q_services.approve(submitted, approver, "Approved (demo).")
        _as(eng)
        q_uploads.upload_revision(uq, user=eng, file=demo_pdf("r1"), value=Decimal("46000"),
                                  quotation_date=today - datetime.timedelta(days=3),
                                  notes="Customer asked for a 5% better price (demo).")
        uq2 = q_uploads.create_uploaded(customer=customers[3], salesperson=eng, user=eng, file=demo_pdf("pending"),
                                        value=Decimal("265000"), quotation_date=today,
                                        external_number="TF-Q-DEMO-102", notes="Large chiller package (demo).")
        q_services.submit(uq2.current, eng)
        counts["quotations"] += 2

        # daily work reports (self-reported, fictional): one reviewed, one submitted, one draft
        from performance.models import DailyReport

        _as(eng)
        workdays = [d for d in (today - datetime.timedelta(days=n) for n in range(1, 8)) if d.weekday() < 5][:2]
        for n, day in enumerate(workdays):
            rep = DailyReport.objects.create(
                employee=eng, report_date=day, status="submitted", submitted_at=timezone.now(),
                calls_followups="Called two customers about pending quotations (demo).",
                visits_outcomes="Site visit, requirements noted (demo).", pending_work="Revise one quotation.",
                next_day_plan="Follow up on open quotations.")
            rep.entries.create(kind="call", customer=customers[n], description="Follow-up call",
                               outcome="Customer asked for a revised offer", position=0)
            if n == 1:
                rep.status, rep.reviewed_by, rep.reviewed_at = "reviewed", coord, timezone.now()
                rep.review_comment = "Thanks, good detail (demo)."
                rep.save()
        DailyReport.objects.create(employee=eng, report_date=today, status="draft",
                                   calls_followups="Draft in progress (demo).")
        counts["daily reports"] = len(workdays) + 1
        assert Payment.objects.count() == counts["payments"]
        return counts
