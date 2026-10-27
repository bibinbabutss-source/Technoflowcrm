"""Create / edit / status forms of every module, submitted through the real pages (HTML forms parsed and posted)."""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts import capabilities as caps
from communications.models import Communication
from core.models import TaxRate
from customers.models import Customer, CustomerContact
from leads.models import LeadStage
from performance.models import KPIDefinition, SalesTarget
from sales.models import Opportunity, OpportunityStage, Project
from tasks.models import Task
from visits.models import Visit

from .webforms import page, select_value, submit

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


@pytest.fixture
def eng(make_user):
    return make_user(caps.ENGINEER, first_name="Eng")


def test_customer_create_edit_contact_archive(eng, make_user, login):
    e = login(eng)
    submit(e, reverse("customers:create"), {"company_name": "Form Test Contracting LLC", "email": "a@example.com",
                                            "phone": "+971 4 000 0000", "city": "Dubai"})
    cust = Customer.objects.get(company_name="Form Test Contracting LLC")
    assert cust.assigned_engineer == eng and cust.code
    submit(e, reverse("customers:edit", args=[cust.pk]), {"city": "Sharjah"})
    cust.refresh_from_db()
    assert cust.city == "Sharjah"
    submit(e, reverse("customers:contact_add", args=[cust.pk]), {"name": "Site Manager", "email": "sm@example.com"})
    assert CustomerContact.objects.filter(customer=cust, name="Site Manager").exists()
    # required field missing -> form shown again with an error, nothing saved
    r = submit(e, reverse("customers:create"), {"company_name": ""}, expect_redirect=False)
    assert r.status_code == 200 and Customer.objects.count() == 1
    assert e.post(reverse("customers:archive", args=[cust.pk])).status_code == 403  # engineers cannot archive
    director = login(make_user(caps.DIRECTOR))
    assert director.post(reverse("customers:archive", args=[cust.pk])).status_code == 302
    cust.refresh_from_db()
    assert cust.is_archived


def test_opportunity_and_project(eng, make_user, login):
    e = login(eng)
    cust = Customer.objects.create(company_name="Opp LLC", assigned_engineer=eng)
    url = reverse("sales:opportunity_create") + f"?customer={cust.pk}"
    submit(e, url, {"title": "Pump upgrade", "customer": str(cust.pk), "estimated_value": "50000",
                    "expected_close_date": (TODAY + datetime.timedelta(days=30)).isoformat()})
    opp = Opportunity.objects.get(title="Pump upgrade")
    nxt = OpportunityStage.objects.filter(is_won=False, is_lost=False).exclude(pk=opp.stage_id).first()
    assert e.post(reverse("sales:opportunity_stage", args=[opp.pk]), {"stage": nxt.pk}).status_code == 302
    opp.refresh_from_db()
    assert opp.stage == nxt and opp.stage_history.exists()
    lost = OpportunityStage.objects.get(is_lost=True)
    e.post(reverse("sales:opportunity_stage", args=[opp.pk]), {"stage": lost.pk})  # no reason -> refused
    opp.refresh_from_db()
    assert opp.stage == nxt
    d = login(make_user(caps.DIRECTOR))
    submit(d, reverse("sales:project_create") + f"?customer={cust.pk}", {"name": "Pump upgrade works",
                                                                        "customer": str(cust.pk)})
    assert Project.objects.filter(name="Pump upgrade works").exists()


def test_visit_schedule_complete_followup(eng, make_user, login):
    coord = make_user(caps.COORDINATOR)
    coord.profile.team_members.add(eng.profile)
    cust = Customer.objects.create(company_name="Visit LLC", assigned_engineer=eng)
    c = login(coord)
    html = page(c, reverse("visits:create") + f"?customer={cust.pk}").content.decode()
    submit(c, reverse("visits:create") + f"?customer={cust.pk}", {
        "customer": str(cust.pk), "assigned_to": select_value(html, "assigned_to", "Eng"),
        "visit_date": TODAY.isoformat(), "start_time": "10:00", "end_time": "11:00", "location": "Site A"})
    visit = Visit.objects.get(customer=cust)
    assert visit.status == "scheduled"
    e = login(eng)
    # completing without notes is refused
    r = submit(e, reverse("visits:complete", args=[visit.pk]), {"meeting_notes": ""}, expect_redirect=False)
    assert r.status_code == 200
    submit(e, reverse("visits:complete", args=[visit.pk]), {
        "meeting_notes": "Discussed scope", "create_task": "on", "next_follow_up_owner": str(eng.pk),
        "next_follow_up_date": (TODAY + datetime.timedelta(days=3)).isoformat()})
    visit.refresh_from_db()
    assert visit.status == "completed" and visit.completed_by == eng
    assert Task.objects.filter(visit=visit).exists()


def test_task_create_status_comment(eng, login):
    e = login(eng)
    submit(e, reverse("tasks:create"), {"title": "Send drawings", "due_date": TODAY.isoformat()})
    task = Task.objects.get(title="Send drawings")
    assert task.assigned_to == eng
    submit(e, reverse("tasks:edit", args=[task.pk]), {"priority": "high"})
    task.refresh_from_db()
    assert task.priority == "high"
    e.post(reverse("tasks:detail", args=[task.pk]), {"body": "Drawings requested from design"})
    assert e.post(reverse("tasks:set_status", args=[task.pk]), {"status": "completed"}).status_code == 302
    task.refresh_from_db()
    assert task.status == "completed" and task.completed_at


