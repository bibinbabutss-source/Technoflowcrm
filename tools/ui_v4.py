"""
Browser check of the v4 sales flow with Playwright: customer-first lead, meetings, Move to Sales Pipeline,
meetings on the opportunity, and the company history ("View as a company").
  python manage.py runserver 127.0.0.1:8765 --noreload   (fresh database with load_demo_users + load_demo_data)
  set DEMO_PW=<demo password>   then   python tools/ui_v4.py
Screenshots go to ui-screenshots/v4/.
"""
import datetime
import os
import re
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("CRM_URL", "http://127.0.0.1:8765")
PW = os.environ["DEMO_PW"]
OUT = os.path.join("ui-screenshots", "v4")
os.makedirs(OUT, exist_ok=True)
results = []
TODAY = datetime.date.today()
STAMP = str(int(time.time()))[-6:]
OPP_LIST = os.environ.get("OPP_LIST", "/pipeline/")


def check(name, ok, info=""):
    results.append((name, bool(ok), info))
    print(("PASS " if ok else "FAIL ") + name + (" — " + str(info) if info else ""), flush=True)


def session(b, user, mobile=False):
    ctx = b.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1366, "height": 900},
                        is_mobile=mobile)
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


def submit(page, selector="form button[type=submit].btn-primary"):
    page.locator(selector).last.click()
    page.wait_for_load_state("networkidle")


def choose_customer(page, name):
    """Pick from the customer list, whether or not it became a searchable (Tom Select) list."""
    value = page.evaluate("""(name) => { const s = document.getElementById('id_customer');
        const o = [...s.options].find(o => o.text.includes(name)); return o ? o.value : null }""", name)
    if value is None:
        return False
    if page.locator("#id_customer.tomselected").count():
        page.evaluate("(v) => document.getElementById('id_customer').tomselect.setValue(v)", value)
    else:
        page.select_option("#id_customer", value)
    return True


def add_meeting(page, days_ago, summary, points, follow_days):
    page.locator("a", has_text="Add meeting").first.click()
    page.wait_for_load_state("networkidle")
    page.fill("#id_meeting_date", (TODAY - datetime.timedelta(days=days_ago)).isoformat())
    page.select_option("#id_meeting_type", "in_person")
    page.fill("#id_summary", summary)
    page.fill("#id_points_discussed", points)
    page.fill("#id_next_action", "Send the offer")
    page.fill("#id_next_follow_up", (TODAY + datetime.timedelta(days=follow_days)).isoformat())
    submit(page)


