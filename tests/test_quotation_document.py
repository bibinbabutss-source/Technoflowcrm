"""Quotation document: editable sections, PDF / Word output in the Technoflow format, logo, permissions."""
import io
import json
from decimal import Decimal
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from django.contrib.staticfiles import finders
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from accounts import capabilities as caps
from core.models import TaxRate
from customers.models import Customer
from quotations import services
from quotations.document import amount_in_words, number_to_words
from quotations.models import Quotation, QuotationLine, QuotationTemplate, QuotationTerm

from .webforms import form_fields, page

pytestmark = pytest.mark.django_db
SAMPLE_ITEMS = Path(__file__).with_name("data") / "sample_quotation_items.json"


def pdf_text(response):
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(response.content)).pages)
    return " ".join(text.split())  # line wraps do not matter for these checks


@pytest.fixture
def setup(make_user, login):
    eng = make_user(caps.ENGINEER, first_name="Bijin")
    director = make_user(caps.DIRECTOR)
    cust = Customer.objects.create(company_name="Gulf Test Contracting WLL", assigned_engineer=eng,
                                   billing_address="P.O. Box 4763", city="Abu Dhabi", contact_person="Mr. Test Buyer")
    return {"eng": eng, "director": director, "cust": cust, "e": login(eng), "d": login(director)}


def _create(c, cust, extra=None):
    url = reverse("quotations:create") + f"?customer={cust.pk}"
    html = page(c, url).content.decode()
    _, data = form_fields(html)
    vat = TaxRate.default().pk
    data.update({
        "q-customer": str(cust.pk), "q-currency": "AED",
        "r-subject": "CHILLED WATER VALVES", "r-project_name": "Project - DOI-25074", "r-consultant": "MINISTRY",
        "r-attention": "Mr. Mohammed Test", "r-manufacturer": "TFL VALVES", "r-sales_in_charge_name": "FABISH CP",
        "r-signatory_name": "A. Manager", "r-signatory_designation": "Asst. Sales Manager",
        "r-letter_body": "Dear Sir / Madam,\n\nWe are pleased to submit our **offer**.",
        "lines-TOTAL_FORMS": "2", "lines-INITIAL_FORMS": "0",
        "lines-0-part_no": "GVBR20", "lines-0-description": "20mm BRONZE GATE VALVE PN20 FOR FCUS",
        "lines-0-quantity": "914", "lines-0-unit": "Nos", "lines-0-unit_price": "39.10", "lines-0-discount_pct": "0",
        "lines-0-tax_rate": str(vat),
        "lines-1-part_no": "STBR20", "lines-1-description": "25mm BRONZE Y-STRAINER PN20 FOR FCUS",
        "lines-1-quantity": "51", "lines-1-unit": "Nos", "lines-1-unit_price": "37.61", "lines-1-discount_pct": "0",
        "lines-1-tax_rate": str(vat),
    })
    data.update(extra or {})
    return c.post(url, data)


def test_create_with_all_sections_and_template_terms(setup):
    r = _create(setup["e"], setup["cust"], {"terms-0-heading": "PRICES", "terms-0-content": "Are in UAE Dirhams only"})
    assert r.status_code == 302
    q = Quotation.objects.get()
    rev = q.current
    assert rev.subject == "CHILLED WATER VALVES" and rev.consultant == "MINISTRY" and rev.manufacturer == "TFL VALVES"
    assert list(rev.lines.values_list("part_no", flat=True)) == ["GVBR20", "STBR20"]
    # totals calculated by the server: 35,737.40 + 1,918.11 = 37,655.51, VAT 5% = 1,882.78
    assert rev.subtotal == Decimal("37655.51") and rev.tax_amount == Decimal("1882.78")
    assert rev.grand_total == Decimal("39538.29")
    # the default terms from Settings > Quotation template were saved, including the edited first row
    terms = list(rev.terms.values_list("heading", "content"))
    assert len(terms) == len(QuotationTemplate.get().default_terms)
    assert terms[0] == ("PRICES", "Are in UAE Dirhams only")


