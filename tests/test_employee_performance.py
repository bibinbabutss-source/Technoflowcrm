"""Employee Performance: figures from real records, periods, attribution, reconciliation and access control."""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts import capabilities as caps
from customers.models import Customer
from leads.models import Lead, LeadStage
from performance import monitoring as mon
from performance.models import DailyReport, KPIDefinition, SalesTarget
from sales.models import Opportunity, OpportunityStage
from tasks.models import Task
from visits.models import Visit

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


def at(d, hour=10):
    return timezone.make_aware(datetime.datetime.combine(d, datetime.time(hour)))


@pytest.fixture
def org(make_user):
    director = make_user(caps.DIRECTOR, first_name="Dana")
    coord = make_user(caps.COORDINATOR, first_name="Casey")
    e1 = make_user(caps.ENGINEER, first_name="Eli")
    e2 = make_user(caps.ENGINEER, first_name="Ema")
    coord.profile.team_members.add(e1.profile)  # Casey manages Eli only
    admin = make_user(caps.ADMIN)
    accounts = make_user(caps.ACCOUNTS)
    return {"director": director, "coord": coord, "e1": e1, "e2": e2, "admin": admin, "accounts": accounts}


def _data(org):
    """Known records: Eli has 2 leads (1 qualified), 1 completed + 1 cancelled + 1 missed visit, 2 won deals
    (100,000 + 50,000), 1 lost; Ema has 1 lead and 1 won deal of 30,000 last month."""
    e1, e2 = org["e1"], org["e2"]
    cust = Customer.objects.create(company_name="Perf Test LLC", assigned_engineer=e1)
    first = LeadStage.objects.filter(is_won=False, is_lost=False).order_by("order").first()
    qualified = LeadStage.objects.filter(is_qualified=True, is_won=False).first()
    Lead.objects.create(title="L1", company_name="A", stage=first, assigned_engineer=e1, created_by=e1)
    Lead.objects.create(title="L2", company_name="B", stage=qualified, assigned_engineer=e1, created_by=e1,
                        next_follow_up=TODAY - datetime.timedelta(days=1))
    Lead.objects.create(title="L3", company_name="C", stage=first, assigned_engineer=e2, created_by=e2)
    v = dict(customer=cust, start_time="09:00", end_time="10:00", location="Site")
    Visit.objects.create(assigned_to=e1, visit_date=TODAY, status="completed", meeting_notes="ok", **v)
    Visit.objects.create(assigned_to=e1, visit_date=TODAY, status="cancelled", **v)
    if TODAY.day > 1:  # a visit earlier this month, never completed = missed
        Visit.objects.create(assigned_to=e1, visit_date=TODAY - datetime.timedelta(days=1), status="scheduled", **v)
    won = OpportunityStage.objects.get(is_won=True)
    lost = OpportunityStage.objects.get(is_lost=True)
    o1 = Opportunity.objects.create(title="W1", customer=cust, stage=won, estimated_value=100000, assigned_engineer=e1)
    o2 = Opportunity.objects.create(title="W2", customer=cust, stage=won, estimated_value=50000, assigned_engineer=e1)
    o3 = Opportunity.objects.create(title="X1", customer=cust, stage=lost, estimated_value=9000, assigned_engineer=e1)
    o4 = Opportunity.objects.create(title="W3", customer=cust, stage=won, estimated_value=30000, assigned_engineer=e2)
    for o in (o1, o2, o3):
        Opportunity.objects.filter(pk=o.pk).update(closed_at=at(TODAY))
    last_month = TODAY.replace(day=1) - datetime.timedelta(days=3)
    Opportunity.objects.filter(pk=o4.pk).update(closed_at=at(last_month))
    Task.objects.create(title="Overdue follow-up", assigned_to=e1, category="follow_up",
                        due_date=TODAY - datetime.timedelta(days=2))
    return cust


def test_list_figures_match_records_and_totals_reconcile(org):
    _data(org)
    start, end, _ = mon.period_for("this_month")
    f = mon.list_figures([org["e1"].pk, org["e2"].pk], start, end)
    e1 = f[org["e1"].pk]
    assert e1["leads_created"] == 2 and e1["open_leads"] == 2
    assert e1["visits_completed"] == 1  # cancelled and missed visits never count as completed
    assert e1["deals_won"] == 2 and e1["deals_lost"] == 1 and e1["won_value"] == Decimal("150000.00")
    assert e1["pending_followups"] == 1 and e1["overdue_tasks"] == 1
    assert f[org["e2"].pk]["won_value"] == 0  # Ema's deal closed last month: outside the period
    rows = list(f.values())
    team = mon.totals(rows)
    assert team["won_value"] == sum(r["won_value"] for r in rows) == Decimal("150000.00")
    # company-wide figure from the same records (no double counting across employees)
    all_won = Opportunity.objects.filter(stage__is_won=True, closed_at__date__gte=start, closed_at__date__lte=end)
    assert sum(o.estimated_value for o in all_won) == team["won_value"]
    last = mon.period_for("last_month")
    assert mon.list_figures([org["e2"].pk], last[0], last[1])[org["e2"].pk]["won_value"] == Decimal("30000.00")


