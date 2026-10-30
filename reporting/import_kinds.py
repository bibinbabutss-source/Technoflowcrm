"""
What each import type contains, how a cell is read, how duplicates are found and how a row is saved.

Duplicate rules (names alone never make a reliable match):
    reliable match  (may UPDATE the existing record, only in "update" mode, after a preview of the changes)
        - the CRM code given in the file (CUS-…, LD-…, VIS-…, TSK-…, OPP-…)
        - the same "Reference" from an earlier import of the same type (stored in ImportKey)
        - customers: the same TRN, or the same email AND the same phone
    possible duplicate  (always skipped, never updated)
        - customers: same company name, email or phone   - leads: an open lead with the same company, email or phone
        - visits: same customer, date, start time and employee      - tasks: same title, due date and employee
        - opportunities: same customer and title, or the same row (customer, title, value, closing date)
          imported before — so a completed-sales file uploaded twice never adds revenue twice
"""
import datetime
import hashlib
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from accounts import capabilities as caps
from accounts.permissions import get_profile, has_capability, visible_user_ids
from core.models import LookupValue


@dataclass
class Field:
    name: str
    label: str
    required: bool = False
    synonyms: list = field(default_factory=list)
    type: str = "text"          # text, email, phone, date, decimal, int, time, lookup:<cat>, employee, customer,
    #                             lead, opportunity, choice, lead_stage, opp_stage
    choices: dict = field(default_factory=dict)   # for type "choice": normalised word -> stored value
    example: str = ""
    help: str = ""
    max_length: int = 255


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


REF = Field("reference", "Reference (your own unique ID)", synonyms=["reference", "ref", "external id", "external ref",
                                                                       "import id", "your id"],
            example="SALES-2025-014", max_length=100,
            help="Optional but recommended. The same reference uploaded again is recognised as the same record.")
OWNER_HELP = ("Employee's CRM username, work email or employee ID. Empty = you, if you are a Sales Engineer or "
              "Coordinator; otherwise required.")
CUSTOMER_HELP = "Customer code (CUS-00001), TRN or email; a company name works only when exactly one customer has it."