def test_edit_add_remove_lines_and_terms_then_pdf_shows_latest(setup):
    e = setup["e"]
    _create(e, setup["cust"])
    q = Quotation.objects.get()
    rev = q.current
    url = reverse("quotations:edit", args=[q.pk])
    html = page(e, url).content.decode()
    soup = BeautifulSoup(html, "lxml")
    assert soup.find("input", {"name": "r-subject"})["value"] == "CHILLED WATER VALVES"  # reopened draft keeps edits
    _, data = form_fields(html)
    first_line, second_line = rev.lines.order_by("position")
    first_term = rev.terms.order_by("position").first()
    n_terms = int(data["terms-TOTAL_FORMS"])
    data.update({
        "r-subject": "CHILLED WATER VALVES - REVISED SCOPE", "r-consultant": "NEW CONSULTANT LLC",
        "lines-1-DELETE": "on",                                       # remove a line
        "lines-TOTAL_FORMS": "3",                                     # add a line
        "lines-2-part_no": "BFX16S-L", "lines-2-description": "65mm BFLY VALVE DI BODY LUGGED",
        "lines-2-quantity": "76", "lines-2-unit": "Nos", "lines-2-unit_price": "199.75", "lines-2-discount_pct": "10",
        "lines-2-tax_rate": str(TaxRate.default().pk),
        "terms-0-DELETE": "on",                                       # remove a term
        "terms-TOTAL_FORMS": str(n_terms + 1),                        # add a term
        f"terms-{n_terms}-heading": "SPECIAL CONDITION", f"terms-{n_terms}-content": "Delivery to **site B** only.",
        "then": "preview",
    })
    r = e.post(url, data)
    assert r.status_code == 302 and r["Location"] == reverse("quotations:preview", args=[q.pk])
    rev.refresh_from_db()
    assert rev.lines.count() == 2 and not rev.lines.filter(pk=second_line.pk).exists()
    assert rev.lines.filter(part_no="BFX16S-L", discount_pct=10).exists()
    # 35,737.40 + 76 × 199.75 × 0.9 = 35,737.40 + 13,662.90 = 49,400.30; VAT 2,470.02
    assert rev.subtotal == Decimal("49400.30") and rev.grand_total == Decimal("51870.32")
    assert not rev.terms.filter(pk=first_term.pk).exists()
    assert rev.terms.order_by("-position").first().heading == "SPECIAL CONDITION"
    # preview page and PDF reflect the saved edits
    assert b"<iframe" in page(e, reverse("quotations:preview", args=[q.pk])).content
    r = page(e, reverse("quotations:pdf", args=[q.pk]) + "?download=1")
    assert r["Content-Type"] == "application/pdf" and r["Content-Disposition"].startswith("attachment")
    text = pdf_text(r)
    for expected in ("CHILLED WATER VALVES - REVISED SCOPE", "NEW CONSULTANT LLC", "BFX16S-L", "13,662.90",
                     "51,870.32", "FIFTY ONE THOUSAND EIGHT HUNDRED SEVENTY DIRHAMS AND THIRTY TWO FILS ONLY",
                     "SPECIAL CONDITION", "Gulf Test Contracting WLL", "Mr. Mohammed Test", "PRICE SCHEDULE",
                     "COMMERCIAL TERMS AND CONDITIONS", "Revision Number", "DRAFT", "TFL VALVES", "FABISH CP"):
        assert expected in text, expected
    assert "STBR20" not in text  # removed line is gone
    # inline (preview) version may be framed by our own pages only
    r = page(e, reverse("quotations:pdf", args=[q.pk]))
    assert r["Content-Disposition"].startswith("inline") and r["X-Frame-Options"] == "SAMEORIGIN"


