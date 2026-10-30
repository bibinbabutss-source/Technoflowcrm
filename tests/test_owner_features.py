"""
Oct-2026 enhancement: lead categories, opportunities, uploaded quotation revisions, Owner role and dashboard,
pending approvals, targets, team calendar, Finance switch, module dashboards and navigation.
"""
import datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from accounts import capabilities as caps
from accounts.models import Capability, Role
from core.models import AuditLog, CompanyProfile, LookupValue
from customers.models import Customer
from leads.models import Lead, LeadStage
from notifications.models import Notification
from performance import monitoring as mon
from quotations import services as qs
from quotations import uploads
from quotations.models import Quotation, QuotationFile
from sales.models import Opportunity, OpportunityStage
from tasks.models import Task
from visits.models import Visit

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


def pdf(name="q.pdf", body=b"offer"):
    return SimpleUploadedFile(name, b"%PDF-1.4\n" + body + b"\n%%EOF\n", "application/pdf")


@pytest.fixture
def org(make_user, login):
    owner, admin, director = make_user(caps.OWNER), make_user(caps.ADMIN), make_user(caps.DIRECTOR)
    e1, e2 = make_user(caps.ENGINEER, username="eng.one"), make_user(caps.ENGINEER, username="eng.two")
    coord, acc = make_user(caps.COORDINATOR), make_user(caps.ACCOUNTS)
    cust = Customer.objects.create(company_name="Gulf Valves LLC", code="CUS-70001", assigned_engineer=e1)
    cust2 = Customer.objects.create(company_name="Other Two LLC", code="CUS-70002", assigned_engineer=e2)
    return {"owner": owner, "admin": admin, "director": director, "e1": e1, "e2": e2, "coord": coord, "acc": acc,
            "cust": cust, "cust2": cust2, "o": login(owner), "a": login(admin), "d": login(director),
            "c1": login(e1), "c2": login(e2), "co": login(coord), "x": login(acc)}


def lead_post(**extra):
    data = {"category": "tender", "title": "Pump package", "company_name": "New Prospect LLC", "priority": "medium",
            "estimated_value": ""}
    data.update(extra)
    return data


# =============================================================== leads
def test_lead_category_required_and_value_optional(org):
    r = org["c1"].post(reverse("leads:create"), lead_post(category=""))
    assert r.status_code == 200 and "Choose the lead category" in r.content.decode()
    assert not Lead.objects.exists()
    r = org["c1"].post(reverse("leads:create"), lead_post())
    assert r.status_code == 302
    lead = Lead.objects.get()
    assert lead.category == "tender" and lead.estimated_value == 0
    assert lead.created_by == org["e1"] and lead.assigned_engineer == org["e1"]  # creator + responsible owner
    page = org["c1"].get(lead.get_absolute_url()).content.decode()
    assert "Tender" in page and "Product interest" in page and "Not given" in page
    # Add Lead form shows the three categories as choices
    form = org["c1"].get(reverse("leads:create")).content.decode()
    for label in ("Job in Hand", "Tender", "Purchase Enquiry"):
        assert label in form


def test_responsible_employee_required_for_assigners_and_category_history(org):
    r = org["d"].post(reverse("leads:create"), lead_post())
    assert r.status_code == 200 and not Lead.objects.exists()  # director must choose the responsible employee
    r = org["d"].post(reverse("leads:create"), lead_post(assigned_engineer=org["e1"].pk))
    assert r.status_code == 302
    lead = Lead.objects.get()
    # another authorised user (not the creator) changes the category: allowed, and the history keeps it
    r = org["c1"].post(reverse("leads:edit", args=[lead.pk]), lead_post(category="job_in_hand",
                                                                       assigned_engineer=org["e1"].pk))
    assert r.status_code == 302
    lead.refresh_from_db()
    assert lead.category == "job_in_hand" and lead.created_by == org["director"]
    page = org["c1"].get(lead.get_absolute_url()).content.decode()
    assert "Category changed from Tender to Job in Hand" in page
    assert "Change history" in page
    log = AuditLog.objects.filter(action="update", object_id=str(lead.pk)).first()
    assert log.user == org["e1"] and log.changes["category"] == ["tender", "job_in_hand"]


