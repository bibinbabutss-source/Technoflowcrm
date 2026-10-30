"""
Checks that the project is ready to deploy. Run them on your laptop before
pushing to GitHub:  python -m pytest tests/test_deployment.py
"""
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client, RequestFactory, override_settings

from accounts import capabilities as caps
from accounts.models import EmployeeProfile, LoginHistory
from core.middleware import get_client_ip

ROOT = Path(__file__).resolve().parent.parent

RENDER_ENV = {
    "SECRET_KEY": "x" * 50,
    "DEBUG": "False",
    "DATABASE_URL": "postgresql://technoflow:pw@dpg-example-a/technoflow_crm",
    "RENDER_EXTERNAL_HOSTNAME": "technoflow-crm.onrender.com",
    "ADMIN_URL": "control+7421/==",
}


def _load_prod(monkeypatch, **overrides):
    for key, value in {**RENDER_ENV, **overrides}.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    import config.settings.base as base

    importlib.reload(base)
    import config.settings.prod as prod

    return importlib.reload(prod)


@pytest.fixture(autouse=True)
def _restore_base_settings():
    yield
    import config.settings.base as base

    importlib.reload(base)


# ---------------------------------------------------------------- settings
def test_production_settings_on_render(monkeypatch):
    prod = _load_prod(monkeypatch)
    assert prod.DEBUG is False
    assert "technoflow-crm.onrender.com" in prod.ALLOWED_HOSTS
    assert "https://technoflow-crm.onrender.com" in prod.CSRF_TRUSTED_ORIGINS
    assert prod.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql"
    assert prod.DATABASES["default"]["CONN_HEALTH_CHECKS"] is True
    assert prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE
    assert prod.STORAGES["staticfiles"]["BACKEND"].startswith("whitenoise.")
    assert prod.MIDDLEWARE[0] == "core.middleware.HealthCheckMiddleware"
    assert "whitenoise.middleware.WhiteNoiseMiddleware" in prod.MIDDLEWARE
    assert prod.ADMIN_URL == "control7421"  # unsafe URL characters removed


@pytest.mark.parametrize("override,message", [
    ({"DEBUG": "True"}, "DEBUG"),
    ({"SECRET_KEY": "short"}, "SECRET_KEY"),
    ({"DATABASE_URL": "sqlite:///db.sqlite3"}, "PostgreSQL"),
    ({"RENDER_EXTERNAL_HOSTNAME": None, "ALLOWED_HOSTS": ""}, "ALLOWED_HOSTS"),
])
def test_production_refuses_unsafe_settings(monkeypatch, override, message):
    from django.core.exceptions import ImproperlyConfigured

    with pytest.raises(ImproperlyConfigured, match=message):
        _load_prod(monkeypatch, **override)


# ---------------------------------------------------------------- health check
def test_health_check_ignores_unknown_host():
    """Render's checker sends Host: localhost:10000, which is not in ALLOWED_HOSTS."""
    with override_settings(ALLOWED_HOSTS=["technoflow-crm.onrender.com"]):
        response = Client(HTTP_HOST="localhost:10000").get("/healthz/")
    assert response.status_code == 200
    assert response.content == b"ok"


# ---------------------------------------------------------------- client IP
@pytest.mark.parametrize("forwarded,expected", [
    ("203.0.113.7, 10.0.0.1", "203.0.113.7"),
    ("not-an-ip, 198.51.100.4", "198.51.100.4"),
    ("garbage", "10.1.1.1"),
    ("", "10.1.1.1"),
])
def test_client_ip_is_always_a_valid_address(forwarded, expected):
    request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR=forwarded, REMOTE_ADDR="10.1.1.1")
    with override_settings(TRUST_X_FORWARDED_FOR=True):
        assert get_client_ip(request) == expected


