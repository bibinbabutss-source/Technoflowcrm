"""First-run defaults. Created only if missing; never overwrites Administrator edits."""
from django.db import transaction

from .models import TaxRate, CompanyProfile, LookupValue, NumberSequence

SEQUENCES = [
    # code, name, prefix, include_year, padding
    ("customer", "Customer", "CUS", False, 5),
    ("lead", "Lead", "LD", True, 4),
    ("opportunity", "Opportunity", "OPP", True, 4),
    ("project", "Project", "PRJ", True, 4),
    ("visit", "Customer visit", "VIS", True, 4),
    ("quotation", "Quotation", "QT", True, 4),
    ("order", "Sales order", "SO", True, 4),
    ("invoice", "Invoice", "INV", True, 4),
    ("payment", "Payment receipt", "RCT", True, 4),
    ("task", "Task", "TSK", True, 5),
    ("communication", "Communication", "COM", True, 5),
]

LOOKUPS = {
    "customer_category": ["Building Owner", "Developer", "Consultant", "Main Contractor", "MEP Contractor",
                          "Facility Management", "End User", "Government"],
    "industry": ["Real Estate", "Construction", "MEP Contracting", "Consultancy", "Hospitality", "Healthcare",
                 "Industrial", "Data Centres", "Retail", "Government"],
    "lead_source": ["Direct Visit", "Referral", "Partnership", "Website", "Phone Enquiry", "Email Enquiry",
                    "Exhibition", "Tender"],
    "project_type": ["New Build", "Retrofit", "Fit-out", "Maintenance"],
    "visit_purpose": ["Initial Meeting", "Technical Discussion", "Project Briefing", "Site Survey",
                      "Proposal Presentation", "Technical Coordination", "Progress Review", "Partnership Meeting"],
    "lost_reason": ["Price", "Lost to competitor", "Project cancelled", "Budget not approved", "Timeline",
                    "Specification mismatch", "No response"],
    "department": ["Management", "Sales", "Accounts", "Administration"],
    "document_category": ["Drawing", "Specification", "Proposal", "Purchase Order", "Contract", "Invoice",
                          "Correspondence", "Photo", "Other"],
}


@transaction.atomic
def seed_defaults():
    CompanyProfile.get()
    for code, name, prefix, include_year, padding in SEQUENCES:
        NumberSequence.objects.get_or_create(
            code=code, defaults={"name": name, "prefix": prefix, "include_year": include_year,
                                 "reset_yearly": include_year, "padding": padding},
        )
    if not TaxRate.objects.exists():
        TaxRate.objects.create(name="VAT", rate=5, is_default=True, sort_order=0)
        TaxRate.objects.create(name="Zero-rated", rate=0, sort_order=1)
        TaxRate.objects.create(name="Exempt", rate=0, sort_order=2)
    if not LookupValue.objects.exists():
        for category, values in LOOKUPS.items():
            for order, value in enumerate(values):
                LookupValue.objects.create(category=category, value=value, sort_order=order)
