import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts import capabilities as caps
from accounts.models import AccountLimitError, EmployeeProfile, Role
from accounts.services import activate_employee, deactivate_employee, update_employee

pytestmark = pytest.mark.django_db


def test_default_roles_and_limits():
    limits = {r.code: r.max_accounts for r in Role.objects.all()}
    assert limits == {caps.ADMIN: 1, caps.DIRECTOR: 2, caps.ACCOUNTS: 2, caps.ENGINEER: 2, caps.COORDINATOR: 3}
    assert sum(limits.values()) == 10


def test_third_sales_engineer_is_refused(make_user):
    make_user(caps.ENGINEER)
    make_user(caps.ENGINEER)
    with pytest.raises(AccountLimitError):
        make_user(caps.ENGINEER)
    assert EmployeeProfile.objects.filter(role__code=caps.ENGINEER).count() == 2


def test_only_one_system_administrator(admin_user, make_user):
    with pytest.raises(AccountLimitError):
        make_user(caps.ADMIN)


def test_limit_enforced_on_direct_model_save(make_user):
    """Even code that bypasses the service layer cannot exceed the limit."""
    make_user(caps.DIRECTOR)
    make_user(caps.DIRECTOR)
    engineer = make_user(caps.ENGINEER)
    profile = engineer.profile
    profile.role = Role.objects.get(code=caps.DIRECTOR)
    with pytest.raises(AccountLimitError):
        profile.save()


def test_deactivated_account_frees_a_place(make_user, admin_user):
    a = make_user(caps.ENGINEER)
    make_user(caps.ENGINEER)
    deactivate_employee(a.profile, by_user=admin_user)
    make_user(caps.ENGINEER)  # allowed now
    with pytest.raises(AccountLimitError):
        activate_employee(a.profile)  # role is full again


def test_reactivation_through_user_save_is_also_checked(make_user, admin_user):
    a = make_user(caps.ENGINEER)
    make_user(caps.ENGINEER)
    deactivate_employee(a.profile, by_user=admin_user)
    make_user(caps.ENGINEER)
    a.refresh_from_db()
    a.is_active = True
    with pytest.raises(AccountLimitError):
        a.save()


def test_moving_user_into_full_role_is_refused(make_user):
    make_user(caps.ACCOUNTS)
    make_user(caps.ACCOUNTS)
    coord = make_user(caps.COORDINATOR)
    with pytest.raises(AccountLimitError):
        update_employee(coord.profile, role=Role.objects.get(code=caps.ACCOUNTS))


def test_admin_can_raise_limit(make_user):
    make_user(caps.ENGINEER)
    make_user(caps.ENGINEER)
    role = Role.objects.get(code=caps.ENGINEER)
    role.max_accounts = 3
    role.save()
    make_user(caps.ENGINEER)
    assert role.active_count() == 3


def test_limit_cannot_be_lowered_below_active_accounts(make_user):
    make_user(caps.COORDINATOR)
    make_user(caps.COORDINATOR)
    role = Role.objects.get(code=caps.COORDINATOR)
    role.max_accounts = 1
    with pytest.raises(ValidationError):
        role.full_clean()


def test_last_admin_cannot_be_deactivated_or_moved(admin_user, make_user):
    director = make_user(caps.DIRECTOR)
    with pytest.raises(ValidationError):
        deactivate_employee(admin_user.profile, by_user=director)
    with pytest.raises(ValidationError):
        update_employee(admin_user.profile, role=Role.objects.get(code=caps.DIRECTOR))


def test_user_cannot_deactivate_self(admin_user):
    with pytest.raises(ValidationError):
        deactivate_employee(admin_user.profile, by_user=admin_user)


def test_deactivation_keeps_history(make_user, admin_user):
    user = make_user(caps.ENGINEER)
    deactivate_employee(user.profile, by_user=admin_user)
    user.refresh_from_db()
    assert user.is_active is False
    assert EmployeeProfile.objects.filter(user=user).exists()


def test_create_user_over_limit_through_web_form_shows_error(make_user, admin_user, login):
    make_user(caps.ENGINEER)
    make_user(caps.ENGINEER)
    client = login(admin_user)
    response = client.post(reverse("accounts:user_create"), {
        "first_name": "New", "last_name": "Engineer", "username": "new.eng", "email": "new.eng@example.com",
        "employee_id": "T-9999", "role": Role.objects.get(code=caps.ENGINEER).pk,
        "temporary_password": "Strong-Test-Pass-91",
    })
    assert response.status_code == 200
    assert b"which is its limit" in response.content
    assert not EmployeeProfile.objects.filter(employee_id="T-9999").exists()


def test_admin_creates_user_through_web_form(admin_user, login):
    client = login(admin_user)
    response = client.post(reverse("accounts:user_create"), {
        "first_name": "Sara", "last_name": "Coordinator", "username": "sara.c", "email": "Sara.C@Example.com",
        "employee_id": "t-0500", "role": Role.objects.get(code=caps.COORDINATOR).pk,
        "temporary_password": "Strong-Test-Pass-91",
    })
    assert response.status_code == 302
    profile = EmployeeProfile.objects.get(employee_id="T-0500")
    assert profile.user.email == "sara.c@example.com"
    assert profile.must_change_password is True