def test_lead_list_category_filters_and_columns(org):
    stage = LeadStage.first_open()
    for cat, n in (("job_in_hand", 2), ("tender", 1), ("purchase_enquiry", 3)):
        for i in range(n):
            Lead.objects.create(title=f"{cat}{i}", company_name=f"{cat} Co {i}", category=cat, stage=stage,
                                assigned_engineer=org["e1"])
    r = org["o"].get(reverse("leads:list") + "?category=purchase_enquiry")
    assert r.status_code == 200
    body = r.content.decode()
    assert body.count("purchase_enquiry Co") == 3 and "tender Co" not in body
    assert "Created by" in body and "Responsible" in body
    for key in ("source", "stage", "employee", "created_from"):
        assert f'name="{key}' in org["o"].get(reverse("leads:list")).content.decode()


def test_lead_sources_add_edit_deactivate_keep_history(org):
    r = org["a"].post(reverse("core:lookups") + "?category=lead_source",
                      {"category": "lead_source", "value": "Trade Show", "is_active": "on", "sort_order": 1})
    assert r.status_code == 302
    src = LookupValue.objects.get(category="lead_source", value="Trade Show")
    lead = Lead.objects.create(title="L", company_name="C", category="tender", stage=LeadStage.first_open(),
                               source=src, assigned_engineer=org["e1"])
    r = org["a"].post(reverse("core:lookup_edit", args=[src.pk]), {"value": "Trade Exhibition", "sort_order": 1,
                                                                    "is_active": "on", "category": "industry"})
    assert r.status_code == 302
    src.refresh_from_db()
    assert src.value == "Trade Exhibition" and src.category == "lead_source"  # list never changes
    org["a"].post(reverse("core:lookup_toggle", args=[src.pk]))
    src.refresh_from_db()
    assert not src.is_active and LookupValue.objects.filter(pk=src.pk).exists()  # deactivated, never deleted
    lead.refresh_from_db()
    assert lead.source == src
    form = org["c1"].get(reverse("leads:create")).content.decode()
    assert "Trade Exhibition" not in form  # inactive: not offered for new leads
    assert org["c1"].get(reverse("core:lookup_edit", args=[src.pk])).status_code == 403


# =============================================================== opportunities
def test_opportunity_from_lead_carries_forward_and_prevents_duplicates(org):
    src = LookupValue.objects.filter(category="lead_source").first()
    lead = Lead.objects.create(title="Chiller AMC", company_name="Gulf Valves LLC", category="job_in_hand",
                               stage=LeadStage.first_open(), customer=org["cust"], source=src, interest="Chillers",
                               estimated_value=Decimal("90000"), assigned_engineer=org["e1"], city="Dubai")
    page = org["c1"].get(reverse("sales:opportunity_create") + f"?lead={lead.pk}&customer={org['cust'].pk}")
    form = page.context["form"]
    assert form.initial["title"] == "Chiller AMC" and form.initial["products_services"] == "Chillers"
    assert form.initial["estimated_value"] == Decimal("90000")
    data = {"title": "Chiller AMC", "customer": org["cust"].pk, "lead": lead.pk, "estimated_value": "90000",
            "probability": 10, "assigned_engineer": org["e1"].pk, "team_members": [org["e2"].pk]}
    assert org["c1"].post(reverse("sales:opportunity_create"), data).status_code == 302
    opp = Opportunity.objects.get()
    assert opp.lead == lead and list(opp.team_members.all()) == [org["e2"]]
    lead.refresh_from_db()
    assert lead.title == "Chiller AMC" and lead.category == "job_in_hand"  # the lead is preserved
    r = org["c1"].post(reverse("sales:opportunity_create"), {**data, "title": "Duplicate"})
    assert r.status_code == 200 and "already has an opportunity" in r.content.decode()
    assert Opportunity.objects.count() == 1
    # team members do not double revenue: credited once to the responsible employee
    opp.stage = OpportunityStage.objects.get(is_won=True)
    opp.closed_at = timezone.now()
    opp.save()
    figs = mon.list_figures([org["e1"].pk, org["e2"].pk], TODAY, TODAY)
    assert figs[org["e1"].pk]["won_value"] == Decimal("90000") and figs[org["e2"].pk]["won_value"] == 0


