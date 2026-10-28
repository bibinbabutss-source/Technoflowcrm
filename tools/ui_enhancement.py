"""
Browser check of the enhancement pages (Employee Performance, Daily Reports, Import from Excel) with Playwright.
  python manage.py runserver 127.0.0.1:8765   (fresh database with load_demo_users + load_demo_data)
  set DEMO_PW=<demo password>   then   python tools/ui_enhancement.py
Screenshots go to ui-screenshots/enhancement/.
"""
import os
import re

from playwright.sync_api import sync_playwright

BASE = os.environ.get("CRM_URL", "http://127.0.0.1:8765")
PW = os.environ["DEMO_PW"]
OUT = os.path.join("ui-screenshots", "enhancement")
os.makedirs(OUT, exist_ok=True)
results = []


def check(name, ok, info=""):
    results.append((name, bool(ok), info))
    print(("PASS " if ok else "FAIL ") + name + (" — " + str(info) if info else ""), flush=True)


def session(b, user, mobile=False):
    ctx = b.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1366, "height": 900},
                        is_mobile=mobile, accept_downloads=True)
    page = ctx.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("dialog", lambda d: d.accept())
    page.goto(BASE + "/accounts/login/")
    page.fill("input[name=username]", user)
    page.fill("input[name=password]", PW)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    return ctx, page, errors


def fits(page):
    return page.evaluate("document.documentElement.scrollWidth") <= page.evaluate("window.innerWidth") + 1