def test_multi_page_quotation_matches_sample_totals(setup):
    """The 103 lines of Technoflow's sample quotation (zero-rated) give the sample's total and words."""
    eng = setup["eng"]
    items = json.loads(SAMPLE_ITEMS.read_text())
    q, rev = services.create_quotation(customer=setup["cust"], opportunity=None, salesperson=eng, currency="AED",
                                       user=eng)
    zero = TaxRate.objects.get(name="Zero-rated")
    for it in items:
        QuotationLine.objects.create(revision=rev, position=it["n"], part_no=it["part"], description=it["desc"],
                                     quantity=Decimal(it["qty"]), unit_price=Decimal(it["price"]), tax_rate=zero)
    services.recalculate(rev)
    rev.refresh_from_db()
    assert rev.grand_total == Decimal("795493.14")
    r = page(setup["e"], reverse("quotations:pdf", args=[q.pk]))
    reader = PdfReader(io.BytesIO(r.content))
    assert len(reader.pages) >= 9  # cover + price schedule pages + terms
    text = pdf_text(r)
    assert "795,493.14" in text
    assert "SEVEN HUNDRED NINETY FIVE THOUSAND FOUR HUNDRED NINETY THREE DIRHAMS AND FOURTEEN FILS ONLY" in text
    for it in items:  # every line total printed, none lost at page breaks
        assert f"{Decimal(it['total']):,.2f}" in text, it["n"]
    assert text.count("PRICE SCHEDULE") >= 7  # heading repeats on every schedule page
    assert "SUB TOTAL" not in text  # no VAT and no discount: single TOTAL AMOUNT line, as in the sample


def test_long_description_and_terms_flow_across_pages(setup):
    eng = setup["eng"]
    q, rev = services.create_quotation(customer=setup["cust"], opportunity=None, salesperson=eng, currency="AED",
                                       user=eng)
    long_desc = " ".join(f"WORD{i:04d}" for i in range(1500))
    QuotationLine.objects.create(revision=rev, position=1, description=long_desc, quantity=1, unit_price=10,
                                 tax_rate=TaxRate.default())
    QuotationTerm.objects.create(revision=rev, position=99, heading="LONG TERM",
                                 content=" ".join(f"TERM{i:04d}" for i in range(1500)))
    services.recalculate(rev)
    text = pdf_text(page(setup["e"], reverse("quotations:pdf", args=[q.pk])))
    assert "WORD0000" in text and "WORD1499" in text and "TERM1499" in text


def test_word_export(setup):
    from docx import Document

    _create(setup["e"], setup["cust"])
    q = Quotation.objects.get()
    r = page(setup["e"], reverse("quotations:docx", args=[q.pk]))
    assert r["Content-Disposition"].endswith('.docx"')
    doc = Document(io.BytesIO(r.content))
    body = "\n".join(p.text for p in doc.paragraphs)
    cells = "\n".join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert "PRICE SCHEDULE" in body and "COMMERCIAL TERMS AND CONDITIONS" in body
    assert "GVBR20" in cells and "39,538.29" in cells and "PAYMENT TERMS" in cells
    assert doc.sections[0].header.paragraphs[0].runs[0]._element.xpath(".//pic:pic")  # logo in the header


def test_revise_copies_document_terms_and_part_numbers(setup):
    _create(setup["e"], setup["cust"])
    q = Quotation.objects.get()
    rev = q.current
    services.submit(rev, setup["eng"])
    rev.refresh_from_db()
    services.approve(rev, setup["director"])
    # locked: terms of a submitted/approved revision cannot be changed
    with pytest.raises(Exception):
        QuotationTerm.objects.create(revision=rev, heading="X", content="Y")
    new = services.revise(q, setup["eng"], "Customer request")
    assert new.subject == rev.subject and new.manufacturer == "TFL VALVES"
    assert list(new.terms.values_list("heading", flat=True)) == list(rev.terms.values_list("heading", flat=True))
    assert list(new.lines.values_list("part_no", flat=True)) == ["GVBR20", "STBR20"]
    text = pdf_text(page(setup["e"], reverse("quotations:pdf", args=[q.pk])))
    assert "Revision Number 1" in text


