from datetime import date
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts import capabilities as caps
from accounts.models import Role
from accounts.services import update_employee
from core.models import AuditLog, CompanyProfile, LookupValue, NumberSequence

pytestmark = pytest.mark.django_db


def test_number_sequence_increments_and_formats():
    assert NumberSequence.next_value("quotation").endswith("-0001")
    second = NumberSequence.next_value("quotation")
    assert second.startswith("QT-") and second.endswith("-0002")
    assert NumberSequence.next_value("customer") == "CUS-00001"


def test_number_sequence_restarts_each_year():
    with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 12, 31)):
        assert NumberSequence.next_value("invoice") == "INV-2026-0001"
        assert NumberSequence.next_value("invoice") == "INV-2026-0002"
    with mock.patch("django.utils.timezone.localdate", return_value=date(2027, 1, 1)):
        assert NumberSequence.next_value("invoice") == "INV-2027-0001"


def test_audit_log_is_append_only(admin_user):
    entry = AuditLog.objects.first()
    entry.message = "tampered"
    with pytest.raises(ValidationError):
        entry.save()
    with pytest.raises(ValidationError):
        entry.delete()


def test_role_change_is_audited_without_password(make_user, admin_user):
    user = make_user(caps.COORDINATOR)
    update_employee(user.profile, role=Role.objects.get(code=caps.DIRECTOR))
    entry = AuditLog.objects.filter(action="permission").latest("id")
    assert entry.changes["role"] == ["Sales Coordinator", "Sales Director"]
    assert not AuditLog.objects.filter(changes__has_key="password").exists()


def test_company_settings_saved_by_admin_and_audited(admin_user, login):
    client = login(admin_user)
    data = {
        "company_name": "Technoflow Trading LLC", "legal_name": "Technoflow Trading LLC",
        "tax_registration_number": "100000000000003", "address": "", "city": "Dubai",
        "country": "United Arab Emirates", "phone": "", "email": "", "website": "https://technoflow.com/",
        "default_currency": "aed", "fiscal_year_start_month": 1, "quotation_validity_days": 45,
        "default_payment_terms_days": 30, "max_upload_mb": 20, "allowed_upload_extensions": "pdf, XLSX ,png",
    }
    assert client.post(reverse("core:settings_home"), data).status_code == 302
    company = CompanyProfile.get()
    assert company.default_currency == "AED"
    assert company.quotation_validity_days == 45
    assert company.extension_list == ["pdf", "xlsx", "png"]
    assert AuditLog.objects.filter(action="update", object_repr=company.company_name).exists()


def test_dangerous_upload_types_refused(admin_user, login):
    client = login(admin_user)
    response = client.post(reverse("core:settings_home"), {
        "company_name": "Technoflow Trading LLC", "default_currency": "AED", "fiscal_year_start_month": 1,
        "quotation_validity_days": 30, "default_payment_terms_days": 30, "max_upload_mb": 20,
        "allowed_upload_extensions": "pdf,exe",
    })
    assert response.status_code == 200
    assert b"not allowed for security reasons" in response.content


def test_lookup_value_added_and_hidden_not_deleted(admin_user, login):
    client = login(admin_user)
    client.post(reverse("core:lookups"), {"category": "lead_source", "value": "LinkedIn",
                                          "sort_order": 9, "is_active": "on"})
    value = LookupValue.objects.get(category="lead_source", value="LinkedIn")
    client.post(reverse("core:lookup_toggle", args=[value.pk]))
    value.refresh_from_db()
    assert value.is_active is False
    # duplicate refused
    response = client.post(reverse("core:lookups"), {"category": "lead_source", "value": "linkedin",
                                                     "sort_order": 1, "is_active": "on"})
    assert b"already exists" in response.content


def test_audit_csv_export_neutralises_formulas(admin_user, login):
    from core.audit import log_action

    log_action("other", message="=HYPERLINK(\"http://evil\")", user=admin_user)
    response = login(admin_user).get(reverse("core:audit_log") + "?export=csv")
    assert response.status_code == 200
    assert b"'=HYPERLINK" in response.content


def test_dashboard_shows_real_role_counts(admin_user, make_user, login):
    make_user(caps.ENGINEER)
    page = login(admin_user).get(reverse("core:dashboard")).content.decode()
    assert "Accounts by role" in page
    assert "Active accounts" in page


def test_production_settings_refuse_weak_secret(monkeypatch):
    import importlib

    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.setenv("DEBUG", "False")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost/db")
    import config.settings.base as base

    importlib.reload(base)
    with pytest.raises(ImproperlyConfigured):
        import config.settings.prod as prod

        importlib.reload(prod)
