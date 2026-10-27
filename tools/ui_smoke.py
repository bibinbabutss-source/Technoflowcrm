"""
Browser check of the running CRM with Playwright (all roles, desktop and phone size).
  pip install playwright && python -m playwright install chromium
  python manage.py runserver 127.0.0.1:8765        (with load_demo_users + load_demo_data)
  set DEMO_PW=<demo password>   then   python tools/ui_smoke.py
"""
import os, re
from playwright.sync_api import sync_playwright
BASE = os.environ.get("CRM_URL", "http://127.0.0.1:8765")
PW = os.environ["DEMO_PW"]
OUT = "ui-screenshots"
import os; os.makedirs(OUT, exist_ok=True)
results = []
def check(name, ok, info=""):
    results.append((name, ok, info)); print(("PASS " if ok else "FAIL ") + name + (" — " + info if info else ""), flush=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    for role in ["admin", "director", "accounts", "engineer", "coordinator"]:
        for mobile in (False, True):
            ctx = b.new_context(viewport={"width": 390, "height": 844} if mobile else {"width": 1366, "height": 900},
                                is_mobile=mobile)
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE + "/accounts/login/")
            page.fill("input[name=username]", "demo." + role)
            page.fill("input[name=password]", PW)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle")
            tag = f"{role}{'-mobile' if mobile else ''}"
            check(f"{tag}: signed in to dashboard", page.url.rstrip("/") == BASE, page.url)
            cards = page.locator(".tf-stat").count()
            check(f"{tag}: dashboard cards", cards >= 4, f"{cards} cards")
            page.wait_for_timeout(1200)
            canv = page.locator("canvas[data-chart]")
            n = canv.count()
            empties = page.locator(".card-body .tf-empty").count()
            check(f"{tag}: charts rendered", n + empties > 0 and not any("Chart" in e for e in errors), f"{n} canvases, {empties} empty-state")
            sw = page.evaluate("document.documentElement.scrollWidth"); vw = page.evaluate("window.innerWidth")
            check(f"{tag}: no horizontal page scroll", sw <= vw + 1, f"{sw} vs {vw}")
            page.screenshot(path=f"{OUT}/{tag}-dashboard.png", full_page=False)
            # visit every sidebar link
            links = page.eval_on_selector_all("a.tf-nav-link", "els => els.map(e => e.getAttribute('href'))")
            bad = []
            for href in links:
                resp = page.goto(BASE + href)
                if resp.status != 200: bad.append(f"{href} {resp.status}")
                sw = page.evaluate("document.documentElement.scrollWidth"); vw = page.evaluate("window.innerWidth")
                if sw > vw + 1: bad.append(f"{href} overflows {sw}>{vw}")
            check(f"{tag}: {len(links)} menu pages open, fit the screen", not bad, "; ".join(bad))
            # global search
            page.goto(BASE + "/search/?q=Demo")
            check(f"{tag}: global search", page.locator("main").inner_text().count("Demo") > 0)
            check(f"{tag}: no JS errors", not errors, " | ".join(errors[:3]))
            ctx.close()

    # interactive checks as engineer (desktop)
    ctx = b.new_context(viewport={"width": 1366, "height": 900}); page = ctx.new_page()
    errors = []; page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/accounts/login/"); page.fill("input[name=username]", "demo.engineer"); page.fill("input[name=password]", PW); page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    # quotation create: add a line row and see live totals
    page.goto(BASE + "/quotations/new/")
    rows0 = page.locator("[data-line]").count()
    btn = page.locator("[data-formset-add]").first
    btn.click()
    rows1 = page.locator("[data-line]").count()
    check("quotation form: Add line adds a row", rows1 == rows0 + 1, f"{rows0}->{rows1}")
    first = page.locator("[data-line]").first
    first.locator("textarea, input[name$='description']").first.fill("Test item")
    first.locator("input[name$='quantity']").fill("2")
    first.locator("input[name$='unit_price']").fill("1000")
    page.wait_for_timeout(300)
    body = page.locator("main").inner_text()
    check("quotation form: live total preview", "2,100.00" in body or "2100.00" in body, re.findall(r"[\d,]+\.\d\d", body)[-4:].__str__())
    page.screenshot(path=f"{OUT}/quotation-form.png", full_page=True)
    # kanban move via dropdown
    page.goto(BASE + "/leads/kanban/")
    page.screenshot(path=f"{OUT}/leads-kanban.png", full_page=False)
    check("lead kanban shows cards", page.locator(".tf-kcard").count() > 0)
    # move the first card with the dropdown (keyboard-accessible alternative to drag & drop)
    first_col = page.locator(".tf-kcol").first
    before = first_col.locator(".tf-kcard").count()
    card = first_col.locator(".tf-kcard").first
    sel = card.locator("select[data-move]")
    opt = sel.locator("option").nth(1).get_attribute("value")
    sel.select_option(opt)
    page.wait_for_load_state("networkidle"); page.wait_for_timeout(800)
    page.goto(BASE + "/leads/kanban/")
    after = page.locator(".tf-kcol").first.locator(".tf-kcard").count()
    check("lead kanban: move card to next stage", after == before - 1, f"{before}->{after}")
    # drag and drop on the pipeline board
    page.goto(BASE + "/pipeline/kanban/")
    cols = page.locator(".tf-kcol")
    src = None
    for i in range(cols.count()):
        if cols.nth(i).locator(".tf-kcard").count():
            src = i; break
    if src is not None:
        tgt = (src + 1) % cols.count()
        n_t = cols.nth(tgt).locator(".tf-kcard").count()
        cols.nth(src).locator(".tf-kcard").first.drag_to(cols.nth(tgt))
        page.wait_for_load_state("networkidle"); page.wait_for_timeout(800)
        page.goto(BASE + "/pipeline/kanban/")
        check("pipeline kanban: drag & drop moves an opportunity", page.locator(".tf-kcol").nth(tgt).locator(".tf-kcard").count() == n_t + 1)
    # bell dropdown
    page.goto(BASE + "/")
    page.click(".tf-bell")
    check("notification bell opens", page.locator(".dropdown-menu.show").count() > 0)
    check("engineer interactive pages: no JS errors", not errors, " | ".join(errors[:3]))
    ctx.close(); b.close()
fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)}/{len(results)} UI checks passed")