@pytest.mark.django_db
def test_forged_forwarded_header_cannot_break_login(make_user):
    from tests.conftest import PASSWORD

    user = make_user(caps.ENGINEER)
    with override_settings(TRUST_X_FORWARDED_FOR=True):
        response = Client().post("/accounts/login/", {"username": user.username, "password": PASSWORD},
                                 HTTP_X_FORWARDED_FOR="<script>")
    assert response.status_code == 302
    assert LoginHistory.objects.filter(user=user, event="login").exists()


# ---------------------------------------------------------------- demo users
@pytest.mark.django_db
def test_demo_users_skip_full_admin_role_and_can_skip_password_change(admin_user, monkeypatch, settings):
    settings.DEBUG = False
    monkeypatch.setenv("DEMO_USERS_PASSWORD", "Shared-Demo-Pass-55")
    call_command("load_demo_users", "--password-env", "DEMO_USERS_PASSWORD",
                 "--allow-production", "--no-password-change")
    created = set(EmployeeProfile.objects.filter(employee_id__startswith="DEMO-")
                  .values_list("user__username", flat=True))
    assert created == {"demo.director", "demo.accounts", "demo.engineer", "demo.coordinator", "demo.owner"}
    assert not EmployeeProfile.objects.filter(employee_id__startswith="DEMO-", must_change_password=True).exists()
    # running again (next deploy) changes nothing
    call_command("load_demo_users", "--password-env", "DEMO_USERS_PASSWORD",
                 "--allow-production", "--no-password-change")
    assert EmployeeProfile.objects.filter(employee_id__startswith="DEMO-").count() == 5


@pytest.mark.django_db
def test_demo_users_refused_in_production_without_flag(settings):
    from django.core.management.base import CommandError

    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("load_demo_users", "--password", "Shared-Demo-Pass-55")


# ---------------------------------------------------------------- repository hygiene
def test_build_script_uses_linux_line_endings():
    assert b"\r\n" not in (ROOT / "build.sh").read_bytes()


def test_secrets_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text()
    for pattern in (".env", "db.sqlite3", "staticfiles/", "media/private/*"):
        assert pattern in ignored


def test_no_real_secrets_in_committed_files():
    """Fails if a real-looking secret value is written into any project file."""
    pattern = re.compile(r"^(SECRET_KEY|ADMIN_TEMP_PASSWORD|EMAIL_HOST_PASSWORD|DEMO_USERS_PASSWORD)=(.+)$",
                         re.MULTILINE)
    skip_dirs = {".venv", "venv", ".git", "staticfiles", "__pycache__", ".pytest_cache", "node_modules"}
    offenders = []
    for path in ROOT.rglob("*"):
        if path.is_dir() or skip_dirs & set(path.parts) or path.name == ".env":
            continue
        if path.suffix not in {".py", ".yaml", ".yml", ".sh", ".txt", ".md", ".example", ".cfg", ".ini", ".toml"}:
            continue
        for match in pattern.finditer(path.read_text(errors="ignore")):
            offenders.append(f"{path.relative_to(ROOT)}: {match.group(1)}")
    assert offenders == []


def test_render_blueprint_keeps_secrets_out_of_git():
    blueprint = (ROOT / "render.yaml").read_text()
    for key in ("ADMIN_TEMP_PASSWORD", "REMOVE_DEMO_DATA", "ADMIN_USERNAME", "ADMIN_URL"):
        block = blueprint.split(f"key: {key}")[1].split("- key:")[0]
        assert "sync: false" in block, key
    assert "generateValue: true" in blueprint.split("key: SECRET_KEY")[1].split("- key:")[0]
    # a deploy never creates demo data any more
    assert "LOAD_DEMO_DATA" not in blueprint and "DEMO_USERS_PASSWORD" not in blueprint
    build = (ROOT / "build.sh").read_text()
    assert "load_demo_data" not in build.replace("Use load_demo_users / load_demo_data only", "")
    assert "load_demo_users --" not in build


def test_migrations_are_complete():
    """Every model change has a migration file, so Render's 'migrate' builds the full database."""
    result = subprocess.run(
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
        cwd=ROOT, capture_output=True, text=True,
        env={**__import__("os").environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