def test_employee_dashboard_sections(org):
    _data(org)
    start, end, _ = mon.period_for("this_month")
    d = mon.employee_dashboard(org["e1"], start, end)
    assert d["leads"]["created"] == 2 and d["leads"]["qualified_now"] == 1 and d["leads"]["new_now"] == 1
    assert len(d["leads"]["needs_followup"]) == 1
    assert d["visits"]["completed"] == 1 and d["visits"]["cancelled"] == 1
    if TODAY.day > 1:
        assert d["visits"]["missed"] == 1
    assert d["sales"]["won"] == 2 and d["sales"]["lost"] == 1
    assert d["sales"]["average_deal"] == Decimal("75000.00")
    assert d["followups"]["fu_overdue_now"] == 1 and d["followups"]["tasks_overdue_now"] == 1


def test_zero_values_and_no_target_are_safe(org):
    start, end, _ = mon.period_for("today")
    d = mon.employee_dashboard(org["e2"], start, end)
    assert d["leads"]["conversion_rate"] is None and d["sales"]["average_deal"] is None
    assert d["sales"]["achievement"] is None
    assert mon.achievement(Decimal(10), Decimal(0)) is None and mon.achievement(Decimal(0), None) is None
    assert mon.achievement(Decimal(50), Decimal(200)) == Decimal("25.0")


def test_target_achievement_uses_won_value_target(org, login):
    _data(org)
    kpi = KPIDefinition.objects.get(code="won_value")
    SalesTarget.objects.create(employee=org["e1"], kpi=kpi, period_type="month", period_start=TODAY.replace(day=1),
                               target_value=200000)
    start, end, _ = mon.period_for("this_month")
    f = mon.list_figures([org["e1"].pk], start, end)[org["e1"].pk]
    assert f["target"] == 200000 and f["achievement"] == Decimal("75.0")
    from reporting.metrics import kpi_actual
    assert kpi_actual("won_value", {org["e1"].pk}, start, end) == Decimal("150000.00")