def test_communication_with_follow_up(eng, login):
    e = login(eng)
    cust = Customer.objects.create(company_name="Comm LLC", assigned_engineer=eng)
    submit(e, reverse("communications:create") + f"?customer={cust.pk}", {
        "customer": str(cust.pk), "kind": "call", "subject": "Price follow-up", "summary": "Customer wants 5% off",
        "follow_up_date": (TODAY + datetime.timedelta(days=2)).isoformat(), "create_task": "on"})
    comm = Communication.objects.get(subject="Price follow-up")
    assert comm.employee == eng
    assert Task.objects.filter(customer=cust).exists()


def test_targets_kpis_and_settings(make_user, login, eng):
    admin = login(make_user(caps.ADMIN))
    director = login(make_user(caps.DIRECTOR))
    kpi = KPIDefinition.objects.get(code="orders_booked")
    url = reverse("performance:set_targets") + f"?employee={eng.pk}&period_type=month&period_date={TODAY}"
    page(director, url)
    r = director.post(url, {"employee": eng.pk, "period_type": "month", "period_date": TODAY.isoformat(),
                            f"kpi_{kpi.pk}": "250000"})
    assert r.status_code == 302
    assert SalesTarget.objects.get(employee=eng, kpi=kpi).target_value == 250000
    submit(director, reverse("performance:kpi_edit", args=[kpi.pk]), {"weight": "40"})
    kpi.refresh_from_db()
    assert kpi.weight == 40
    # settings pages
    submit(admin, reverse("core:settings_workflow"), {"approval_threshold": "50000", "overdue_reminder_days": "30,7,1"})
    from core.models import CompanyProfile

    company = CompanyProfile.get()
    assert company.approval_threshold == 50000 and company.overdue_reminder_days == "1,7,30"
    r = submit(admin, reverse("core:settings_workflow"), {"rating_good": "95"}, expect_redirect=False)
    assert r.status_code == 200  # bands out of order are refused
    submit(admin, reverse("core:tax_rates"), {"name": "Special", "rate": "2.5", "is_active": "on"})
    assert TaxRate.objects.filter(name="Special").exists()
    submit(admin, reverse("core:stages", args=["lead"]), {"name": "Site survey", "order": "3", "is_active": "on"})
    assert LeadStage.objects.filter(name="Site survey").exists()
    assert admin.post(reverse("core:run_reminders")).status_code == 302
    submit(admin, reverse("notifications:preferences"), {})


def test_mfa_setup_from_profile(eng, login):
    import pyotp

    e = login(eng)
    page(e, reverse("accounts:mfa_setup"))
    secret = e.session["mfa_setup_secret"]
    e.post(reverse("accounts:mfa_setup"), {"code": pyotp.TOTP(secret).now()})
    eng.profile.refresh_from_db()
    assert eng.profile.mfa_enabled and eng.profile.mfa_secret == secret


def test_lead_lost_needs_reason_and_archive(eng, make_user, login):
    from leads.models import Lead

    lead = Lead.objects.create(title="Lost test", company_name="Lost LLC", assigned_engineer=eng,
                               stage=LeadStage.objects.filter(is_won=False, is_lost=False).first())
    e = login(eng)
    lost = LeadStage.objects.get(is_lost=True)
    r = submit(e, reverse("leads:stage", args=[lead.pk]), {"stage": str(lost.pk)}, expect_redirect=False)
    assert r.status_code == 200
    lead.refresh_from_db()
    assert not lead.stage.is_lost
    from core.models import LookupValue

    reason = LookupValue.objects.filter(category="lost_reason").first()
    submit(e, reverse("leads:stage", args=[lead.pk]), {"stage": str(lost.pk), "lost_reason": str(reason.pk)})
    lead.refresh_from_db()
    assert lead.stage.is_lost and lead.lost_reason == reason
    coord = login(make_user(caps.COORDINATOR))
    admin = login(make_user(caps.ADMIN))
    assert admin.post(reverse("leads:archive", args=[lead.pk])).status_code == 302
    lead.refresh_from_db()
    assert lead.is_archived
    assert coord.get(reverse("leads:detail", args=[lead.pk])).status_code == 404  # not in coordinator's team


def test_visit_cancel_and_quotation_draft_delete(eng, make_user, login):
    from quotations import services as qs
    from quotations.models import Quotation

    cust = Customer.objects.create(company_name="Misc LLC", assigned_engineer=eng)
    e = login(eng)
    v = Visit.objects.create(customer=cust, assigned_to=eng, visit_date=TODAY, start_time="09:00", end_time="10:00",
                             location="Office")
    submit(e, reverse("visits:cancel", args=[v.pk]), {"reason": "Customer travelling"})
    v.refresh_from_db()
    assert v.status == "cancelled" and v.cancel_reason == "Customer travelling"
    q, rev = qs.create_quotation(customer=cust, opportunity=None, salesperson=eng, currency="AED", user=eng)
    Quotation.objects.filter(pk=q.pk).update(created_by=eng)
    assert e.post(reverse("quotations:delete", args=[q.pk])).status_code == 302
    assert not Quotation.objects.filter(pk=q.pk).exists()