def test_stage_names_and_menu(org):
    names = list(OpportunityStage.objects.values_list("name", flat=True))
    for name in ("Qualification", "Proposal", "Negotiation", "Won", "Lost"):
        assert name in names
    nav = org["o"].get(reverse("sales:pipeline")).context["crm_nav"]
    sales = [i["label"] for s in nav if s["title"] == "Sales" for i in s["items"]]
    assert sales == ["Dashboard", "Leads", "Customer Visits", "Customers", "Sales Pipeline", "Opportunities",
                     "Projects", "Quotations"]
    active = [i["label"] for s in nav for i in s["items"] if i["active"]]
    assert active == ["Opportunities"]
    nav = org["o"].get(reverse("sales:kanban")).context["crm_nav"]
    assert [i["label"] for s in nav for i in s["items"] if i["active"]] == ["Sales Pipeline"]
    nav = org["o"].get(reverse("sales:projects")).context["crm_nav"]
    assert [i["label"] for s in nav for i in s["items"] if i["active"]] == ["Projects"]


def test_stage_rename_migration_logic(org):
    import importlib

    mig = importlib.import_module("sales.migrations.0003_rename_default_stages")
    OpportunityStage.objects.filter(name="Qualification").update(name="Initial Discussion")

    class Apps:
        @staticmethod
        def get_model(app, name):
            return OpportunityStage

    mig.forwards(Apps, None)
    assert OpportunityStage.objects.filter(name="Qualification").exists()
    assert not OpportunityStage.objects.filter(name="Initial Discussion").exists()


# =============================================================== uploaded quotations
def _upload(client, cust, **extra):
    data = {"customer": cust.pk, "salesperson": extra.pop("salesperson"), "currency": "AED",
            "quotation_date": TODAY.isoformat(), "value": "12500", "external_number": "EXT-1", "notes": "First",
            "file": pdf()}
    data.update(extra)
    return client.post(reverse("quotations:upload"), data)


def test_uploaded_quotation_revisions_are_kept_and_final_marked(org):
    r = _upload(org["c1"], org["cust"], salesperson=org["e1"].pk)
    assert r.status_code == 302
    q = Quotation.objects.get()
    assert q.is_uploaded and q.current.label == "Original" and q.grand_total == Decimal("12500")
    f0 = q.current.document
    assert f0.uploaded_by == org["e1"] and bytes(f0.data).startswith(b"%PDF")
    # R1 and R2: new revisions, earlier ones superseded but intact
    for i, value in enumerate(("12000", "11800"), start=1):
        r = org["c1"].post(reverse("quotations:upload_revision", args=[q.pk]), {
            "file": pdf(f"r{i}.pdf", f"rev {i}".encode()), "quotation_date": TODAY.isoformat(), "value": value,
            "notes": f"Price change {i}"})
        assert r.status_code == 302, r.content
    q.refresh_from_db()
    revs = {r.version: r for r in q.revisions.all()}
    assert [revs[v].revision_code for v in (1, 2, 3)] == ["Original", "R1", "R2"]
    assert revs[1].status == "superseded" and revs[2].status == "superseded" and q.current_version == 3
    assert q.grand_total == Decimal("11800") and Quotation.objects.count() == 1  # still ONE quotation
    for v in (1, 2, 3):
        d = org["c1"].get(reverse("quotations:file", args=[q.pk, v]))
        assert d.status_code == 200 and d["Content-Disposition"].startswith("attachment")
    assert b"rev 1" in org["c1"].get(reverse("quotations:file", args=[q.pk, 2])).content
    # mark final
    org["c1"].post(reverse("quotations:mark_final", args=[q.pk]))
    q = Quotation.objects.get(pk=q.pk)
    assert q.current.is_final and q.current.label == "Final (R2)"
    page = org["c1"].get(q.get_absolute_url()).content.decode()
    for text in ("Original", "R1", "Final", "Latest", "Price change 1", "Revision history"):
        assert text in page
    # files can never be replaced or deleted
    with pytest.raises(ValidationError):
        f0.save()
    with pytest.raises(ValidationError):
        f0.delete()
    assert AuditLog.objects.filter(action="download").count() == 4
    # quotation counted once; revisions counted separately; never revenue
    figs = mon.list_figures([org["e1"].pk], TODAY, TODAY)[org["e1"].pk]
    assert figs["quotations_created"] == 1 and figs["quotations_uploaded"] == 1 and figs["quotations_revised"] == 1
    assert figs["won_value"] == 0


