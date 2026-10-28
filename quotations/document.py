"""
Everything needed to print a quotation (PDF and Word) in the Technoflow format:
cover letter → price schedule → commercial terms and conditions.

All values come from the saved revision. Empty document fields fall back to the customer, the
opportunity, the salesperson and the company quotation template, so older quotations still print fully.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from django.utils.html import escape
from django.utils.safestring import mark_safe

# Default commercial terms for new quotations (Settings > Quotation template can change them).
DEFAULT_TERMS = [
    ("PRICES", "Are in UAE Dirhams"),
    ("PRICE TERMS", "The Offered prices are valid for this BOQ without split order. Complete order need to place "
                    "in a single shot on or before 2026 or else PO will not be accepted.\n\n"
                    "**Prices validity may vary due to below reasons.**\n"
                    "1. Fluctuations in Raw Material Costs\n2. Currency Exchange Rate Changes\n"
                    "3. Supply Chain Disruptions\n4. Transportation and Freight Costs"),
    ("POINT OF DELIVERY", "To Site."),
    ("PAYMENT TERMS", "**10% Advance and Balance 60 days LC.**\n\nLC Charges will be beared mutually.\n\n"
                      "In-case any payment issues, payment terms of 60 days LC will be changed to our flexible "
                      "payment terms.\n\nLC documents need to be release for collection after 1 week from date of "
                      "delivery.\n\n“Prices are excluding Vat”"),
    ("CANCELLATION", "20 % after order placement, 50% if castings are under manufacture, 80% if the material is "
                     "under assembly and 100% if the material is ready for dispatch."),
    ("DELIVERY LEAD TIME", "Standard delivery lead time of 10-12 Weeks from date of LPO and Delivery request with "
                           "additional transit time. (Based on current situation)\n\nDetailed delivery schedule need "
                           "to be shared against the LPO.\n\nMaterials kept against for the Project need to be "
                           "collected by contractor in 1-2 weeks.\n\nProduction will start as per the schedule from "
                           "site team."),
    ("STORAGE", "Storage of the valves should be as per manufacture standard. Damage due to the wrong storage at "
                "site will not born any responsibilities with supplier."),
    ("OUR SCOPE", "Our scope is supply of valves site. Additional site visit will be based on additional cost of "
                  "AED 2,000/Visit."),
    ("PAYMENT DEFAULTING TERMS", "The terms mentioned will be valid till the completion of the final payment.\n\n"
                                 "Client/Customer LPO payment agreed day’s terms shall be mutually adhered."),
    ("VARIATIONS", "Any variations in original BOQ quantities shall be submitted as variation and related work "
                   "shall be executed inline to the Client / Project requirement."),
    ("FORCE MAJURE", "Cover natural disasters or other \"Acts of God\", war, or the failure of third parties-- such "
                     "as suppliers and subcontractors-- to perform their obligations to the contracting party.\n\n"
                     "**If any surcharge applicable due to a force majeure event shall claim extra**"),
    ("LIQUIDATED DAMAGES", "Not applicable."),
    ("WARRANTY", "**2 Years from TOC date.**\n\nWarranty will cease to exist in case of the following. Extended "
                 "warranty can be arranged at an additional charge agreed between the parties."),
    ("QUOTE VALIDITY", "**10 days**"),
]

CURRENCY_NAMES = {
    "AED": ("United Arab Emirates Dirham", "DIRHAMS", "FILS"),
    "USD": ("US Dollar", "US DOLLARS", "CENTS"),
    "EUR": ("Euro", "EUROS", "CENTS"),
    "GBP": ("British Pound", "POUNDS", "PENCE"),
    "SAR": ("Saudi Riyal", "SAUDI RIYALS", "HALALAS"),
    "QAR": ("Qatari Riyal", "QATARI RIYALS", "DIRHAMS"),
    "OMR": ("Omani Rial", "OMANI RIALS", "BAISA"),
    "KWD": ("Kuwaiti Dinar", "KUWAITI DINARS", "FILS"),
    "BHD": ("Bahraini Dinar", "BAHRAINI DINARS", "FILS"),
    "INR": ("Indian Rupee", "RUPEES", "PAISE"),
}

_ONES = ["", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE",
         "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
_TENS = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]


def _under_thousand(n):
    words = []
    if n >= 100:
        words += [_ONES[n // 100], "HUNDRED"]
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10])
        n %= 10
    if n:
        words.append(_ONES[n])
    return words


def number_to_words(n):
    n = int(n)
    if n == 0:
        return "ZERO"
    words = []
    for value, name in ((10 ** 12, "TRILLION"), (10 ** 9, "BILLION"), (10 ** 6, "MILLION"), (1000, "THOUSAND")):
        if n >= value:
            words += _under_thousand(n // value) + [name]
            n %= value
    words += _under_thousand(n)
    return " ".join(words)


def currency_full_name(code):
    return CURRENCY_NAMES.get((code or "").upper(), (code or "",))[0]


def amount_in_words(amount, currency):
    """795493.14, AED -> 'SEVEN HUNDRED NINETY FIVE THOUSAND ... DIRHAMS AND FOURTEEN FILS ONLY'"""
    amount = Decimal(amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, fraction = int(amount), int((amount - int(amount)) * 100)
    _, major, minor = CURRENCY_NAMES.get((currency or "").upper(), ("", (currency or "").upper(), "CENTS"))
    text = f"{number_to_words(whole)} {major}"
    if fraction:
        text += f" AND {number_to_words(fraction)} {minor}"
    return text + " ONLY"


def rich_text(value):
    """Plain text -> safe HTML: paragraphs on blank lines, line breaks kept, **bold** supported."""
    if not value:
        return ""
    html = escape(value)
    html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html, flags=re.S)
    paragraphs = [p.strip("\n") for p in re.split(r"\n\s*\n", html) if p.strip()]
    return mark_safe("".join(f"<p>{p.replace(chr(10), '<br/>')}</p>" for p in paragraphs))


def legacy_terms(rev):
    """Terms rows for revisions saved before the terms table existed (built from the older fields)."""
    rows = []
    for heading, value in (("PAYMENT TERMS", rev.payment_terms), ("DELIVERY", rev.delivery_terms),
                           ("WARRANTY", rev.warranty_terms), ("QUOTE VALIDITY", rev.validity)):
        if value and value.strip():
            rows.append((heading, value))
    return rows


def terms_for(rev):
    rows = [(t.heading, t.content) for t in rev.terms.all()] or legacy_terms(rev)
    extra = []
    if rev.scope_of_work.strip():
        extra.append(("SCOPE OF WORK", rev.scope_of_work))
    if rev.exclusions.strip():
        extra.append(("EXCLUSIONS", rev.exclusions))
    if rev.customer_notes.strip():
        extra.append(("NOTES", rev.customer_notes))
    return rows + extra


def customer_address(customer):
    parts = [customer.billing_address or customer.office_address or ""]
    if customer.city and customer.city.lower() not in parts[0].lower():
        parts.append(customer.city)
    return "\n".join(p for p in parts if p.strip())


def build(q, rev):
    """Context for templates/quotations/pdf.html and the Word export."""
    from core.models import CompanyProfile

    from .models import QuotationTemplate

    tpl = QuotationTemplate.get()
    company = CompanyProfile.get()
    customer = q.customer
    lines = list(rev.lines.select_related("tax_rate"))
    salesperson = q.salesperson.get_full_name() or q.salesperson.username if q.salesperson_id else ""
    tax_rows = {}
    for ln in lines:
        tax_rows.setdefault(ln.tax_rate_value, Decimal(0))
        tax_rows[ln.tax_rate_value] += ln.line_tax
    has_discount = any(ln.discount_pct for ln in lines)
    doc = {
        "number": q.number,
        "revision_number": rev.version - 1,  # the first issue is revision 0, as on Technoflow's quotations
        "date": rev.quotation_date,
        "expiry_date": rev.expiry_date,
        "currency": rev.currency,
        "currency_name": currency_full_name(rev.currency),
        "customer_name": rev.customer_name or customer.company_name,
        "customer_address": rev.customer_address or customer_address(customer),
        "attention": rev.attention or customer.contact_person,
        "subject": rev.subject or (q.opportunity.title.upper() if q.opportunity_id else ""),
        "project": rev.project_name or (q.opportunity.title if q.opportunity_id else ""),
        "consultant": rev.consultant,
        "letter_body": rev.letter_body or tpl.letter_body,
        "letter_closing": rev.letter_closing or tpl.letter_closing,
        "signatory_name": rev.signatory_name,
        "signatory_designation": rev.signatory_designation or tpl.signatory_designation,
        "signature_label": tpl.signature_label,
        "manufacturer": rev.manufacturer,
        "schedule_note": rev.schedule_note or tpl.schedule_note,
        "sales_engineer": rev.sales_engineer_name or salesperson,
        "sales_in_charge": rev.sales_in_charge_name,
        "approved_by": rev.approved_by_name,
        "lines": lines,
        "show_discount": has_discount,
        "show_unit": tpl.show_unit,
        "subtotal": rev.subtotal,
        "header_discount": rev.header_discount,
        "taxable": rev.taxable_amount,
        "tax_rows": sorted(((r, t) for r, t in tax_rows.items() if t), key=lambda x: x[0]),
        "tax_amount": rev.tax_amount,
        "grand_total": rev.grand_total,
        "simple_total": not rev.header_discount and not rev.tax_amount,
        "amount_words": amount_in_words(rev.grand_total, rev.currency),
        "terms": terms_for(rev),
        "is_draft": rev.status in ("draft", "submitted", "rejected"),
        "legal_name": company.legal_name or company.company_name,
        "trn": company.tax_registration_number,
        "tagline": tpl.letterhead_tagline,
        "arabic_name": tpl.arabic_name,
        "footer_tagline": tpl.footer_tagline,
        "footer_website": tpl.footer_website,
        "footer_business_lines": tpl.footer_business_lines,
        "footer_contact": tpl.footer_contact,
    }
    return doc


def filename(q, rev):
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", q.number).strip("-")
    return f"{safe}-Rev{rev.version - 1}"