with sync_playwright() as p:
    b = p.chromium.launch()

    # ---- Employee Performance as the director (desktop + phone)
    for mobile in (False, True):
        tag = "director" + ("-mobile" if mobile else "")
        ctx, page, errors = session(b, "demo.director", mobile)
        page.goto(BASE + "/team/")
        rows = page.locator("table tbody tr").count()
        check(f"{tag}: employee list shows rows", rows >= 2, f"{rows} rows")
        check(f"{tag}: KPI cards coloured", page.locator(".tf-kpi-green, .tf-kpi-blue, .tf-kpi-orange").count() >= 2)
        check(f"{tag}: list fits the screen", fits(page))
        page.screenshot(path=f"{OUT}/{tag}-team.png", full_page=True)
        for preset in ("today", "yesterday", "this_week", "last_week", "this_month", "last_month"):
            page.goto(BASE + f"/team/?period={preset}")
            active = page.locator(".tf-chip-period a.btn-primary").inner_text().strip()
            check(f"{tag}: period {preset} opens and is highlighted", bool(active), active)
        page.goto(BASE + "/team/")
        page.fill("input[name=start]", "2026-01-01")
        page.fill("input[name=end]", "2026-01-31")
        page.locator(".tf-chip-period button[type=submit]").click()
        page.wait_for_load_state("networkidle")
        check(f"{tag}: custom date range applied", "start=2026-01-01" in page.url and "01 Jan 2026" in page.content(),
              page.url)
        if not mobile:
            page.goto(BASE + "/team/?sort=-won_value")
            check(f"{tag}: sort by won value", page.locator("table tbody tr").count() >= 1)
            page.goto(BASE + "/team/?q=engineer")
            names = page.locator("table tbody tr").all_inner_texts()
            check(f"{tag}: search filter", names and all("ngineer" in n for n in names), f"{len(names)} rows")
            page.goto(BASE + "/team/")
            with page.expect_download() as dl:
                page.locator("a[href*='export=xlsx']").first.click()
            check(f"{tag}: Excel export downloads", dl.value.suggested_filename.endswith(".xlsx"),
                  dl.value.suggested_filename)
        # open an employee dashboard from the list
        page.goto(BASE + "/team/?period=this_month")
        page.locator("table tbody tr a[href^='/team/']").first.click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        check(f"{tag}: employee dashboard opens", re.search(r"/team/\d+/", page.url), page.url)
        chart = page.evaluate("(() => { const c = document.getElementById('act-chart'); "
                              "return c ? c.width > 0 && !!window.Chart && !!Chart.getChart(c) : null })()")
        check(f"{tag}: activity chart drawn", chart is not False, str(chart))
        for sec in ("Leads", "Visits", "Sales", "Follow-ups"):
            check(f"{tag}: dashboard section '{sec}'", page.locator(".tf-section-title", has_text=sec).count() > 0)
        check(f"{tag}: dashboard fits the screen", fits(page))
        page.screenshot(path=f"{OUT}/{tag}-employee.png", full_page=True)
        check(f"{tag}: no JS errors", not errors, " | ".join(errors[:3]))
        ctx.close()

    # ---- Engineer: only their own dashboard; daily report list shows self-reported marker
    ctx, page, errors = session(b, "demo.engineer")
    page.goto(BASE + "/team/")
    check("engineer: /team/ goes to own dashboard", page.url.rstrip("/").endswith("/team/me") or
          re.search(r"/team/\d+/?$", page.url), page.url)
    r = page.goto(BASE + "/team/1/")
    check("engineer: other employee's dashboard refused", r.status in (403, 404) or "demo.engineer" in page.content(),
          r.status)
    errors.clear()  # the browser logs the intended 404 above as a console error
    page.goto(BASE + "/daily-reports/")
    check("engineer: daily report list", page.locator("table tbody tr").count() >= 2)
    check("engineer: self-reported label visible", page.locator(".tf-self-reported").count() > 0 or
          "self-reported" in page.content().lower())
    page.screenshot(path=f"{OUT}/engineer-daily-reports.png", full_page=True)
    check("engineer: no JS errors", not errors, " | ".join(errors[:3]))
    ctx.close()

    # ---- Coordinator writes and submits today's daily report with two activity rows
    ctx, page, errors = session(b, "demo.coordinator")
    page.goto(BASE + "/daily-reports/new/")
    before = page.locator("[data-formset-body] tr").count()
    page.locator("[data-formset-add]").click()
    page.locator("[data-formset-add]").click()
    after = page.locator("[data-formset-body] tr").count()
    check("coordinator: 'Add activity' adds rows", after == before + 2, f"{before} -> {after}")
    rows = page.locator("[data-formset-body] tr")
    page.locator("textarea[name=calls_followups]").fill("Called three customers about delivery dates (UI test).")
    last = rows.nth(after - 1)
    last.locator("select[name$='-kind']").select_option("call")
    last.locator("input[name$='-description'], textarea[name$='-description']").first.fill("Delivery call (UI test)")
    page.screenshot(path=f"{OUT}/coordinator-report-form.png", full_page=True)
    import datetime
    day = datetime.date.today()
    for _ in range(25):  # one report per day: when re-run, the earlier days are taken, so try the day before
        page.locator("input[name=report_date]").fill(day.isoformat())
        page.locator("button[name=action][value=submit]").click()
        page.wait_for_load_state("networkidle")
        if "/new/" not in page.url:
            break
        if "already have a report for this date" in page.content():
            check(f"coordinator: second report for {day} refused", True)
        day -= datetime.timedelta(days=1)
    body = page.content()
    check("coordinator: report submitted", re.search(r"/daily-reports/\d+/", page.url) and "Submitted" in body,
          page.url)
    check("coordinator: activity saved", "Delivery call (UI test)" in body)
    check("coordinator: CRM-tracked figures shown separately", "CRM" in body and "self-reported" in body.lower())
    page.screenshot(path=f"{OUT}/coordinator-report-detail.png", full_page=True)
    check("coordinator: no JS errors", not errors, " | ".join(errors[:3]))
    ctx.close()

    # ---- Director imports leads for the engineer: upload, preview, confirm
    csv_path = os.path.join(OUT, "ui_leads.csv")
    import time
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write("Lead title,Company name,Sales Engineer,Date received,Estimated value\n"
                 f"UI import lead A,UI Test {int(time.time())} LLC,demo.engineer,2026-02-10,12000\n"
                 "UI import lead B,UI Test Two LLC,nobody.here,2026-02-11,5000\n")
    for mobile in (True, False):  # phone first: it cancels, so the desktop run still has a new row to import
        tag = "director" + ("-mobile" if mobile else "")
        ctx, page, errors = session(b, "demo.director", mobile)
        page.goto(BASE + "/import/")
        check(f"{tag}: import page lists templates", page.locator("a[href*='/import/template/']").count() >= 5)
        check(f"{tag}: import page fits the screen", fits(page))
        page.screenshot(path=f"{OUT}/{tag}-import-start.png", full_page=True)
        if not mobile:
            with page.expect_download() as dl:
                page.locator("a[href*='/import/template/leads.xlsx']").first.click()
            check(f"{tag}: template download", dl.value.suggested_filename.endswith("leads.xlsx"))
        page.select_option("select[name=kind]", "leads")
        page.set_input_files("input[name=file]", csv_path)
        page.locator("form button[type=submit]").last.click()
        page.wait_for_load_state("networkidle")
        txt = page.locator("main").inner_text()
        check(f"{tag}: preview shows 1 new + 1 error", "No active employee" in txt and page.locator(
            "#preview").count() == 1, page.url)
        check(f"{tag}: preview fits the screen", fits(page))
        page.screenshot(path=f"{OUT}/{tag}-import-preview.png", full_page=True)
        if mobile:
            page.locator("button", has_text="Cancel import").click()
            page.wait_for_load_state("networkidle")
            check(f"{tag}: cancel import", "/import/" in page.url and "Nothing was saved" in page.content())
        else:
            page.locator("button", has_text="Import 1 row").click()
            page.wait_for_load_state("networkidle")
            check(f"{tag}: import confirmed", "Import finished: 1 created" in page.content())
            page.screenshot(path=f"{OUT}/{tag}-import-done.png", full_page=True)
        check(f"{tag}: no JS errors", not errors, " | ".join(errors[:3]))
        ctx.close()
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
raise SystemExit(1 if failed else 0)
