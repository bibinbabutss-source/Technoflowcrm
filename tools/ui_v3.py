"""
Browser check of the Oct-2026 features (Owner dashboard, approvals, team calendar, Finance switch, lead categories,
uploaded quotation revisions, module dashboards, searchable drop-downs) with Playwright, desktop and phone size.
  python manage.py runserver 127.0.0.1:8767   (fresh database with load_demo_users + load_demo_data)
  set DEMO_PW=<demo password>   then   python tools/ui_v3.py
"""
import os
import re
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("CRM_URL", "http://127.0.0.1:8767")
PW = os.environ["DEMO_PW"]
OUT = os.path.join("ui-screenshots", "v3")
os.makedirs(OUT, exist_ok=True)
results = []
STAMP = str(int(time.time()))[-6:]


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


def charts_ok(page):
    page.wait_for_timeout(700)
    return page.evaluate("""(() => { const cs = [...document.querySelectorAll('canvas[data-dash-chart]')];
        const empties = document.querySelectorAll('.card-body .tf-empty').length;
        return cs.every(c => window.Chart && Chart.getChart(c)) && (cs.length + empties) > 0; })()""")


def pdf_file(name, text):
    path = os.path.join(OUT, name)
    with open(path, "wb") as fh:
        fh.write(b"%PDF-1.4\n% UI test quotation " + text.encode() + b"\n%%EOF\n")
    return path


