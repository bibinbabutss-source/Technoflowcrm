"""Regression tests for the bugs found in the Phase 2 browser audit."""
import pytest
from django.test import Client
from django.urls import reverse

from accounts import capabilities as caps
from accounts.models import Role
from core.models import LookupValue, NumberSequence
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("url", [
    "/accounts/users/?role=abc", "/audit-log/?user=abc", "/audit-log/?date_from=2026-13-45",
    "/audit-log/?date_to=yesterday", "/audit-log/?action=bogus", "/accounts/users/login-history/?event=x",
])
def test_bad_filter_values_do_not_crash(admin_user, login, url):
    assert login(admin_user).get(url).status_code == 200


def test_numbering_cannot_restart_yearly_without_year(admin_user, login):
    seq = NumberSequence.objects.get(code="customer")
    response = login(admin_user).post(reverse("core:numbering_edit", args=[seq.pk]),
                                      {"prefix": "CUS", "padding": 5, "reset_yearly": "on"})
    assert response.status_code == 200
    assert b"same number would be issued again" in response.content
    seq.refresh_from_db()
    assert seq.reset_yearly is False


def test_lookup_blank_order_accepted_and_blank_value_explained(admin_user, login):
    client = login(admin_user)
    client.post(reverse("core:lookups"), {"category": "lead_source", "value": "Cold   Call", "sort_order": ""})
    assert LookupValue.objects.filter(category="lead_source", value="Cold Call", sort_order=0).exists()
    response = client.post(reverse("core:lookups"), {"category": "lead_source", "value": "   "})
    assert b"Please correct" in response.content or b"required" in response.content


def test_hidden_department_kept_when_employee_edited(make_user, admin_user, login):
    user = make_user(caps.ENGINEER, department="Sales")
    LookupValue.objects.filter(category="department", value="Sales").update(is_active=False)
    client = login(admin_user)
    p = user.profile
    response = client.post(reverse("accounts:user_edit", args=[p.pk]), {
        "first_name": user.first_name, "last_name": user.last_name, "email": user.email,
        "employee_id": p.employee_id, "role": p.role.pk, "department": "Sales", "job_title": "Engineer II",
    })
    assert response.status_code == 302
    p.refresh_from_db()
    assert p.department == "Sales" and p.job_title == "Engineer II"


def test_reporting_loop_refused(make_user, admin_user, login):
    a = make_user(caps.ENGINEER)
    b = make_user(caps.COORDINATOR)
    b.profile.reporting_manager = a.profile
    b.profile.save()
    client = login(admin_user)
    pa = a.profile
    response = client.post(reverse("accounts:user_edit", args=[pa.pk]), {
        "first_name": a.first_name, "last_name": a.last_name, "email": a.email, "employee_id": pa.employee_id,
        "role": pa.role.pk, "reporting_manager": b.profile.pk,
    })
    assert b"reporting loop" in response.content


def test_admin_cannot_reset_own_password_from_user_page(admin_user, login):
    client = login(admin_user)
    client.post(reverse("accounts:user_reset_password", args=[admin_user.profile.pk]),
                {"temporary_password": "Another-Temp-Pass-9"})
    admin_user.refresh_from_db()
    assert admin_user.check_password(PASSWORD)
    assert client.get(reverse("core:dashboard")).status_code == 200  # still signed in


def test_lockout_is_per_user_and_address_and_admin_can_unlock(make_user, admin_user, login, settings):
    victim = make_user(caps.ENGINEER)
    colleague = make_user(caps.COORDINATOR)
    office = Client()
    for _ in range(settings.AXES_FAILURE_LIMIT):
        office.post(reverse("accounts:login"), {"username": victim.username, "password": "wrong"})
    assert office.post(reverse("accounts:login"),
                       {"username": victim.username, "password": PASSWORD}).status_code == 429
    # a colleague on the same office connection is not locked out
    assert office.post(reverse("accounts:login"),
                       {"username": colleague.username, "password": PASSWORD}).status_code == 302
    admin = login(admin_user)
    page = admin.get(reverse("accounts:user_detail", args=[victim.profile.pk]))
    assert b"Unlock sign-in" in page.content
    admin.post(reverse("accounts:user_unlock", args=[victim.profile.pk]))
    assert Client().post(reverse("accounts:login"),
                         {"username": victim.username, "password": PASSWORD}).status_code == 302


def test_my_profile_without_employee_profile_does_not_crash(db):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create_user("tech", "tech@example.com", PASSWORD)
    client = Client()
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    assert client.get(reverse("accounts:my_profile")).status_code == 403


def test_unlock_requires_admin(make_user, login):
    eng = make_user(caps.ENGINEER)
    assert login(eng).post(reverse("accounts:user_unlock", args=[eng.profile.pk])).status_code == 403
    assert Role.objects.get(code=caps.ENGINEER)  # sanity
