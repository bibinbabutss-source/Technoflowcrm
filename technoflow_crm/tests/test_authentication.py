import pytest
from django.test import Client
from django.urls import reverse

from accounts import capabilities as caps
from accounts.models import LoginHistory
from core.models import AuditLog
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


def test_login_page_shows_branding():
    response = Client().get(reverse("accounts:login"))
    assert response.status_code == 200
    assert b"technoflow-logo.png" in response.content
    assert b"Technoflow Trading LLC" in response.content


def test_unauthenticated_user_redirected_to_login():
    response = Client().get(reverse("core:dashboard"))
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_successful_login_records_history_and_audit(make_user):
    user = make_user(caps.ENGINEER)
    client = Client()
    response = client.post(reverse("accounts:login"), {"username": user.username, "password": PASSWORD})
    assert response.status_code == 302
    assert LoginHistory.objects.filter(user=user, event="login").exists()
    assert AuditLog.objects.filter(user=user, action="login").exists()


def test_wrong_password_rejected_and_logged(make_user):
    user = make_user(caps.ENGINEER)
    response = Client().post(reverse("accounts:login"), {"username": user.username, "password": "wrong-password"})
    assert response.status_code == 200
    assert b"correct username and password" in response.content
    assert LoginHistory.objects.filter(username=user.username, event="failed").exists()


def test_account_locks_after_repeated_failures(make_user, settings):
    user = make_user(caps.ENGINEER)
    client = Client()
    for _ in range(settings.AXES_FAILURE_LIMIT):
        client.post(reverse("accounts:login"), {"username": user.username, "password": "wrong"})
    # Even the correct password is refused while locked
    response = client.post(reverse("accounts:login"), {"username": user.username, "password": PASSWORD})
    assert response.status_code == 429
    assert b"Too many failed sign-in attempts" in response.content


def test_deactivated_user_cannot_login(make_user, admin_user):
    from accounts.services import deactivate_employee

    user = make_user(caps.ENGINEER)
    deactivate_employee(user.profile, by_user=admin_user)
    response = Client().post(reverse("accounts:login"), {"username": user.username, "password": PASSWORD})
    assert response.status_code == 200  # form re-shown with error
    assert "_auth_user_id" not in Client().session


def test_password_is_hashed_not_plain_text(make_user):
    user = make_user(caps.ENGINEER)
    user.refresh_from_db()
    assert PASSWORD not in user.password
    assert user.password.startswith(("pbkdf2_", "argon2", "md5$", "bcrypt"))


def test_temporary_password_forces_change(make_user, login):
    user = make_user(caps.ENGINEER, must_change=True)
    client = login(user)
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 302 and response.url == reverse("accounts:password_change")

    response = client.post(reverse("accounts:password_change"), {
        "old_password": PASSWORD, "new_password1": "Another-Strong-77x", "new_password2": "Another-Strong-77x"})
    assert response.status_code == 302
    user.profile.refresh_from_db()
    assert user.profile.must_change_password is False
    assert client.get(reverse("core:dashboard")).status_code == 200


def test_logout_requires_post(make_user, login):
    client = login(make_user(caps.ENGINEER))
    assert client.get(reverse("accounts:logout")).status_code == 405
    assert client.post(reverse("accounts:logout")).status_code == 302
    assert client.get(reverse("core:dashboard")).status_code == 302


def test_password_reset_email_sent_only_for_known_active_email(make_user, mailoutbox):
    user = make_user(caps.ENGINEER)
    Client().post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})
    assert len(mailoutbox) == 0
    Client().post(reverse("accounts:password_reset"), {"email": user.email})
    assert len(mailoutbox) == 1
    assert "password/reset/" in mailoutbox[0].body


def test_user_without_employee_profile_cannot_sign_in(db):
    from django.contrib.auth import get_user_model

    get_user_model().objects.create_user("noprofile", "np@example.com", PASSWORD)
    response = Client().post(reverse("accounts:login"), {"username": "noprofile", "password": PASSWORD})
    assert response.status_code == 200
    assert b"not linked to an employee profile" in response.content