KINDS = {
    "customers": {
        "label": "Customers", "create_cap": "customers.create", "assign_cap": "records.assign",
        "fields": [
            Field("company_name", "Company name", True, ["company", "company name", "customer", "client", "client name",
                                                          "name", "organisation", "organization"],
                  example="Demo Gulf Contracting LLC", max_length=200),
            Field("crm_code", "CRM customer code", False, ["crm code", "customer code", "code"], example="",
                  help="Only to update an existing customer (CUS-00001)."),
            Field("category", "Category", False, ["category", "client type", "customer type", "type"],
                  "lookup:customer_category"),
            Field("industry", "Industry", False, ["industry", "sector"], "lookup:industry"),
            Field("status", "Status", False, ["status"], "choice", {"active": "active", "prospect": "prospect",
                                                                     "lead": "prospect", "inactive": "inactive",
                                                                     "on hold": "on_hold"}, "Active"),
            Field("contact_person", "Contact person", False, ["contact", "contact person", "contact name"],
                  example="Mr. A. Example", max_length=150),
            Field("designation", "Designation", False, ["designation", "title", "position", "job title"],
                  max_length=100),
            Field("phone", "Phone", False, ["phone", "mobile", "telephone", "tel", "primary phone"], "phone",
                  example="+971 4 555 0100", max_length=40),
            Field("alt_phone", "Alternative phone", False, ["alternative phone", "alt phone", "phone 2"], "phone",
                  max_length=40),
            Field("email", "Email", False, ["email", "e-mail", "email address"], "email",
                  example="info@example.com"),
            Field("website", "Website", False, ["website", "web", "url"], max_length=200),
            Field("billing_address", "Billing address", False, ["billing address", "address", "invoice address"],
                  max_length=500),
            Field("city", "Emirate / city", False, ["city", "emirate", "location"], example="Dubai", max_length=100),
            Field("country", "Country", False, ["country"], max_length=100),
            Field("trn", "TRN", False, ["trn", "tax registration number", "vat number"], max_length=30),
            Field("source", "Source", False, ["source", "lead source"], "lookup:lead_source"),
            Field("assigned_engineer", "Sales Engineer", False, ["sales engineer", "assigned to", "owner",
                                                                  "salesperson", "employee"], "employee",
                  help="Username, email or employee ID. Empty = not assigned."),
            Field("notes", "Notes", False, ["notes", "remarks", "comments"], max_length=2000),
            REF,
        ],
    },
    "leads": {
        "label": "Sales leads", "create_cap": "leads.create", "assign_cap": "leads.assign",
        "fields": [
            Field("title", "Lead title", True, ["title", "lead title", "lead", "project", "subject", "enquiry"],
                  example="Chiller replacement - Tower A", max_length=200),
            Field("category", "Lead category", True, ["category", "lead category", "lead type", "type"], "choice",
                  {"job in hand": "job_in_hand", "jih": "job_in_hand", "job": "job_in_hand",
                   "tender": "tender", "purchase enquiry": "purchase_enquiry", "purchase inquiry": "purchase_enquiry",
                   "pe": "purchase_enquiry", "enquiry": "purchase_enquiry"}, "Tender",
                  help="Job in Hand, Tender or Purchase Enquiry."),
            Field("company_name", "Company name", True, ["company", "company name", "customer", "client"],
                  example="Demo Gulf Contracting LLC", max_length=200),
            Field("crm_code", "CRM lead code", False, ["crm code", "lead code", "code"],
                  help="Only to update an existing lead (LD-…)."),
            Field("contact_person", "Contact person", False, ["contact", "contact person", "contact name"],
                  max_length=150),
            Field("designation", "Designation", False, ["designation", "position", "job title"], max_length=100),
            Field("email", "Email", False, ["email", "e-mail"], "email"),
            Field("phone", "Phone", False, ["phone", "mobile", "telephone", "tel"], "phone", max_length=40),
            Field("city", "Emirate / city", False, ["city", "emirate", "location"], max_length=100),
            Field("source", "Source", False, ["source", "lead source"], "lookup:lead_source"),
            Field("interest", "Product interest", False, ["product interest", "interest", "service / product interest",
                                                          "service", "product", "requirement"],
                  max_length=255),
            Field("estimated_value", "Estimated value", False, ["value", "estimated value", "potential value",
                                                                 "amount"], "decimal", example="150000"),
            Field("priority", "Priority", False, ["priority"], "choice",
                  {"low": "low", "medium": "medium", "high": "high"}, "Medium"),
            Field("stage", "Stage", False, ["stage", "status", "lead status"], "lead_stage", example="New",
                  help="An open lead stage, e.g. New, Contacted, Qualified. Empty = the first stage. Import "
                       "completed deals as Opportunities."),
            Field("assigned_engineer", "Sales Engineer", False, ["sales engineer", "assigned to", "owner",
                                                                  "assigned", "employee"], "employee",
                  help=OWNER_HELP),
            Field("created_date", "Date received", False, ["date", "created", "created date", "date received",
                                                            "enquiry date"], "date", example="2026-03-15",
                  help="Kept as the lead's real date (not the upload date). Empty = today."),
            Field("next_follow_up", "Next follow-up", False, ["next follow up", "follow up", "follow-up date"],
                  "date"),
            Field("qualification_notes", "Notes", False, ["notes", "remarks", "comments"], max_length=2000),
            REF,
        ],
    },
    "visits": {
        "label": "Customer visits", "create_cap": "visits.create", "assign_cap": "records.assign",
        "fields": [
            Field("customer", "Customer", True, ["customer", "company", "customer code", "client"], "customer",
                  example="CUS-00001", help=CUSTOMER_HELP),
            Field("visit_date", "Visit date", True, ["date", "visit date"], "date", example="2026-03-20"),
            Field("start_time", "Start time", False, ["start", "start time", "time"], "time", example="10:00"),
            Field("end_time", "End time", False, ["end", "end time"], "time", example="11:00"),
            Field("location", "Location", False, ["location", "site", "address"], max_length=255),
            Field("purpose", "Purpose", False, ["purpose", "visit purpose", "type"], "lookup:visit_purpose"),
            Field("status", "Status", False, ["status"], "choice",
                  {"scheduled": "scheduled", "planned": "scheduled", "confirmed": "confirmed",
                   "completed": "completed", "done": "completed", "cancelled": "cancelled",
                   "canceled": "cancelled"}, "Completed",
                  help="Scheduled, Confirmed, Completed or Cancelled. Empty = Completed for past dates, Scheduled "
                       "for future dates."),
            Field("assigned_to", "Employee", False, ["employee", "assigned to", "sales engineer", "owner",
                                                     "visited by"], "employee", help=OWNER_HELP),
            Field("lead", "Lead code", False, ["lead", "lead code"], "lead"),
            Field("opportunity", "Opportunity code", False, ["opportunity", "opportunity code", "deal"],
                  "opportunity"),
            Field("crm_code", "CRM visit code", False, ["crm code", "visit code", "code"]),
            Field("meeting_notes", "Meeting outcome / notes", False, ["notes", "outcome", "meeting notes",
                                                                       "meeting outcome", "minutes"],
                  max_length=4000, help="Required for completed visits."),
            Field("next_follow_up_date", "Next follow-up date", False, ["next follow up", "follow up"], "date"),
            REF,
        ],
    },
    "tasks": {
        "label": "Follow-ups and tasks", "create_cap": "tasks.create", "assign_cap": "records.assign",
        "fields": [
            Field("title", "Title", True, ["title", "task", "follow up", "subject"], example="Call back about offer",
                  max_length=200),
            Field("due_date", "Due date", True, ["due", "due date", "date"], "date", example="2026-03-25"),
            Field("category", "Type", False, ["type", "category"], "choice",
                  {"follow up": "follow_up", "followup": "follow_up", "general": "general",
                   "collection": "collection", "collection follow up": "collection",
                   "documentation": "documentation"}, "Follow-up", help="Empty = Follow-up."),
            Field("priority", "Priority", False, ["priority"], "choice",
                  {"low": "low", "medium": "medium", "high": "high", "urgent": "urgent"}, "Medium"),
            Field("status", "Status", False, ["status"], "choice",
                  {"open": "open", "in progress": "in_progress", "waiting": "waiting", "completed": "completed",
                   "done": "completed", "cancelled": "cancelled", "canceled": "cancelled"}, "Open"),
            Field("completed_date", "Completed date", False, ["completed", "completed date", "done date"], "date",
                  help="For completed tasks; empty = the due date."),
            Field("assigned_to", "Employee", False, ["employee", "assigned to", "owner"], "employee",
                  help=OWNER_HELP),
            Field("customer", "Customer", False, ["customer", "company", "customer code"], "customer",
                  help=CUSTOMER_HELP),
            Field("lead", "Lead code", False, ["lead", "lead code"], "lead"),
            Field("crm_code", "CRM task code", False, ["crm code", "task code", "code"]),
            Field("description", "Description", False, ["description", "notes", "details"], max_length=4000),
            REF,
        ],
    },
    "opportunities": {
        "label": "Opportunities and completed sales", "create_cap": "pipeline.edit", "assign_cap": "records.assign",
        "fields": [
            Field("title", "Deal title", True, ["title", "deal", "opportunity", "project", "description"],
                  example="Supply of chilled water valves", max_length=200),
            Field("customer", "Customer", True, ["customer", "company", "customer code", "client"], "customer",
                  example="CUS-00001", help=CUSTOMER_HELP),
            Field("stage", "Status / stage", True, ["status", "stage", "deal status", "result"], "opp_stage",
                  example="Won", help="Won (completed sale), Lost, or an open stage such as Negotiation. Rows "
                                      "without a status are rejected: an amount alone never makes a sale."),
            Field("estimated_value", "Deal value", True, ["value", "amount", "sales value", "deal value",
                                                          "estimated value", "total"], "decimal",
                  example="250000"),
            Field("closed_date", "Closing date", False, ["closing date", "closed date", "close date", "won date",
                                                         "date"], "date",
                  help="Required for Won and Lost: the real closing date (revenue is reported on it)."),
            Field("expected_close_date", "Expected closing date", False, ["expected close", "expected closing date"],
                  "date"),
            Field("lost_reason", "Lost reason", False, ["lost reason", "reason"], "lookup:lost_reason",
                  help="Required for Lost."),
            Field("assigned_engineer", "Sales Engineer", False, ["sales engineer", "employee", "owner",
                                                                  "salesperson", "assigned to"], "employee",
                  help=OWNER_HELP),
            Field("probability", "Probability %", False, ["probability", "probability %"], "int",
                  help="Open deals only; empty = the stage's default."),
            Field("source", "Source", False, ["source"], "lookup:lead_source"),
            Field("crm_code", "CRM opportunity code", False, ["crm code", "opportunity code", "code"]),
            Field("notes", "Notes", False, ["notes", "remarks"], max_length=2000),
            REF,
        ],
    },
}

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%d/%m/%y", "%Y/%m/%d")