def test_upload_validation_and_access(org):
    r = _upload(org["c1"], org["cust"], salesperson=org["e1"].pk,
                file=SimpleUploadedFile("fake.pdf", b"MZ not a pdf", "application/pdf"))
    assert r.status_code == 200 and "does not match a real .pdf" in r.content.decode()
    r = _upload(org["c1"], org["cust"], salesperson=org["e1"].pk,
                file=SimpleUploadedFile("x.exe", b"MZ", "application/octet-stream"))
    assert r.status_code == 200 and not Quotation.objects.exists()
    assert _upload(org["c1"], org["cust"], salesperson=org["e1"].pk).status_code == 302
    q = Quotation.objects.get()
    # another engineer can neither see nor download it
    assert org["c2"].get(q.get_absolute_url()).status_code == 404
    assert org["c2"].get(reverse("quotations:file", args=[q.pk, 1])).status_code == 404
    assert org["x"].get(reverse("quotations:file", args=[q.pk, 1])).status_code == 403
    # waiting for approval: no new revision until decided
    qs.submit(q.current, org["e1"])
    q.refresh_from_db()
    assert q.status == "submitted"
    with pytest.raises(ValidationError):
        uploads.upload_revision(q, user=org["e1"], file=pdf(), value=1, quotation_date=TODAY)


# =============================================================== owner role and approvals
def test_owner_role_has_everything_and_dashboard_is_owner_only(org):
    owner_caps = set(Role.objects.get(code=caps.OWNER).capabilities.values_list("code", flat=True))
    assert owner_caps == set(Capability.objects.values_list("code", flat=True))
    assert org["o"].get(reverse("owner:dashboard")).status_code == 200
    for c in ("a", "d", "c1", "co", "x"):
        assert org[c].get(reverse("owner:dashboard")).status_code == 403, c
    nav = org["o"].get(reverse("owner:dashboard")).context["crm_nav"]
    assert nav[0]["title"] == "Owner" and nav[0]["items"][0]["label"] == "Owner Dashboard"


def _submitted(org, value="50000"):
    q = uploads.create_uploaded(customer=org["cust"], salesperson=org["e1"], user=org["e1"], file=pdf(),
                                value=Decimal(value), quotation_date=TODAY)
    return qs.submit(q.current, org["e1"])


def test_owner_approves_from_pending_approvals_and_employee_is_notified(org):
    rev = _submitted(org)
    page = org["o"].get(reverse("owner:approvals"))
    body = page.content.decode()
    assert rev.quotation.number in body and "Approve" in body and "Download Original" in body
    r = org["o"].post(reverse("quotations:decide", args=[rev.quotation.pk]),
                      {"decision": "approve", "comments": "OK", "next": reverse("owner:approvals")})
    assert r.status_code == 302 and r["Location"] == reverse("owner:approvals")
    rev.refresh_from_db()
    assert rev.status == "approved" and rev.decided_by == org["owner"] and rev.decision_comments == "OK"
    assert Notification.objects.filter(user=org["e1"], title__startswith="Quotation approved").exists()
    # rejection needs a comment and notifies too
    rev2 = _submitted(org, "1000")
    org["o"].post(reverse("quotations:decide", args=[rev2.quotation.pk]), {"decision": "reject", "comments": ""})
    rev2.refresh_from_db()
    assert rev2.status == "submitted"
    org["o"].post(reverse("quotations:decide", args=[rev2.quotation.pk]),
                  {"decision": "reject", "comments": "Too cheap"})
    rev2.refresh_from_db()
    assert rev2.status == "rejected"
    assert Notification.objects.filter(user=org["e1"], title__startswith="Quotation rejected").exists()
    # an open redirect is ignored
    rev3 = _submitted(org, "2000")
    r = org["o"].post(reverse("quotations:decide", args=[rev3.quotation.pk]),
                      {"decision": "approve", "next": "https://evil.example/x"})
    assert r["Location"] == rev3.quotation.get_absolute_url()


