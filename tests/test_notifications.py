"""Notifications: in-app, optional e-mail, de-duplication, daily reminders."""
import datetime

import pytest
from django.core import mail
from django.utils import timezone

from accounts import capabilities as caps
from core.models import CompanyProfile, SystemJobRun
from notifications.models import Notification, NotificationPreference
from notifications.services import notify

pytestmark = pytest.mark.django_db


def test_in_app_and_email_with_absolute_link(make_user, settings):
    settings.SITE_URL = "https://crm.example.com"
    user = make_user(caps.ENGINEER)
    company = CompanyProfile.get()
    company.email_notifications_enabled = True
    company.save()
    NotificationPreference.objects.create(user=user, category="task_assigned", in_app=True, email=True)
    notify([user], "task_assigned", "New task", "Call the customer", "/tasks/1/", dedupe_key="t1")
    notify([user], "task_assigned", "New task", "Call the customer", "/tasks/1/", dedupe_key="t1")  # duplicate
    assert Notification.objects.filter(user=user).count() == 1
    assert len(mail.outbox) == 1
    assert "https://crm.example.com/tasks/1/" in mail.outbox[0].body


def test_no_email_when_switched_off_company_wide(make_user):
    user = make_user(caps.ENGINEER)
    NotificationPreference.objects.create(user=user, category="task_assigned", in_app=True, email=True)
    notify([user], "task_assigned", "New task")
    assert len(mail.outbox) == 0 and Notification.objects.filter(user=user).count() == 1


def test_daily_reminders_run_once_per_day(make_user, login):
    from notifications.reminders import run_if_due
    from tasks.models import Task

    eng = make_user(caps.ENGINEER)
    Task.objects.create(title="Overdue call", assigned_to=eng, due_date=timezone.localdate() - datetime.timedelta(days=1))
    first = run_if_due()
    assert first is not None and "task" in first
    assert run_if_due() is None  # already ran today
    assert SystemJobRun.objects.get().last_run_date == timezone.localdate()
    assert Notification.objects.filter(user=eng).exists()