def parse_date(raw):
    raw = str(raw).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?", raw):  # Excel date cells
        raw = raw[:10]
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError


def parse_time(raw):
    raw = str(raw).strip()
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})(?::\d{2})?\s*([ap]m)?", raw, re.I)
    if not m:
        raise ValueError
    h, mi = int(m.group(1)), int(m.group(2))
    if m.group(3):
        h = h % 12 + (12 if m.group(3).lower() == "pm" else 0)
    return datetime.time(h, mi)


class Context:
    """Who is importing and what they may do; caches look-ups for one file."""

    def __init__(self, user, kind):
        self.user, self.kind, self.spec = user, kind, KINDS[kind]
        self.full = has_capability(user, "data.import") and has_capability(user, self.spec["assign_cap"])
        self.allowed = visible_user_ids(user) if self.full else {user.pk}
        profile = get_profile(user)
        self.default_owner = user if profile and profile.role.code in (caps.ENGINEER, caps.COORDINATOR) else None
        self._lookups = {}

    def lookup(self, category, value):
        key = (category, value.strip().lower())
        if key not in self._lookups:
            self._lookups[key] = LookupValue.objects.filter(category=category, value__iexact=value.strip()).first()
        return self._lookups[key]


def employee_for(value):
    User = get_user_model()
    v = value.strip()
    base = User.objects.filter(is_active=True, profile__isnull=False)
    return (base.filter(username__iexact=v).first() or base.filter(email__iexact=v).first()
            or base.filter(profile__employee_id__iexact=v).first())


