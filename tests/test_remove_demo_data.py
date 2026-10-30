"""remove_demo_data: preview changes nothing; --confirm removes only demo records, keeps real ones."""
import io

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from customers.models import Customer
from invoicing.models import Invoice, Payment
from leads.models import Lead, LeadStage
from quotations.models import Quotation
from core.models import AuditLog, NumberSequence

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv("DEMO_PW_TEST", "Demo-Test-Pass-2026")
    call_command("load_demo_users", "--password-env", "DEMO_PW_TEST", "--allow-production", stdout=io.StringIO())
    call_command("load_demo_data", "--allow-production", stdout=io.StringIO())
    eng = get_user_model().objects.get(username="demo.engineer")
    real_cust = Customer.objects.create(company_name="Real Customer LLC", code="CUS-88001")
    real_lead = Lead.objects.create(title="Real enquiry", company_name="Real Prospect LLC",
                                    stage=LeadStage.first_open(), assigned_engineer=eng)
    return real_cust, real_lead


def run(*args):
    out = io.StringIO()
    call_command("remove_demo_data", *args, stdout=out)
    return out.getvalue()


def test_preview_changes_nothing(demo):
    before = (Customer.objects.count(), Payment.objects.count(), Invoice.objects.count())
    out = run()
    assert "Preview only" in out and "Customers" in out
    assert (Customer.objects.count(), Payment.objects.count(), Invoice.objects.count()) == before
    assert get_user_model().objects.filter(username__startswith="demo.", is_active=True).exists()


def test_confirm_removes_demo_keeps_real(demo):
    real_cust, real_lead = demo
    assert Payment.objects.exists() and Quotation.objects.exists()
    out = run("--confirm")
    assert "Demo data removed" in out
    assert list(Customer.objects.all()) == [real_cust]
    assert list(Lead.objects.all()) == [real_lead]
    assert not Payment.objects.exists() and not Invoice.objects.exists() and not Quotation.objects.exists()
    assert not get_user_model().objects.filter(username__startswith="demo.", is_active=True).exists()
    assert get_user_model().objects.filter(username__startswith="demo.").exists()  # deactivated, not deleted
    assert NumberSequence.objects.get(code="quotation").preview().endswith("-0001")
    assert NumberSequence.objects.get(code="customer").last_number > 0  # real customers left: not reset
    assert AuditLog.objects.filter(message__startswith="Demo data removed").count() == 1
    assert "nothing to do" in run("--confirm")


def test_no_demo_data_is_a_safe_no_op(db):
    Customer.objects.create(company_name="Only Real LLC", code="CUS-88002")
    assert "nothing to do" in run("--confirm")
    assert Customer.objects.count() == 1