def test_period_presets():
    monday = datetime.date(2026, 10, 26)  # a Monday
    wed = monday + datetime.timedelta(days=2)
    assert mon.period_for("today", wed)[:2] == (wed, wed)
    assert mon.period_for("yesterday", wed)[:2] == (wed - datetime.timedelta(days=1),) * 2
    assert mon.period_for("this_week", wed)[:2] == (monday, monday + datetime.timedelta(days=6))
    assert mon.period_for("last_week", wed)[:2] == (monday - datetime.timedelta(days=7),
                                                    monday - datetime.timedelta(days=1))
    assert mon.period_for("this_month", wed)[:2] == (datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
    assert mon.period_for("last_month", wed)[:2] == (datetime.date(2026, 9, 1), datetime.date(2026, 9, 30))
    s, e, p = mon.period_for("custom", wed, datetime.date(2026, 10, 9), datetime.date(2026, 10, 2))
    assert (s, e, p) == (datetime.date(2026, 10, 2), datetime.date(2026, 10, 9), "custom")  # swapped safely


def test_date_filter_in_page(org, login):
    _data(org)
    c = login(org["director"])
    r = c.get(reverse("team:list") + "?period=last_month")
    assert r.status_code == 200
    rows = {row["user"].pk: row for row in r.context["rows"]}
    assert rows[org["e2"].pk]["won_value"] == Decimal("30000.00") and rows[org["e1"].pk]["won_value"] == 0
    r = c.get(reverse("team:list") + f"?period=custom&start={TODAY}&end={TODAY}")
    rows = {row["user"].pk: row for row in r.context["rows"]}
    assert rows[org["e1"].pk]["visits_completed"] == 1


def test_access_rules(org, login):
    e1, e2, coord = org["e1"], org["e2"], org["coord"]
    # admin and director: all sales employees
    for who in ("admin", "director"):
        r = login(org[who]).get(reverse("team:list"))
        ids = {row["user"].pk for row in r.context["rows"]}
        assert {e1.pk, e2.pk, coord.pk, org["director"].pk} <= ids
        assert login(org[who]).get(reverse("team:employee", args=[e2.pk])).status_code == 200
    # coordinator (Sales Manager): own team only
    c = login(coord)
    ids = {row["user"].pk for row in c.get(reverse("team:list")).context["rows"]}
    assert ids == {coord.pk, e1.pk}
    assert c.get(reverse("team:employee", args=[e1.pk])).status_code == 200
    assert c.get(reverse("team:employee", args=[e2.pk])).status_code == 404
    # engineer: own dashboard only; the list redirects there; others' dashboards are refused
    e = login(e1)
    r = e.get(reverse("team:list"))
    assert r.status_code == 302 and r["Location"] == reverse("team:employee", args=[e1.pk])
    assert e.get(reverse("team:employee", args=[e1.pk])).status_code == 200
    assert e.get(reverse("team:employee", args=[e2.pk])).status_code == 404
    assert e.get(reverse("team:employee", args=[999999])).status_code == 404
    # accounts: no access at all
    assert login(org["accounts"]).get(reverse("team:list")).status_code == 403
    # export needs data.export; inactive employees hidden by default
    assert login(org["director"]).get(reverse("team:list") + "?export=xlsx").status_code == 200


def test_filters_search_and_sort(org, login):
    _data(org)
    org["e1"].profile.department = "Projects"
    org["e1"].profile.reporting_manager = org["director"].profile
    org["e1"].profile.save()
    c = login(org["director"])
    rows = c.get(reverse("team:list") + "?q=Eli").context["rows"]
    assert [r["user"].pk for r in rows] == [org["e1"].pk]
    rows = c.get(reverse("team:list") + "?department=Projects").context["rows"]
    assert [r["user"].pk for r in rows] == [org["e1"].pk]
    rows = c.get(reverse("team:list") + f"?manager={org['director'].pk}").context["rows"]
    assert [r["user"].pk for r in rows] == [org["e1"].pk]
    rows = list(c.get(reverse("team:list") + "?sort=won_value").context["rows"])
    assert rows[0]["user"].pk == org["e1"].pk
    org["e2"].is_active = False
    org["e2"].save()
    ids = {r["user"].pk for r in c.get(reverse("team:list")).context["rows"]}
    assert org["e2"].pk not in ids
    ids = {r["user"].pk for r in c.get(reverse("team:list") + "?status=inactive").context["rows"]}
    assert ids == {org["e2"].pk}
    assert c.get(reverse("team:list") + "?sort=bogus&period=nonsense&manager=abc").status_code == 200


# ------------------------------------------------------------------ daily reports
def _report_post(day, action="submit", **extra):
    data = {"report_date": day.isoformat(), "calls_followups": "Called 3 customers", "visits_outcomes": "",
            "quotations_prepared": "QT for Perf Test", "opportunities_progressed": "", "tasks_completed": "",
            "pending_work": "", "challenges": "", "next_day_plan": "Visit site B", "action": action,
            "entries-TOTAL_FORMS": "1", "entries-INITIAL_FORMS": "0", "entries-MIN_NUM_FORMS": "0",
            "entries-MAX_NUM_FORMS": "1000", "entries-0-kind": "call", "entries-0-description": "Called buyer",
            "entries-0-outcome": "Interested"}
    data.update(extra)
    return data


def test_daily_report_submit_edit_review_and_history(org, login):
    from core.models import AuditLog

    e = login(org["e1"])
    r = e.post(reverse("dailyreports:new"), _report_post(TODAY))
    assert r.status_code == 302
    rep = DailyReport.objects.get(employee=org["e1"])
    assert rep.status == "submitted" and rep.submitted_at and rep.created_by == org["e1"]
    assert rep.entries.count() == 1
    # second report for the same day is refused; future dates refused
    assert e.post(reverse("dailyreports:new"), _report_post(TODAY)).status_code == 200
    assert e.post(reverse("dailyreports:new"), _report_post(TODAY + datetime.timedelta(days=1))).status_code == 200
    assert DailyReport.objects.count() == 1
    # edit keeps history in the audit log
    e.post(reverse("dailyreports:edit", args=[rep.pk]), _report_post(TODAY, calls_followups="Called 4 customers",
                                                                     **{"entries-TOTAL_FORMS": "0"}))
    rep.refresh_from_db()
    assert rep.calls_followups == "Called 4 customers"
    log = AuditLog.objects.filter(action="update", object_repr__contains="Daily report").first()
    assert log and "calls_followups" in log.changes
    # another engineer cannot see it; the coordinator (manager) can and reviews it
    assert login(org["e2"]).get(rep.get_absolute_url()).status_code == 404
    c = login(org["coord"])
    page = c.get(rep.get_absolute_url())
    assert page.status_code == 200
    hist = page.context["history"]
    assert any(ch[0].startswith("Calls") and ch[2] == "Called 4 customers" for h in hist for ch in h["changes"])
    assert "Change history" in page.content.decode()
    c.post(rep.get_absolute_url(), {"review_comment": "Good"})
    rep.refresh_from_db()
    assert rep.status == "reviewed" and rep.reviewed_by == org["coord"]
    # reviewed reports are locked for the employee
    assert e.get(reverse("dailyreports:edit", args=[rep.pk])).status_code == 403
    # the employee cannot review their own report
    assert e.post(rep.get_absolute_url(), {"review_comment": "x"}).status_code == 403
    # summary for managers counts the self-reported lines, separately from CRM activity
    r = c.get(reverse("dailyreports:list") + "?period=this_month")
    s = {row["user"].pk: row for row in r.context["summary"]}
    assert s[org["e1"].pk]["submitted"] == 1


def test_drafts_are_private_and_deletable(org, login):
    e = login(org["e1"])
    e.post(reverse("dailyreports:new"), _report_post(TODAY, action="draft"))
    rep = DailyReport.objects.get()
    assert rep.status == "draft"
    r = login(org["director"]).get(reverse("dailyreports:list"))
    assert rep not in list(r.context["page"])  # managers do not see unsubmitted drafts
    assert login(org["e2"]).post(reverse("dailyreports:delete", args=[rep.pk])).status_code == 404
    assert e.post(reverse("dailyreports:delete", args=[rep.pk])).status_code == 302
    assert not DailyReport.objects.exists()


def test_imported_lead_counts_for_the_named_employee_on_its_real_date(org, login):
    """A lead imported by the director for Eli, dated last month, is Eli's — and last month's."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    c = login(org["director"])
    old = TODAY.replace(day=1) - datetime.timedelta(days=5)
    csv = (f"Lead title,Company name,Sales Engineer,Date received,Category\nImported L,Old Co LLC,{org['e1'].username},"
           f"{old.isoformat()},Tender\n").encode()
    c.post(reverse("reporting:import_start"), {"kind": "leads", "mode": "skip",
                                                   "file": SimpleUploadedFile("l.csv", csv, "text/csv")})
    from reporting.models import ImportBatch

    batch = ImportBatch.objects.get()
    assert batch.summary["new"] == 1, batch.results
    c.post(reverse("reporting:import_run", args=[batch.pk]))
    lead = Lead.objects.get(title="Imported L")
    assert lead.assigned_engineer == org["e1"] and lead.created_by == org["e1"]
    assert timezone.localtime(lead.created_at).date() == old
    this = mon.period_for("this_month")
    last = mon.period_for("last_month")
    assert mon.list_figures([org["e1"].pk], this[0], this[1])[org["e1"].pk]["leads_created"] == 0
    assert mon.list_figures([org["e1"].pk], last[0], last[1])[org["e1"].pk]["leads_created"] == 1
    assert mon.list_figures([org["director"].pk], last[0], last[1])[org["director"].pk]["leads_created"] == 0


def test_export_and_page_links_are_well_formed(make_user, login):
    """Regression: links built with {% querystring %} must not start with '??'."""
    from accounts import capabilities as caps

    from accounts.models import Role

    Role.objects.filter(code=caps.ENGINEER).update(max_accounts=50)
    admin = make_user(caps.ADMIN)
    for n in range(30):
        make_user(caps.ENGINEER)
    c = login(admin)
    for url in (reverse("team:list"), reverse("dailyreports:list")):
        body = c.get(url).content.decode()
        assert 'href="??' not in body, url
    body = c.get(reverse("team:list")).content.decode()
    assert 'href="?export=xlsx' in body and "page=2" in body
    r = c.get(reverse("team:list") + "?export=xlsx")
    assert r["Content-Type"].startswith("application/vnd.openxmlformats")


def test_drafts_hidden_from_managers_everywhere(make_user, login):
    from accounts import capabilities as caps
    from performance.models import DailyReport

    director, eng = make_user(caps.DIRECTOR), make_user(caps.ENGINEER)
    draft = DailyReport.objects.create(employee=eng, report_date=timezone.localdate(), status="draft",
                                       calls_followups="secret draft text")
    d = login(director)
    assert d.get(reverse("dailyreports:detail", args=[draft.pk])).status_code == 404
    page = d.get(reverse("team:employee", args=[eng.pk])).content.decode()
    assert reverse("dailyreports:detail", args=[draft.pk]) not in page
    own = login(eng).get(reverse("team:me"), follow=True).content.decode()
    assert reverse("dailyreports:detail", args=[draft.pk]) in own