def test_only_owner_approves_director_as_backup_admin_never(org):
    rev = _submitted(org)
    url = reverse("quotations:decide", args=[rev.quotation.pk])
    assert org["d"].post(url, {"decision": "approve"}).status_code == 403
    assert org["a"].post(url, {"decision": "approve"}).status_code == 403
    assert org["c1"].post(url, {"decision": "approve"}).status_code == 403
    rev.refresh_from_db()
    assert rev.status == "submitted"
    page = org["d"].get(reverse("owner:approvals")).content.decode()
    assert "Approvals are done by the Owner" in page and 'value="approve"' not in page
    # the Owner turns on the Director backup
    r = org["o"].post(reverse("owner:modules"), {"finance_enabled": "on", "director_backup_approval": "on",
                                                 "approval_threshold": "0", "discount_approval_limit": "10"})
    assert r.status_code == 302 and CompanyProfile.get().director_backup_approval
    assert org["d"].post(url, {"decision": "approve"}).status_code == 302
    rev.refresh_from_db()
    assert rev.status == "approved" and rev.decided_by == org["director"]
    assert org["a"].post(reverse("quotations:decide", args=[_submitted(org).quotation.pk]),
                         {"decision": "approve"}).status_code == 403  # admin still not


def test_without_an_owner_account_the_previous_rule_applies(org):
    get_user_model().objects.filter(pk=org["owner"].pk).update(is_active=False)
    rev = _submitted(org)
    assert org["d"].post(reverse("quotations:decide", args=[rev.quotation.pk]), {"decision": "approve"}).status_code \
        == 302
    rev.refresh_from_db()
    assert rev.status == "approved"


def test_nobody_approves_own_quotation(org, make_user):
    rev = _submitted(org)
    q = rev.quotation
    q.salesperson = org["owner"]
    q.save()
    with pytest.raises(PermissionDenied):
        qs.approve(rev, org["owner"])


# =============================================================== targets
def _won(org, user, value, when):
    opp = Opportunity.objects.create(title=f"Deal {value}", customer=org["cust"], assigned_engineer=user,
                                     estimated_value=Decimal(value), stage=OpportunityStage.objects.get(is_won=True))
    Opportunity.objects.filter(pk=opp.pk).update(closed_at=timezone.make_aware(
        datetime.datetime.combine(when, datetime.time(12))))
    return opp


def test_quarterly_and_yearly_targets_and_status(org):
    from performance.models import KPIDefinition, SalesTarget
    from reporting.metrics import period_bounds

    kpi = KPIDefinition.objects.get(code="won_value")
    q_start, q_end = period_bounds("quarter", TODAY)
    y_start, _ = period_bounds("year", TODAY)
    SalesTarget.objects.create(employee=org["e1"], kpi=kpi, period_type="quarter", period_start=q_start,
                               target_value=Decimal("100000"))
    SalesTarget.objects.create(employee=org["e1"], kpi=kpi, period_type="year", period_start=y_start,
                               target_value=Decimal("1000000"))
    SalesTarget.objects.create(employee=org["e2"], kpi=kpi, period_type="quarter", period_start=q_start,
                               target_value=Decimal("50000"))
    _won(org, org["e1"], "120000", q_start)
    _won(org, org["e2"], "10000", q_start)
    Opportunity.objects.create(title="Open big", customer=org["cust"], assigned_engineer=org["e2"],
                               estimated_value=Decimal("60000"), stage=OpportunityStage.first_open(),
                               expected_close_date=q_end)
    # a quotation value is never revenue
    uploads.create_uploaded(customer=org["cust"], salesperson=org["e1"], user=org["e1"], file=pdf(),
                            value=Decimal("999999"), quotation_date=TODAY)
    f = mon.list_figures([org["e1"].pk, org["e2"].pk], q_start, q_end, target_period="quarter")
    assert f[org["e1"].pk]["target"] == Decimal("100000") and f[org["e1"].pk]["achievement"] == Decimal("120.0")
    assert f[org["e1"].pk]["target_status"] == "achieved"
    assert f[org["e2"].pk]["target_status"] == "on_track"  # 10,000 won + 60,000 open pipeline due >= 50,000
    y = mon.list_figures([org["e1"].pk], y_start, TODAY, target_period="year")[org["e1"].pk]
    assert y["target"] == Decimal("1000000") and y["target_status"] == "behind"
    page = org["o"].get(reverse("owner:dashboard") + "?period=this_quarter&tp=quarter").content.decode()
    assert "Target achieved" in page and "Pipeline can reach target" in page
    r = org["o"].get(reverse("team:list") + "?period=this_quarter&tp=quarter&target=achieved")
    assert [row["user"] for row in r.context["rows"]] == [org["e1"]]