with sync_playwright() as p:
    b = p.chromium.launch()

    # ---------------- Owner: dashboard, approvals, calendar, modules (desktop + phone)
    for mobile in (False, True):
        tag = "owner" + ("-mobile" if mobile else "")
        ctx, page, errors = session(b, "demo.owner", mobile)
        page.goto(BASE + "/owner/")
        check(f"{tag}: Owner Dashboard opens", "Owner Dashboard" in page.content())
        check(f"{tag}: summary cards", page.locator(".tf-kpi").count() >= 7, page.locator(".tf-kpi").count())
        check(f"{tag}: target chart drawn", charts_ok(page))
        check(f"{tag}: employee table", page.locator("table tbody tr").count() >= 3)
        check(f"{tag}: dashboard fits screen", fits(page))
        page.screenshot(path=f"{OUT}/{tag}-dashboard.png", full_page=True)
        for tp in ("quarter", "year"):
            page.goto(BASE + f"/owner/?period=this_year&tp={tp}")
            check(f"{tag}: {tp}ly targets view", page.locator("a.btn-primary", has_text=tp.capitalize() + "ly")
                  .count() == 1)
        page.goto(BASE + "/owner/approvals/")
        check(f"{tag}: approvals list", page.locator(".tf-approval").count() >= 1, page.locator(".tf-approval").count())
        check(f"{tag}: approvals fit screen", fits(page))
        page.screenshot(path=f"{OUT}/{tag}-approvals.png", full_page=True)
        for view in ("month", "list"):
            page.goto(BASE + f"/owner/calendar/?view={view}")
            check(f"{tag}: calendar {view} view", page.locator("h1", has_text="Team Calendar").count() == 1)
            check(f"{tag}: calendar {view} fits", fits(page))
            page.screenshot(path=f"{OUT}/{tag}-calendar-{view}.png", full_page=True)
        check(f"{tag}: no JS errors", not errors, " | ".join(errors[:3]))
        ctx.close()

    # approve one request with a comment (desktop)
    ctx, page, errors = session(b, "demo.owner")
    page.goto(BASE + "/owner/approvals/")
    before = page.locator(".tf-approval").count()
    card = page.locator(".tf-approval").first
    number = card.locator("h2 a").inner_text().split(" ")[0]
    card.locator("textarea[name=comments]").fill("Approved in UI test")
    card.locator("button[value=approve]").click()
    page.wait_for_load_state("networkidle")
    check("owner: approve from Pending Approvals", page.locator(".tf-approval").count() == before - 1
          and "approved" in page.content().lower(), number)
    check("owner: decision listed under recent decisions", "Approved in UI test" in page.content())
    # calendar filters
    import datetime as _dt
    _t = _dt.date.today()
    rng = f"&start={_t - _dt.timedelta(days=45)}&end={_t + _dt.timedelta(days=45)}"
    page.goto(BASE + "/owner/calendar/?view=list&type=visit" + rng)
    types = set(page.locator("table tbody td:nth-child(3)").all_inner_texts())
    check("owner: calendar type filter", types <= {"Customer visits"} and len(types) == 1, types)
    page.goto(BASE + "/owner/calendar/?view=list" + rng)
    page.select_option("#cal-emp", label="Elliot Engineer")
    page.locator("form button[type=submit]", has_text="Apply").click()
    page.wait_for_load_state("networkidle")
    who = set(page.locator("table tbody td:nth-child(5)").all_inner_texts())
    check("owner: calendar employee filter", who <= {"Elliot Engineer"}, who)
    # Finance switch off -> menu gone, pages blocked -> on again
    page.goto(BASE + "/owner/modules/")
    page.uncheck("input[name=finance_enabled]")
    page.locator("button[type=submit]", has_text="Save").click()
    page.wait_for_load_state("networkidle")
    nav = page.locator(".tf-sidebar").inner_text()
    check("owner: Finance hidden from menu", "Sales Orders" not in nav and "Invoices" not in nav)
    r = page.goto(BASE + "/invoices/")
    check("owner: Finance pages blocked", r.status == 403, r.status)
    page.goto(BASE + "/owner/modules/")
    page.check("input[name=finance_enabled]")
    page.locator("button[type=submit]", has_text="Save").click()
    page.wait_for_load_state("networkidle")
    r = page.goto(BASE + "/invoices/")
    check("owner: Finance restored", r.status == 200 and "Invoices" in page.locator(".tf-sidebar").inner_text())
    errors.clear()
    # module dashboards with drill-down
    for module in ("leads", "visits", "customers", "pipeline", "opportunities", "projects", "quotations"):
        page.goto(BASE + f"/dashboards/{module}/?period=this_year")
        check(f"owner: {module} dashboard charts", charts_ok(page))
    page.goto(BASE + "/dashboards/leads/?period=this_year")
    page.locator("a.tf-kpi", has_text="Tender").click()
    page.wait_for_load_state("networkidle")
    check("owner: dashboard card drills down to filtered list", "category=tender" in page.url, page.url)
    page.screenshot(path=f"{OUT}/owner-leads-drilldown.png", full_page=True)
    check("owner: no JS errors (actions)", not errors, " | ".join(errors[:3]))
    ctx.close()

    # ---------------- Engineer: lead with category, uploaded quotation with revisions
    for mobile in (False, True):
        tag = "engineer" + ("-mobile" if mobile else "")
        ctx, page, errors = session(b, "demo.engineer", mobile)
        page.goto(BASE + "/leads/new/")
        check(f"{tag}: three category buttons", page.locator(".tf-pill").count() == 3)
        page.fill("input[name=title]", f"UI lead {STAMP}{'m' if mobile else ''}")
        page.check("input[name=customer_mode][value=new]")
        page.fill("input[name=company_name]", f"UI Prospect {STAMP}{'m' if mobile else ''} LLC")
        page.locator("button[type=submit]", has_text="Save").click()
        page.wait_for_load_state("networkidle")
        check(f"{tag}: category is required", "Choose the lead category" in page.content())
        page.locator("label.tf-pill", has_text="Purchase Enquiry").click()
        page.mouse.move(0, 0)
        page.wait_for_timeout(600)  # let the 0.15 s colour transition finish
        bg = page.locator("label.tf-pill", has_text="Purchase Enquiry").evaluate("e => getComputedStyle(e).backgroundColor")
        check(f"{tag}: chosen category is highlighted in its colour", bg == "rgb(201, 116, 26)", bg)
        page.screenshot(path=f"{OUT}/{tag}-lead-form.png", full_page=True)
        check(f"{tag}: lead form fits", fits(page))
        page.locator("button[type=submit]", has_text="Save").click()
        page.wait_for_load_state("networkidle")
        check(f"{tag}: lead saved with category", re.search(r"/leads/\d+/", page.url) and
              "Purchase Enquiry" in page.content(), page.url)
        check(f"{tag}: no JS errors", not errors, " | ".join(errors[:3]))
        ctx.close()

    ctx, page, errors = session(b, "demo.engineer")
    page.goto(BASE + "/quotations/")
    page.locator("a.btn-primary", has_text="Upload quotation").click()
    page.wait_for_load_state("networkidle")
    searchable = page.locator(".ts-wrapper").count()
    check("engineer: searchable drop-downs on the upload form", searchable >= 1, searchable)
    page.set_input_files("input[name=file]", pdf_file("orig.pdf", "original"))
    page.fill("input[name=external_number]", f"EXT-{STAMP}")
    page.fill("input[name=value]", "15000")
    cust = page.locator("select[name=customer]")
    if page.locator("#id_customer-ts-control").count():
        page.locator("#id_customer + .ts-wrapper .ts-control").click()  # what a user clicks: the visible box
        page.keyboard.type("Falcon")
        page.locator(".ts-dropdown .option", has_text="Falcon").first.click()
    else:
        cust.select_option(index=1)
    page.locator("button[type=submit]", has_text="Upload").click()
    page.wait_for_load_state("networkidle")
    check("engineer: quotation uploaded", re.search(r"/quotations/\d+/", page.url) and "Original" in page.content(),
          page.url)
    qurl = page.url.split("?")[0]
    for i in (1, 2):
        page.goto(qurl)
        page.locator("a", has_text="Upload revision").click()
        page.wait_for_load_state("networkidle")
        page.set_input_files("input[name=file]", pdf_file(f"r{i}.pdf", f"revision {i}"))
        page.fill("input[name=value]", str(15000 - i * 500))
        page.fill("textarea[name=notes]", f"UI revision {i}")
        page.locator("button[type=submit]", has_text="Upload revision").click()
        page.wait_for_load_state("networkidle")
        check(f"engineer: R{i} uploaded", f"R{i}" in page.content() and f"UI revision {i}" in page.content())
    page.locator("button", has_text="Mark as final").click()
    page.wait_for_load_state("networkidle")
    rows = page.locator(".card", has_text="Revision history").locator("tbody tr")
    check("engineer: revision history lists Original, R1, R2", rows.count() == 3, rows.count())
    check("engineer: final badge shown", page.locator(".badge-status", has_text="Final").count() >= 1)
    with page.expect_download() as dl:
        rows.nth(2).locator("a[aria-label^='Download']").click()
    check("engineer: earlier revision downloadable", dl.value.suggested_filename == "orig.pdf",
          dl.value.suggested_filename)
    page.screenshot(path=f"{OUT}/engineer-quotation-revisions.png", full_page=True)
    ctx2 = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
    check("engineer: no JS errors (quotations)", not errors, " | ".join(errors[:3]))
    ctx.close()

    ctx, page, errors = session(b, "demo.engineer", True)
    page.goto(qurl)
    check("engineer-mobile: quotation page fits", fits(page))
    page.screenshot(path=f"{OUT}/engineer-mobile-quotation.png", full_page=True)
    r = page.goto(BASE + "/owner/")
    check("engineer: Owner Dashboard refused", r.status == 403, r.status)
    errors.clear()
    ctx.close()
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
raise SystemExit(1 if failed else 0)
