"""
v4 sales flow: customer first → lead → meetings → Move to Sales Pipeline → opportunity (meetings, quotations,
follow-ups) → company history ("View as a company").
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts import capabilities as caps
from core.models import Activity, AuditLog
from customers.models import Customer
from leads.models import Lead, LeadStage
from meetings.models import Meeting
from meetings import services as meeting_services
from sales.models import Opportunity

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


@pytest.fixture
def org(make_user, login):
    director = make_user(caps.DIRECTOR)
    e1, e2 = make_user(caps.ENGINEER, username="eng.one"), make_user(caps.ENGINEER, username="eng.two")
    acc = make_user(caps.ACCOUNTS)
    cust = Customer.objects.create(company_name="Gulf Valves LLC", code="CUS-80001", assigned_engineer=e1,
                                   contact_person="Sara Buyer", phone="+971 50 111 2222", city="Dubai")
    other = Customer.objects.create(company_name="Other Two LLC", code="CUS-80002", assigned_engineer=e2)
    return {"director": director, "e1": e1, "e2": e2, "acc": acc, "cust": cust, "other": other,
            "d": login(director), "c1": login(e1), "c2": login(e2), "x": login(acc)}


def lead_data(**extra):
    data = {"category": "tender", "title": "Pump package", "priority": "medium", "estimated_value": "50000"}
    data.update(extra)
    return data


def meeting_data(**extra):
    data = {"meeting_date": (TODAY - datetime.timedelta(days=3)).isoformat(), "meeting_type": "in_person",
            "summary": "Introduction meeting", "points_discussed": "Pumps\nBudget", "next_action": "Send offer",
            "next_follow_up": (TODAY + datetime.timedelta(days=4)).isoformat()}
    data.update(extra)
    return data


def make_lead(org, **extra):
    r = org["c1"].post(reverse("leads:create"), lead_data(customer_mode="existing", customer=org["cust"].pk,
                                                          **extra))
    assert r.status_code == 302, r.content.decode()[:3000]
    return Lead.objects.latest("pk")


# ============================================================ customer first
def test_lead_needs_a_customer(org):
    r = org["c1"].post(reverse("leads:create"), lead_data(customer_mode="existing"))
    assert r.status_code == 200 and "Choose the customer" in r.content.decode()
    r = org["c1"].post(reverse("leads:create"), lead_data(customer_mode="new"))
    assert r.status_code == 200 and "company name of the new customer" in r.content.decode()
    assert not Lead.objects.exists()


def test_lead_with_existing_customer_takes_its_details(org):
    lead = make_lead(org)
    assert lead.customer == org["cust"] and lead.company_name == "Gulf Valves LLC"
    assert lead.contact_person == "Sara Buyer" and lead.city == "Dubai"
    assert not lead.is_converted  # having a customer is not the same as being in the pipeline
    page = org["c1"].get(lead.get_absolute_url()).content.decode()
    assert "Move to Sales Pipeline" in page and "Add meeting" in page and "company history" in page


def test_lead_with_new_customer_creates_the_customer(org):
    r = org["c1"].post(reverse("leads:create"), lead_data(customer_mode="new", company_name="Fresh Start LLC",
                                                          contact_person="Ali", email="ali@example.com"))
    assert r.status_code == 302
    lead = Lead.objects.get()
    cust = Customer.objects.get(company_name="Fresh Start LLC")
    assert lead.customer == cust and cust.status == "prospect" and cust.assigned_engineer == org["e1"]
    assert cust.email == "ali@example.com"
    assert Activity.objects.filter(customer=cust, message__contains=f"with lead {lead.code}").exists()


def test_new_customer_duplicate_needs_confirmation(org):
    r = org["c1"].post(reverse("leads:create"), lead_data(customer_mode="new", company_name="Gulf Valves LLC"))
    page = r.content.decode()
    assert r.status_code == 200 and "Similar existing customers" in page and not Lead.objects.exists()
    r = org["c1"].post(reverse("leads:create"), lead_data(customer_mode="new", company_name="Gulf Valves LLC",
                                                          confirm_new_customer="on"))
    assert r.status_code == 302 and Customer.objects.filter(company_name="Gulf Valves LLC").count() == 2


def test_customer_picker_is_scoped(org):
    # eng.two cannot attach a lead to eng.one's customer
    r = org["c2"].post(reverse("leads:create"), lead_data(customer_mode="existing", customer=org["cust"].pk))
    assert r.status_code == 200 and not Lead.objects.exists()
    form = org["c2"].get(reverse("leads:create")).content.decode()
    assert "Other Two LLC" in form and "Gulf Valves LLC" not in form


def test_add_lead_from_customer_page_preselects_customer(org):
    page = org["c1"].get(org["cust"].get_absolute_url()).content.decode()
    assert f"/leads/new/?customer={org['cust'].pk}" in page and "Company history" in page
    form = org["c1"].get(reverse("leads:create") + f"?customer={org['cust'].pk}").content.decode()
    assert f'value="{org["cust"].pk}" selected' in form


def test_customer_locked_after_meetings(org):
    lead = make_lead(org)
    org["c1"].post(reverse("meetings:add", args=["lead", lead.pk]), meeting_data())
    r = org["c1"].post(reverse("leads:edit", args=[lead.pk]), lead_data(customer=org["other"].pk,
                                                                        title="Pump package v2"))
    assert r.status_code == 302
    lead.refresh_from_db()
    assert lead.customer == org["cust"] and lead.title == "Pump package v2"


def test_old_lead_without_customer_still_moves_to_pipeline(org):
    lead = Lead.objects.create(title="Imported lead", company_name="Imported Co LLC", stage=LeadStage.first_open(),
                               assigned_engineer=org["e1"], category="tender")
    page = org["c1"].get(reverse("leads:convert", args=[lead.pk])).content.decode()
    assert "Link to an existing customer" in page
    r = org["c1"].post(reverse("leads:convert", args=[lead.pk]), {
        "mode": "new", "company_name": "Imported Co LLC", "create_opportunity": "on", "opp_title": "Imported deal",
        "opp_probability": "20"})
    assert r.status_code == 302
    lead.refresh_from_db()
    assert lead.is_converted and lead.customer.company_name == "Imported Co LLC"


# ============================================================ meetings
def test_meeting_crud_and_follow_up_sync(org):
    lead = make_lead(org)
    r = org["c1"].post(reverse("meetings:add", args=["lead", lead.pk]), meeting_data())
    assert r.status_code == 302, r.context["form"].errors if r.context else r.content[:500]
    m = Meeting.objects.get()
    assert m.customer == org["cust"] and m.lead == lead and not m.in_pipeline and m.held_by == org["e1"]
    assert m.points == ["Pumps", "Budget"]
    lead.refresh_from_db()
    assert lead.next_follow_up == TODAY + datetime.timedelta(days=4)
    assert lead.last_contact_date == TODAY - datetime.timedelta(days=3)
    page = org["c1"].get(lead.get_absolute_url()).content.decode()
    assert "Introduction meeting" in page and "Send offer" in page
    r = org["c1"].post(reverse("meetings:edit", args=[m.pk]), meeting_data(summary="Intro, revised"))
    assert r.status_code == 302 and Meeting.objects.get().summary == "Intro, revised"
    assert AuditLog.objects.filter(object_id=str(m.pk), action="update").exists()
    r = org["c1"].post(reverse("meetings:delete", args=[m.pk]))
    assert r.status_code == 302 and not Meeting.objects.exists()


def test_meeting_rules(org):
    lead = make_lead(org)
    url = reverse("meetings:add", args=["lead", lead.pk])
    r = org["c1"].post(url, meeting_data(meeting_date=(TODAY + datetime.timedelta(days=2)).isoformat()))
    assert r.status_code == 200 and "Customer Visits" in r.content.decode()
    r = org["c1"].post(url, meeting_data(next_follow_up=(TODAY - datetime.timedelta(days=10)).isoformat()))
    assert r.status_code == 200 and not Meeting.objects.exists()
    r = org["c1"].post(url, meeting_data(summary=""))
    assert r.status_code == 200 and not Meeting.objects.exists()


def test_meeting_permissions(org):
    lead = make_lead(org)
    url = reverse("meetings:add", args=["lead", lead.pk])
    assert org["c2"].post(url, meeting_data()).status_code == 404   # outside eng.two's scope
    assert org["x"].post(url, meeting_data()).status_code in (403, 404)  # accounts cannot edit leads
    org["c1"].post(url, meeting_data())
    m = Meeting.objects.get()
    assert org["c2"].post(reverse("meetings:delete", args=[m.pk])).status_code == 404
    assert org["c2"].get(reverse("meetings:edit", args=[m.pk])).status_code == 404
    assert Meeting.objects.count() == 1


# ============================================================ move to sales pipeline
def test_move_to_pipeline_and_meeting_counts(org):
    lead = make_lead(org)
    for days in (10, 5):
        org["c1"].post(reverse("meetings:add", args=["lead", lead.pk]),
                       meeting_data(meeting_date=(TODAY - datetime.timedelta(days=days)).isoformat(),
                                    next_follow_up=""))
    page = org["c1"].get(reverse("leads:convert", args=[lead.pk])).content.decode()
    assert "Gulf Valves LLC" in page and "Link to an existing customer" not in page
    assert "Meetings recorded on this lead so far: <strong>2</strong>" in page
    r = org["c1"].post(reverse("leads:convert", args=[lead.pk]), {"opp_title": "", "opp_probability": "30"})
    assert r.status_code == 200 and not Opportunity.objects.exists()  # the opportunity title is required
    r = org["c1"].post(reverse("leads:convert", args=[lead.pk]), {"opp_title": "Pump package deal",
                                                                  "opp_value": "48000", "opp_probability": "30"})
    opp = Opportunity.objects.get()
    assert r.status_code == 302 and r.url == opp.get_absolute_url()
    lead.refresh_from_db()
    assert lead.is_converted and opp.customer == org["cust"] and Customer.objects.count() == 2
    r = org["c1"].post(reverse("meetings:add", args=["opportunity", opp.pk]),
                       meeting_data(meeting_date=TODAY.isoformat(), summary="Commercial meeting"))
    assert r.status_code == 302
    assert Meeting.objects.get(summary="Commercial meeting").in_pipeline
    assert meeting_services.counts(opportunity=opp) == {"total": 3, "before_pipeline": 2, "in_pipeline": 1}
    page = org["c1"].get(opp.get_absolute_url()).content.decode()
    assert "Commercial meeting" in page and "Introduction meeting" in page and "2 before the pipeline" in page
    opp.refresh_from_db()
    assert opp.next_follow_up == TODAY + datetime.timedelta(days=4)
    # list columns
    lst = org["c1"].get(reverse("sales:pipeline")).context
    row = [o for o in lst["page"].object_list if o.pk == opp.pk][0]
    assert row.meeting_count == 3
    leads = org["c1"].get(reverse("leads:list") + "?converted=1").context["page"].object_list
    assert [x.pk for x in leads] == [lead.pk] and leads[0].meeting_count == 3  # the whole journey of the lead
    # a second move is refused
    r = org["c1"].get(reverse("leads:convert", args=[lead.pk]))
    assert r.status_code == 302 and Opportunity.objects.count() == 1


# ============================================================ company history
def test_company_history(org):
    lead = make_lead(org)
    org["c1"].post(reverse("meetings:add", args=["lead", lead.pk]), meeting_data(summary="First talk"))
    org["c1"].post(reverse("leads:convert", args=[lead.pk]), {"opp_title": "Pump deal", "opp_value": "40000",
                                                              "opp_probability": "30"})
    opp = Opportunity.objects.get()
    org["c1"].post(reverse("meetings:add", args=["opportunity", opp.pk]),
                   meeting_data(meeting_date=TODAY.isoformat(), summary="Price talk"))
    r = org["c1"].get(reverse("customers:history", args=[org["cust"].pk]))
    assert r.status_code == 200
    s = r.context["summary"]
    assert (s["leads"], s["leads_in_pipeline"], s["meetings"], s["meetings_before"], s["meetings_in_pipeline"],
            s["opportunities"], s["opps_open"]) == (1, 1, 2, 1, 1, 1, 1)
    j = r.context["journeys"][0]
    assert j["lead"] == lead and len(j["meetings_before"]) == 1 and j["opportunities"][0]["meetings_total"] == 2
    page = r.content.decode()
    for text in ("First talk", "Price talk", "Pump deal", "Moved to the sales pipeline", "Full timeline"):
        assert text in page
    # scope: another engineer cannot open it; the director can
    assert org["c2"].get(reverse("customers:history", args=[org["cust"].pk])).status_code == 404
    assert org["d"].get(reverse("customers:history", args=[org["cust"].pk])).status_code == 200


def test_company_picker_and_dashboard_box(org):
    page = org["c1"].get(reverse("core:dashboard")).content.decode()
    assert "View as a company" in page
    r = org["c1"].get(reverse("customers:history_picker") + "?q=gulf")
    assert r.status_code == 302 and r.url == reverse("customers:history", args=[org["cust"].pk])
    r = org["c2"].get(reverse("customers:history_picker") + "?q=gulf")
    assert r.status_code == 200 and "No company found" in r.content.decode()
    r = org["c1"].get(reverse("customers:history_picker"))
    assert r.status_code == 200 and "Gulf Valves LLC" in r.content.decode()


def test_won_deal_meetings_per_win(org):
    lead = make_lead(org)
    for days in (9, 6):
        org["c1"].post(reverse("meetings:add", args=["lead", lead.pk]),
                       meeting_data(meeting_date=(TODAY - datetime.timedelta(days=days)).isoformat()))
    org["c1"].post(reverse("leads:convert", args=[lead.pk]), {"opp_title": "Won deal", "opp_value": "10000",
                                                              "opp_probability": "50"})
    opp = Opportunity.objects.get()
    from sales.models import OpportunityStage
    from sales.services import change_stage
    change_stage(opp, OpportunityStage.objects.get(is_won=True))
    s = org["d"].get(reverse("customers:history", args=[org["cust"].pk])).context["summary"]
    assert s["opps_won"] == 1 and s["meetings_per_win"] == 2 and s["won_value"] == 10000