with sync_playwright() as p:
    b = p.chromium.launch()

    # ---- 1. Engineer: new customer + lead, two meetings, move to pipeline, meeting on the opportunity
    ctx, page, errors = session(b, "demo.engineer")
    page.goto(BASE + "/leads/new/")
    check("lead form: customer step shown first", page.locator(".card-header").first.inner_text().startswith("1."))
    page.check("input[name=customer_mode][value=new]")
    hidden = page.evaluate("document.getElementById('id_customer').closest('.col-md-6, .col-12').hidden")
    check("lead form: picker hidden for a new customer", hidden is True)
    page.check("input[name=customer_mode][value=existing]")
    shown = not page.evaluate("document.getElementById('id_customer').closest('.col-md-6, .col-12').hidden")
    check("lead form: picker shown for an existing customer", shown)
    page.check("input[name=customer_mode][value=new]")
    company = f"UI Flow {STAMP} LLC"
    page.locator("label", has_text="Tender").first.click()
    page.fill("#id_title", "Cooling tower retrofit")
    page.fill("#id_company_name", company)
    page.fill("#id_contact_person", "Test Contact")
    page.fill("#id_phone", "+971 50 000 " + STAMP[-4:])
    page.screenshot(path=f"{OUT}/lead-form-new-customer.png", full_page=True)
    submit(page)
    check("lead saved with a new customer", re.search(r"/leads/\d+/$", page.url) and company in page.content(),
          page.url)
    lead_url = page.url
    check("lead page: customer linked", page.locator("dd a", has_text=company).count() > 0)
    check("lead page: Move to Sales Pipeline button", page.locator("a", has_text="Move to Sales Pipeline").count() == 1)
    add_meeting(page, 6, "First meeting with the facilities manager", "Tower is 15 years old\nWants a quote", 3)
    check("meeting 1 recorded", page.url.startswith(lead_url) and "First meeting with the facilities manager"
          in page.content(), page.url)
    add_meeting(page, 2, "Site walk with the technical team", "Access from the roof\nWork on Fridays", 5)
    check("meeting 2 recorded", page.locator(".tf-meeting").count() == 2)
    check("meeting points listed as bullets", page.locator(".tf-meeting li", has_text="Access from the roof").count() == 1)
    page.screenshot(path=f"{OUT}/lead-with-meetings.png", full_page=True)

    page.locator("a", has_text="Move to Sales Pipeline").first.click()
    page.wait_for_load_state("networkidle")
    body = page.content()
    check("move page: customer already chosen", company in body and "Link to an existing customer" not in body)
    check("move page: meetings so far = 2", "<strong>2</strong>" in body)
    page.fill("#id_opp_title", "Cooling tower retrofit")
    page.fill("#id_opp_value", "85000")
    page.fill("#id_opp_probability", "40")
    page.screenshot(path=f"{OUT}/move-to-pipeline.png", full_page=True)
    submit(page)
    check("opportunity opened after the move", re.search(r"/pipeline/\d+/", page.url) or "/opportunit" in page.url,
          page.url)
    check("steps bar shown", page.locator(".tf-steps li").count() == 6)
    check("meetings before the pipeline carried over", "2 before the pipeline" in page.content())
    add_meeting(page, 0, "Commercial discussion", "Payment terms\nDelivery 6 weeks", 4)
    check("meeting on the opportunity", "1 in the pipeline" in page.content() and page.locator(".tf-meeting").count() == 3)
    page.screenshot(path=f"{OUT}/opportunity-meetings.png", full_page=True)
    opp_url = page.url

    # edit a meeting
    page.locator(".tf-meeting a[href*='/meetings/']").first.click()
    page.wait_for_load_state("networkidle")
    page.fill("#id_summary", "Commercial discussion (edited)")
    submit(page)
    check("meeting edited", "Commercial discussion (edited)" in page.content())

    # opportunities list shows the meetings count
    page.goto(BASE + OPP_LIST + "?q=Cooling+tower+retrofit")
    row = page.locator("table tbody tr", has_text="Cooling tower retrofit").first.inner_text()
    check("opportunity list: Meetings column", "meetings" in page.locator("table thead").inner_text().lower()
          and re.search(r"\b3\b", row), row[:120])
    check("engineer: no JS errors so far", not errors, " | ".join(errors[:3]))

    # ---- 2. Company history from the dashboard
    page.goto(BASE + "/")
    page.fill("#company-view-q", company)
    page.locator(".tf-company-view button[type=submit]").click()
    page.wait_for_load_state("networkidle")
    check("dashboard 'View as a company' opens the history", "/history/" in page.url and company in page.content(),
          page.url)
    meetings_total = page.locator("[data-meetings-total]").inner_text().strip()
    check("history: 3 meetings counted", meetings_total == "3", meetings_total)
    check("history: journey shows the move", page.locator(".tf-journey li.done", has_text="Moved").count() == 1)
    check("history: all meetings table", page.locator("#all-meetings tbody tr").count() == 3)
    check("history: timeline filled", page.locator("#timeline .tf-timeline-item").count() >= 4)
    page.screenshot(path=f"{OUT}/company-history.png", full_page=True)

    # ---- 3. Lead for an existing customer (from the customer page)
    page.goto(BASE + "/customers/history/?q=" + company.replace(" ", "+"))
    page.locator("a", has_text="Customer page").click()
    page.wait_for_load_state("networkidle")
    page.locator("a", has_text="Add lead").first.click()
    page.wait_for_load_state("networkidle")
    sel = page.evaluate("document.getElementById('id_customer').value")
    check("add lead from customer page: customer preselected", sel != "", sel)
    page.locator("label", has_text="Purchase Enquiry").first.click()
    page.fill("#id_title", "Spare pumps")
    submit(page)
    body = page.content()
    if "Similar open leads" in body:
        page.check("#id_confirm_duplicates")
        submit(page)
    check("second lead saved for the same customer", re.search(r"/leads/\d+/$", page.url) and company in
          page.content(), page.url)
    page.goto(BASE + "/leads/new/")
    check("existing customer can be searched", choose_customer(page, "Falcon Ridge"))
    check("engineer: no JS errors", not errors, " | ".join(errors[:3]))
    ctx.close()

    # ---- 4. Phone width
    ctx, page, errors = session(b, "demo.director", mobile=True)
    page.goto(BASE + "/customers/history/")
    check("phone: company list fits", fits(page))
    page.locator(".list-group-item").first.click()
    page.wait_for_load_state("networkidle")
    check("phone: history page fits", fits(page))
    page.screenshot(path=f"{OUT}/phone-history.png", full_page=True)
    page.goto(BASE + "/leads/new/")
    check("phone: lead form fits", fits(page))
    page.goto(BASE + "/")
    check("phone: dashboard company box fits", fits(page) and page.locator("#company-view-q").is_visible())
    check("director phone: no JS errors", not errors, " | ".join(errors[:3]))
    ctx.close()

    # ---- 5. Accounts cannot record meetings
    ctx, page, errors = session(b, "demo.accounts")
    page.goto(BASE + "/")
    check("accounts: dashboard opens", page.locator("h1").count() > 0)
    r = page.goto(BASE + "/meetings/new/lead/1/")
    check("accounts: meeting form refused", r.status in (403, 404), r.status)
    ctx.close()
    b.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
raise SystemExit(1 if failed else 0)
