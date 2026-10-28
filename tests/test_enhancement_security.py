"""Security checks for the enhancement: password handling, CSRF, access to the new pages, no data leaks."""
import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts import capabilities as caps
from core.models import AuditLog
from tests.conftest import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(make_user, login):
    admin, eng, acc = make_user(caps.ADMIN), make_user(caps.ENGINEER), make_user(caps.ACCOUNTS)
    return {"admin": admin, "eng": eng, "acc": acc, "a": login(admin), "e": login(eng), "x": login(acc)}


def test_reset_link_is_emailed_without_any_password(people):
    eng = people["eng"]
    old_hash = eng.password
    url = reverse("accounts:user_send_reset_link", args=[eng.profile.pk])
    assert people["a"].get(url).status_code == 405  # POST only
    r = people["a"].post(url, follow=True)
    assert r.status_code == 200 and "password-reset link was sent" in r.content.decode()
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == [eng.email]
    assert PASSWORD not in msg.body and old_hash not in msg.body
    link = re.search(r"https?://\S+/password/reset/\S+/\S+/", msg.body).group(0)
    eng.refresh_from_db()
    assert eng.password == old_hash  # sending the link changes nothing by itself
    assert AuditLog.objects.filter(action="password_reset").exists()
    # the link works once: set a new password, then the same link is invalid
    c = Client()
    path = link.split("://", 1)[1].split("/", 1)[1]
    r = c.get("/" + path, follow=True)
    form_url = r.redirect_chain[-1][0] if r.redirect_chain else "/" + path
    r = c.post(form_url, {"new_password1": "Brand-New-Pass-77", "new_password2": "Brand-New-Pass-77"})
    assert r.status_code == 302
    eng.refresh_from_db()
    assert eng.check_password("Brand-New-Pass-77")
    r = Client().get("/" + path, follow=True)
    assert "Link no longer valid" in r.content.decode()


def test_only_user_managers_can_send_reset_links(people):
    url = reverse("accounts:user_send_reset_link", args=[people["admin"].profile.pk])
    assert people["e"].post(url).status_code == 403
    assert people["x"].post(url).status_code == 403
    assert not mail.outbox
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(people["admin"], backend="django.contrib.auth.backends.ModelBackend")
    assert strict.post(reverse("accounts:user_send_reset_link", args=[people["eng"].profile.pk])).status_code == 403
    assert not mail.outbox


def test_passwords_never_appear_in_pages_or_exports(people):
    hashes = [u.password for u in get_user_model().objects.all()]
    pages = [reverse("accounts:user_list"), reverse("accounts:user_detail", args=[people["eng"].profile.pk]),
             reverse("team:list"), reverse("team:list") + "?export=csv", reverse("team:list") + "?export=xlsx",
             reverse("team:employee", args=[people["eng"].pk]), reverse("dailyreports:list")]
    for url in pages:
        r = people["a"].get(url)
        assert r.status_code == 200, url
        body = r.content
        assert PASSWORD.encode() not in body, url
        for h in hashes:
            assert h.encode() not in body, url
        if b"<html" in body:
            assert not re.search(rb'type="password"[^>]*value="[^"]+', body), url


def test_new_pages_need_login_and_hide_internals(people):
    anon = Client()
    for url in (reverse("team:list"), reverse("team:me"), reverse("dailyreports:list"),
                reverse("dailyreports:new"), reverse("reporting:import_start")):
        r = anon.get(url)
        assert r.status_code == 302 and "/login" in r["Location"]
    # Accounts has no monitoring rights
    assert people["x"].get(reverse("team:list")).status_code == 403
    assert people["x"].get(reverse("dailyreports:new")).status_code == 403
    # unknown objects: plain 404, no stack trace
    r = people["a"].get(reverse("dailyreports:detail", args=[99999]))
    assert r.status_code == 404 and b"Traceback" not in r.content


def test_daily_report_post_requires_csrf(people):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(people["eng"], backend="django.contrib.auth.backends.ModelBackend")
    assert strict.post(reverse("dailyreports:new"), {"report_date": "2026-01-01"}).status_code == 403