def test_older_quotation_without_document_fields_still_prints(setup):
    eng = setup["eng"]
    q, rev = services.create_quotation(customer=setup["cust"], opportunity=None, salesperson=eng, currency="AED",
                                       user=eng, with_template=False)
    rev.payment_terms = "30 days from invoice date"
    rev.warranty_terms = "12 months"
    rev.save()
    QuotationLine.objects.create(revision=rev, description="Item", quantity=1, unit_price=100,
                                 tax_rate=TaxRate.default())
    services.recalculate(rev)
    text = pdf_text(page(setup["e"], reverse("quotations:pdf", args=[q.pk])))
    for expected in ("Gulf Test Contracting WLL", "P.O. Box 4763", "Mr. Test Buyer", "PAYMENT TERMS",
                     "30 days from invoice date", "WARRANTY", "Dear Sir / Madam"):
        assert expected in text, expected


def test_permissions(setup, make_user, login):
    _create(setup["e"], setup["cust"])
    q = Quotation.objects.get()
    other_eng = login(make_user(caps.ENGINEER))
    accounts = login(make_user(caps.ACCOUNTS))
    for name in ("quotations:pdf", "quotations:docx", "quotations:preview"):
        assert other_eng.get(reverse(name, args=[q.pk])).status_code == 404  # not their customer
        assert accounts.get(reverse(name, args=[q.pk])).status_code == 403   # no quotations.view
    assert setup["e"].get(reverse("quotations:template")).status_code == 403
    admin = login(make_user(caps.ADMIN))
    assert admin.get(reverse("quotations:template")).status_code == 200
    # the approved revision can no longer be edited through the page
    rev = q.current
    services.submit(rev, setup["eng"])
    assert setup["e"].get(reverse("quotations:edit", args=[q.pk])).status_code == 403


def test_template_settings_change_defaults_for_new_quotations(setup, make_user, login):
    admin = login(make_user(caps.ADMIN))
    url = reverse("quotations:template")
    _, data = form_fields(page(admin, url).content.decode())
    n = int(data["terms-TOTAL_FORMS"])
    data.update({"letterhead_tagline": "AN ISO 9001:2015 COMPANY", "schedule_note": "NOTE : PRICES EXCLUDE VAT",
                 "terms-TOTAL_FORMS": str(n + 1), f"terms-{n}-heading": "GUARANTEE",
                 f"terms-{n}-content": "As per manufacturer.", "terms-1-DELETE": "on"})
    assert admin.post(url, data).status_code == 302
    tpl = QuotationTemplate.get()
    assert tpl.schedule_note == "NOTE : PRICES EXCLUDE VAT"
    assert tpl.default_terms[-1] == ["GUARANTEE", "As per manufacturer."] and len(tpl.default_terms) == n
    q, rev = services.create_quotation(customer=setup["cust"], opportunity=None, salesperson=setup["eng"],
                                       currency="AED", user=setup["eng"])
    assert rev.schedule_note == "NOTE : PRICES EXCLUDE VAT" and rev.terms.last().heading == "GUARANTEE"


def test_logo_is_the_uploaded_file_everywhere(setup, client):
    full, web = finders.find("img/technoflow-logo-full.png"), finders.find("img/technoflow-logo.png")
    from PIL import Image

    for path in (full, web):
        with Image.open(path) as im:
            assert abs(im.width / im.height - 2.445) < 0.02  # aspect ratio of the supplied logo kept
    assert b"img/technoflow-logo.png" in client.get(reverse("accounts:login")).content
    assert b"img/technoflow-logo.png" in setup["e"].get(reverse("core:dashboard")).content
    _create(setup["e"], setup["cust"])
    q = Quotation.objects.get()
    reader = PdfReader(io.BytesIO(page(setup["e"], reverse("quotations:pdf", args=[q.pk])).content))
    assert all(page_.images for page_ in reader.pages)  # logo printed on every page


def test_amount_in_words():
    assert number_to_words(0) == "ZERO"
    assert number_to_words(1015) == "ONE THOUSAND FIFTEEN"
    assert amount_in_words(Decimal("795493.14"), "AED") == (
        "SEVEN HUNDRED NINETY FIVE THOUSAND FOUR HUNDRED NINETY THREE DIRHAMS AND FOURTEEN FILS ONLY")
    assert amount_in_words(Decimal("1000000"), "USD") == "ONE MILLION US DOLLARS ONLY"
    assert amount_in_words(timezone.now().year, "XYZ").endswith("XYZ ONLY")