# =============================================================== team calendar
def _visit(user, cust, day, status="scheduled"):
    return Visit.objects.create(customer=cust, assigned_to=user, visit_date=day, start_time=datetime.time(10),
                                end_time=datetime.time(11), location="Site", status=status)


def test_team_calendar_scope_filters_and_statuses(org):
    v_done = _visit(org["e1"], org["cust"], TODAY - datetime.timedelta(days=2), "completed")
    v_missed = _visit(org["e1"], org["cust"], TODAY - datetime.timedelta(days=1))
    v_up = _visit(org["e2"], org["cust2"], TODAY + datetime.timedelta(days=2))
    Task.objects.create(title="Call back", assigned_to=org["e1"], due_date=TODAY, category="follow_up")
    from owner import calendar as cal

    start, end = TODAY - datetime.timedelta(days=5), TODAY + datetime.timedelta(days=5)
    everyone = cal.events(org["owner"], start, end)
    status = {e["url"]: e["status"] for e in everyone}
    assert status[v_done.get_absolute_url()] == "completed" and status[v_missed.get_absolute_url()] == "overdue"
    assert status[v_up.get_absolute_url()] == "upcoming"
    assert any(e["type"] == "follow_up" and e["status"] == "pending" for e in everyone)
    # one employee / one type
    only_e2 = cal.events(org["owner"], start, end, employee_ids=[org["e2"].pk])
    assert {e["url"] for e in only_e2} == {v_up.get_absolute_url()}
    assert all(e["type"] == "follow_up" for e in cal.events(org["owner"], start, end, types=["follow_up"]))
    # privacy: an engineer only sees their own entries, even when asking for someone else
    mine = cal.events(org["e1"], start, end, employee_ids=[org["e2"].pk])
    assert mine == []
    assert v_up.get_absolute_url() not in {e["url"] for e in cal.events(org["e1"], start, end)}
    for view in ("month", "list"):
        r = org["o"].get(reverse("owner:calendar") + f"?view={view}")
        assert r.status_code == 200 and "Overdue" in r.content.decode()
    r = org["c1"].get(reverse("owner:calendar") + f"?view=list&employee={org['e2'].pk}")
    assert v_up.customer.company_name not in r.content.decode()
    assert org["x"].get(reverse("owner:calendar")).status_code == 403


# =============================================================== finance switch
def test_finance_module_hide_block_and_restore(org):
    finance_urls = [reverse("orders:list"), reverse("invoicing:list"), reverse("invoicing:collections"),
                    reverse("reporting:report", args=["invoices_issued"]),
                    reverse("reporting:report", args=["confirmed_orders"])]
    for url in finance_urls:
        assert org["o"].get(url).status_code == 200, url
    assert org["c1"].post(reverse("owner:modules"), {}).status_code == 403
    assert org["d"].get(reverse("owner:modules")).status_code == 403
    r = org["o"].post(reverse("owner:modules"), {"approval_threshold": "0", "discount_approval_limit": "10"})
    assert r.status_code == 302 and not CompanyProfile.get().finance_enabled
    assert AuditLog.objects.filter(message__contains="Show the Finance module = False").exists()
    for c in ("o", "a", "d", "x", "c1"):
        for url in finance_urls:
            assert org[c].get(url).status_code == 403, (c, url)
        nav = org[c].get(reverse("core:dashboard")).context["crm_nav"]
        assert "Finance" not in [s["title"] for s in nav]
    reports = org["o"].get(reverse("reporting:index")).content.decode()
    assert "Invoices issued" not in reports and "Confirmed orders" not in reports and "Leads by source" in reports
    # roles keep their permissions; turning it on again restores access
    assert Role.objects.get(code=caps.ACCOUNTS).capabilities.filter(code="invoices.view").exists()
    org["o"].post(reverse("owner:modules"), {"finance_enabled": "on", "approval_threshold": "0",
                                             "discount_approval_limit": "10"})
    for url in finance_urls:
        assert org["o"].get(url).status_code == 200, url


# =============================================================== module dashboards
@pytest.mark.parametrize("module", ["leads", "visits", "customers", "pipeline", "opportunities", "projects",
                                    "quotations"])