def customer_for(value):
    from customers.models import Customer, normalize_name

    v = value.strip()
    c = Customer.objects.filter(code__iexact=v).first() or Customer.objects.filter(trn=v.replace(" ", "")).first() \
        if v else None
    if c is None and "@" in v:
        c = Customer.objects.filter(email__iexact=v).first()
    if c is None and v:
        matches = list(Customer.objects.filter(normalized_name=normalize_name(v), is_archived=False)[:2])
        if len(matches) == 1:
            return matches[0], "matched by company name"
        if len(matches) > 1:
            return None, f"'{v}' matches several customers — use the customer code"
    return c, ""


def read_cell(f, raw, ctx):
    """(value, error) for one cell; empty → (None, None)."""
    from leads.models import Lead, LeadStage
    from sales.models import Opportunity, OpportunityStage

    raw = "" if raw is None else str(raw).strip()
    if raw == "":
        return None, None
    if len(raw) > f.max_length:
        return None, f"{f.label} is longer than {f.max_length} characters"
    t = f.type
    try:
        if t == "text":
            return raw, None
        if t == "email":
            validate_email(raw)
            return raw.lower(), None
        if t == "phone":
            digits = re.sub(r"\D", "", raw)
            if not re.fullmatch(r"[\d\s+()\-./]+", raw) or not 6 <= len(digits) <= 15:
                return None, f"'{raw}' is not a valid phone number"
            return raw, None
        if t == "date":
            return parse_date(raw), None
        if t == "time":
            return parse_time(raw), None
        if t == "decimal":
            v = Decimal(re.sub(r"[^\d.\-]", "", raw.replace(",", "")) or "x")
            if v < 0 or v > Decimal("999999999999"):
                raise InvalidOperation
            return v.quantize(Decimal("0.01")), None
        if t == "int":
            v = int(Decimal(raw.replace("%", "").strip()))
            if not 0 <= v <= 100:
                raise ValueError
            return v, None
        if t == "choice":
            v = f.choices.get(norm(raw))
            if v is None:
                return None, f"'{raw}' is not a valid {f.label.lower()} (use " + ", ".join(
                    sorted({k.title() for k in f.choices})) + ")"
            return v, None
        if t.startswith("lookup:"):
            obj = ctx.lookup(t.split(":", 1)[1], raw)
            if obj is None:
                return None, f"'{raw}' is not in the {f.label.lower()} list (Settings > Drop-down lists)"
            return obj, None
        if t == "employee":
            u = employee_for(raw)
            if u is None:
                return None, f"No active employee with username, email or employee ID '{raw}'"
            if ctx.allowed is not None and u.pk not in ctx.allowed:
                return None, f"You are not allowed to import records for {u.get_full_name() or u.username}"
            return u, None
        if t == "customer":
            c, note = customer_for(raw)
            if c is None:
                return None, note or f"No customer found for '{raw}'"
            return (c, note), None
        if t == "lead":
            obj = Lead.objects.filter(code__iexact=raw).first()
            return (obj, None) if obj else (None, f"No lead with code '{raw}'")
        if t == "opportunity":
            obj = Opportunity.objects.filter(code__iexact=raw).first()
            return (obj, None) if obj else (None, f"No opportunity with code '{raw}'")
        if t == "lead_stage":
            st = LeadStage.objects.filter(name__iexact=raw, is_active=True).first()
            if st is None:
                return None, f"'{raw}' is not a lead stage"
            if st.is_won or st.is_lost:
                return None, "Won / Lost leads cannot be imported here; import completed deals as Opportunities"
            return st, None
        if t == "opp_stage":
            word = norm(raw)
            if word in ("won", "closed won", "completed", "complete", "sold", "closed"):
                return OpportunityStage.objects.get(is_won=True), None
            if word in ("lost", "closed lost", "cancelled", "canceled"):
                return OpportunityStage.objects.get(is_lost=True), None
            st = OpportunityStage.objects.filter(name__iexact=raw, is_active=True).first()
            if st is None:
                return None, f"'{raw}' is not a deal status (use Won, Lost or a stage name)"
            return st, None
    except (ValueError, InvalidOperation, ValidationError):
        pass
    hint = {"date": " (use YYYY-MM-DD or DD/MM/YYYY)", "time": " (use HH:MM)", "decimal": " (numbers only)",
            "int": " (0 to 100)", "email": ""}.get(t, "")
    return None, f"'{raw}' is not a valid {f.label.lower()}{hint}"


def fingerprint(kind, *parts):
    text = "|".join(norm(p) if not isinstance(p, (datetime.date, Decimal)) else str(p) for p in parts)
    return "auto:" + hashlib.sha256(f"{kind}|{text}".encode()).hexdigest()[:40]


def ref_key(data):
    return f"ref:{norm(data['reference'])}" if data.get("reference") else None
