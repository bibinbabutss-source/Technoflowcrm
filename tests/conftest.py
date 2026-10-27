import itertools

import pytest
from django.test import Client

from accounts import capabilities as caps
from accounts.models import Role
from accounts.services import create_employee

PASSWORD = "Strong-Test-Pass-91"
_counter = itertools.count(1)


@pytest.fixture
def make_user(db):
    def _make(role_code, *, must_change=False, **extra):
        n = next(_counter)
        user = create_employee(
            username=extra.pop("username", f"user{n}"), email=f"user{n}@example.com",
            first_name=extra.pop("first_name", "Test"), last_name=f"User{n}",
            employee_id=f"T-{n:04d}", role=Role.objects.get(code=role_code), temporary_password=PASSWORD,
            **extra,
        )
        user.profile.must_change_password = must_change
        user.profile.save()
        return user

    return _make


@pytest.fixture
def admin_user(make_user):
    return make_user(caps.ADMIN)


@pytest.fixture
def login():
    def _login(user):
        client = Client()
        client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
        return client

    return _login