def test_module_dashboards_open_for_allowed_roles(module, org):
    stage = LeadStage.first_open()
    Lead.objects.create(title="L", company_name="Dash Co", category="tender", stage=stage,
                        assigned_engineer=org["e1"])
    for c in ("o", "d", "c1"):
        r = org[c].get(reverse(f"dashboards:{module}") + "?period=this_year")
        assert r.status_code == 200, (c, module)
        assert r.context["cards"] and r.context["charts"]
    assert org["o"].get(reverse("dashboards:module", kwargs={"module": "nope"})).status_code == 404


def test_module_dashboard_figures_scope_and_drilldown(org):
    stage = LeadStage.first_open()
    for user, cat in ((org["e1"], "tender"), (org["e1"], "tender"), (org["e2"], "job_in_hand")):
        Lead.objects.create(title="L", company_name="Co", category=cat, stage=stage, assigned_engineer=user,
                            created_by=user)
    cards = {c["label"]: c for c in org["o"].get(reverse("dashboards:leads")).context["cards"]}
    assert cards["Leads created"]["value"] == 3 and cards["Tender"]["value"] == 2
    assert cards["Job in Hand"]["value"] == 1
    mine = {c["label"]: c for c in org["c1"].get(reverse("dashboards:leads")).context["cards"]}
    assert mine["Leads created"]["value"] == 2 and mine["Job in Hand"]["value"] == 0  # own leads only
    drill = org["o"].get(cards["Tender"]["url"])
    assert drill.status_code == 200 and drill.context["page"].paginator.count == 2
    assert org["x"].get(reverse("dashboards:leads")).status_code == 403


def test_period_presets_quarter_and_year():
    for today, preset, expect in [
        (datetime.date(2026, 5, 10), "this_quarter", (datetime.date(2026, 4, 1), datetime.date(2026, 6, 30))),
        (datetime.date(2026, 2, 10), "last_quarter", (datetime.date(2025, 10, 1), datetime.date(2025, 12, 31))),
        (datetime.date(2026, 7, 1), "this_year", (datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))),
        (datetime.date(2026, 7, 1), "last_year", (datetime.date(2025, 1, 1), datetime.date(2025, 12, 31))),
    ]:
        assert mon.period_for(preset, today=today)[:2] == expect


def test_demo_cleanup_removes_uploaded_quotation_files(org, monkeypatch):
    import io

    from django.core.management import call_command

    cust = Customer.objects.create(company_name="Demo: Test Removal LLC", code="CUS-70009")
    q = uploads.create_uploaded(customer=cust, salesperson=org["e1"], user=org["e1"], file=pdf(),
                                value=Decimal("100"), quotation_date=TODAY)
    uploads.upload_revision(q, user=org["e1"], file=pdf(), value=Decimal("90"), quotation_date=TODAY)
    real = uploads.create_uploaded(customer=org["cust"], salesperson=org["e1"], user=org["e1"], file=pdf(),
                                   value=Decimal("100"), quotation_date=TODAY)
    call_command("remove_demo_data", "--confirm", stdout=io.StringIO())
    assert not Quotation.objects.filter(pk=q.pk).exists()
    assert list(Quotation.objects.all()) == [real] and QuotationFile.objects.count() == 1


def test_calendar_meetings_come_from_communications_and_visits_stay_visits(org):
    from communications.models import Communication
    from owner import calendar as cal

    purpose, _ = LookupValue.objects.get_or_create(category="visit_purpose", value="Initial Meeting")
    v = _visit(org["e1"], org["cust"], TODAY)
    v.purpose = purpose
    v.save()
    m = Communication.objects.create(customer=org["cust"], employee=org["e1"], kind="meeting",
                                     direction="out", occurred_at=timezone.now(), subject="Price review")
    start, end = TODAY - datetime.timedelta(days=1), TODAY + datetime.timedelta(days=1)
    visits_only = cal.events(org["owner"], start, end, types=["visit"])
    meetings_only = cal.events(org["owner"], start, end, types=["meeting"])
    assert [e["url"] for e in visits_only] == [v.get_absolute_url()]
    assert [e["url"] for e in meetings_only] == [m.get_absolute_url()]
    assert meetings_only[0]["status"] == "completed"
    assert [e for e in cal.events(org["acc"], start, end) if e["type"] == "visit"] == []  # Accounts: no visits
