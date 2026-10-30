"""
End-to-end business workflow through the real web pages (forms rendered by the CRM are parsed and posted,
as a browser would):

Lead → qualification → conversion (customer + opportunity) → quotation with lines → submit → Director
approval → sent → accepted → sales order → milestones → confirmation → invoices → partial and full
payment → reversal → statement / collections → dashboard and report figures.
"""
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts import capabilities as caps
from customers.models import Customer
from invoicing.models import Invoice, Payment
from leads.models import Lead, LeadStage
from orders.models import SalesOrder
from quotations.models import Quotation
from reporting import metrics
from sales.models import Opportunity

from .webforms import page, select_value, submit

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(make_user, login):
    director = make_user(caps.DIRECTOR)
    accounts = make_user(caps.ACCOUNTS)
    engineer = make_user(caps.ENGINEER)
    return {"director": director, "accounts": accounts, "engineer": engineer,
            "d": login(director), "a": login(accounts), "e": login(engineer)}


def test_full_sales_to_cash_workflow(team):
    e, d, a = team["e"], team["d"], team["a"]
    today = timezone.localdate()

    # 1. Engineer creates a lead (owner defaults to themselves)
    submit(e, reverse("leads:create"), {"category": "tender", "title": "Chiller replacement", "company_name": "Workflow Test Trading LLC",
                                        "contact_person": "Test Buyer", "email": "buyer@example.com",
                                        "phone": "+971 50 000 0001", "estimated_value": "100000"})
    lead = Lead.objects.get(title="Chiller replacement")
    assert lead.assigned_engineer == team["engineer"]

    # 2. Qualify and convert into a new customer + opportunity
    qualified = LeadStage.objects.filter(is_qualified=True, is_won=False).first()
    r = e.post(reverse("leads:stage", args=[lead.pk]), {"stage": qualified.pk})
    assert r.status_code == 302
    submit(e, reverse("leads:convert", args=[lead.pk]), {"mode": "new", "create_opportunity": "on",
                                                         "opp_title": "Chiller replacement", "opp_value": "100000",
                                                         "opp_probability": "40"})
    lead.refresh_from_db()
    assert lead.is_converted
    customer = Customer.objects.get(company_name="Workflow Test Trading LLC")
    opp = Opportunity.objects.get(lead=lead)
    assert opp.customer == customer

    # 3. Quotation with two lines (one discounted), 5% VAT
    url = reverse("quotations:create") + f"?opportunity={opp.pk}"
    html = page(e, url).content.decode()
    vat = select_value(html, "lines-0-tax_rate", "VAT")
    submit(e, url, {
        "lines-TOTAL_FORMS": "2",
        "lines-0-description": "Chiller 200 TR", "lines-0-quantity": "1", "lines-0-unit": "nos",
        "lines-0-unit_price": "80000", "lines-0-discount_pct": "0", "lines-0-tax_rate": vat,
        "lines-1-description": "Installation", "lines-1-quantity": "1", "lines-1-unit": "lot",
        "lines-1-unit_price": "20000", "lines-1-discount_pct": "10", "lines-1-tax_rate": vat,
    })
    q = Quotation.objects.get(opportunity=opp)
    rev = q.revisions.get(version=1)
    assert rev.subtotal == Decimal("98000.00")  # line nets after line discounts
    assert rev.discount_total == Decimal("2000.00")  # total discount given (10% on 20,000)
    assert rev.taxable_amount == Decimal("98000.00")  # 80,000 + 18,000
    assert rev.tax_amount == Decimal("4900.00")
    assert rev.grand_total == Decimal("102900.00")

    # 4. Submit; the engineer cannot approve their own quotation; the Director approves
    assert e.post(reverse("quotations:submit", args=[q.pk])).status_code == 302
    q.refresh_from_db()
    assert q.status == "submitted"
    e.post(reverse("quotations:decide", args=[q.pk]), {"decision": "approve"})
    q.refresh_from_db()
    assert q.status == "submitted", "self-approval must be impossible"
    d.post(reverse("quotations:decide", args=[q.pk]), {"decision": "approve", "comments": "OK"})
    q.refresh_from_db()
    assert q.status == "approved"
    # locked: financial edits are refused once approved
    r = e.get(reverse("quotations:edit", args=[q.pk]))
    assert r.status_code in (302, 403)

    # 5. PDF, sent, accepted
    r = e.get(reverse("quotations:pdf", args=[q.pk]))
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
    assert e.post(reverse("quotations:send", args=[q.pk])).status_code == 302
    r = e.post(reverse("quotations:accept", args=[q.pk]), {"date": today.isoformat(),
                                                          "accepted_by_name": "Test Buyer",
                                                          "customer_reference": "PO-123"})
    assert r.status_code == 302
    q.refresh_from_db()
    assert q.status == "accepted"

    # 6. Sales order with 30/70 milestones; engineer cannot confirm, Director can
    submit(e, reverse("orders:create_from_quotation", args=[q.pk]), {"milestones": "30-70"})
    order = SalesOrder.objects.get(quotation=q)
    assert order.status == "draft"
    assert order.net_amount == Decimal("98000.00") and order.total_amount == Decimal("102900.00")
    assert [m.percentage for m in order.milestones.order_by("sequence")] == [Decimal(30), Decimal(70)]
    r = e.post(reverse("orders:confirm", args=[order.pk]))
    order.refresh_from_db()
    assert order.status == "draft"
    d.post(reverse("orders:confirm", args=[order.pk]))
    order.refresh_from_db()
    assert order.status == "confirmed"
    opp.refresh_from_db()
    assert opp.stage.is_won

    # 7. Accounts invoices both milestones; amounts add up exactly to the order total
    m1, m2 = order.milestones.order_by("sequence")
    assert a.post(reverse("invoicing:create_from_milestone", args=[m1.pk])).status_code == 302
    inv1 = Invoice.objects.get(milestone=m1)
    assert inv1.total == Decimal("30870.00")
    assert a.post(reverse("invoicing:issue", args=[inv1.pk])).status_code == 302
    a.post(reverse("invoicing:create_from_milestone", args=[m2.pk]))
    inv2 = Invoice.objects.get(milestone=m2)
    a.post(reverse("invoicing:issue", args=[inv2.pk]))
    inv1.refresh_from_db(); inv2.refresh_from_db()
    assert inv1.number and inv2.number and inv1.number != inv2.number
    assert inv1.total + inv2.total == order.total_amount
    # the same milestone cannot be invoiced twice
    a.post(reverse("invoicing:create_from_milestone", args=[m1.pk]))
    assert Invoice.objects.filter(milestone=m1).exclude(status="cancelled").count() == 1

    # 8. Partial payment, then the balance with an over-payment kept as credit
    r = a.post(reverse("invoicing:payment_create"), {
        "customer": customer.pk, "payment_date": today.isoformat(), "amount": "10000", "method": "bank",
        "reference": "TRF-1", f"alloc_{inv1.pk}": "10000"})
    assert r.status_code == 302, r.content[:500]
    inv1.refresh_from_db()
    assert inv1.status == "partially_paid" and inv1.outstanding == Decimal("20870.00")
    r = a.post(reverse("invoicing:payment_create"), {
        "customer": customer.pk, "payment_date": today.isoformat(), "amount": "21000", "method": "bank",
        "reference": "TRF-2", f"alloc_{inv1.pk}": "20870"})
    assert r.status_code == 302
    inv1.refresh_from_db()
    assert inv1.status == "paid" and inv1.outstanding == 0
    p2 = Payment.objects.get(reference="TRF-2")
    assert p2.unallocated == Decimal("130.00")

    # over-allocation is refused
    before = Payment.objects.count()
    a.post(reverse("invoicing:payment_create"), {
        "customer": customer.pk, "payment_date": today.isoformat(), "amount": "999999", "method": "bank",
        "reference": "TRF-X", f"alloc_{inv2.pk}": "999999"})
    assert Payment.objects.count() == before

    # 9. Reversal (never delete): the invoice goes back to partially paid
    r = a.post(reverse("invoicing:payment_detail", args=[p2.pk]), {"action": "reverse",
                                                                    "reason": "Cheque bounced"})
    assert r.status_code == 302
    inv1.refresh_from_db()
    assert inv1.status == "partially_paid" and inv1.outstanding == Decimal("20870.00")
    assert Payment.objects.filter(reverses=p2, is_reversal=True).exists()

    # 10. Statement, collections, dashboard and reports agree
    for url in (reverse("invoicing:statement", args=[customer.pk]), reverse("invoicing:collections"),
                reverse("core:dashboard"), reverse("reporting:index")):
        page(a, url)
    f = metrics.dashboard_figures(team["director"], today.replace(month=1, day=1), today)
    assert f["orders_value"] == Decimal("98000.00")
    assert f["invoiced"] == Decimal("102900.00")
    assert f["collected"] == Decimal("10000.00")  # 10,000 + 21,000 − 21,000 reversed
    assert f["outstanding"] == Decimal("92900.00")
    r = d.get(reverse("reporting:report", args=["confirmed_orders"]))
    assert r.status_code == 200 and order.number in r.content.decode()
    for fmt, ctype in (("xlsx", "spreadsheetml"), ("csv", "text/csv"), ("pdf", "application/pdf")):
        r = d.get(reverse("reporting:report", args=["confirmed_orders"]) + f"?export={fmt}")
        assert r.status_code == 200 and ctype in r["Content-Type"], fmt
