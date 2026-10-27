# Technoflow CRM — Project Status

Status on 27-Oct-2026: **all 8 phases delivered**. This page lists what was built in each phase, how it was
verified, and what is not done or not tested. "Tested" below means a check was actually run; the results
are the real results of the final run.

## 1. Phase checklist

The phase plan is the one in the Phase 1 document *"Technoflow CRM — Phase 1 Architecture & Plan"*.

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Architecture, data model, roles/permission matrix, workflows, plan | Done (separate document) |
| 2 | Foundation: project, settings, sign-in, lockout, password rules, users, roles & limits, capabilities, audit log, company settings, numbering, drop-down lists, branded layout | Done |
| 3 | Customers (+ contacts, duplicates, 360° view), leads (list, Kanban, assignment, stages, conversion), customer visits (calendar, week, completion), communication history, tasks & follow-ups | Done |
| 4 | Sales pipeline (list, Kanban, forecast), projects, quotations (lines, VAT, discounts, approval rules, Director approval, no self-approval, revisions with locking, PDF, sent/accepted/declined, expiry) | Done |
| 5 | Sales orders from accepted quotations, payment milestones, confirmation, invoices per milestone (gap-free numbers, over-invoicing blocked), payments, allocations, credit, reversals, statements, ageing, collections | Done |
| 6 | Targets & KPIs (10 KPIs, weights, scorecards, ranking), role dashboards with drill-down charts, 44 reports with Excel / CSV / PDF export | Done |
| 7 | Documents (private storage, validation, versions), notifications (in-app + optional e-mail, preferences), daily reminders, Excel/CSV import with preview, global search, optional two-step sign-in (authenticator app), settings for approvals, reminders, tax rates and stages | Done |
| 8 | Fictional demo data, automated tests, browser tests, PostgreSQL + Gunicorn rehearsal, deployment kit (Render, Nginx, systemd, backup/restore), manuals | Done |

## 2. Verification results (final run)

| Check | What it does | Result |
| --- | --- | --- |
| Automated tests (`python -m pytest`) on SQLite | 145 tests: sign-in, lockout, MFA, passwords, role limits, permissions per page per role, record scope, full workflow through the web forms, create/edit forms of every module, calculations, revisions, documents, imports, exports, every report in every format, KPIs, notifications, deployment settings | **145 passed** |
| Same 145 tests on PostgreSQL 16 | Same suite against a real PostgreSQL database | **145 passed** |
| Page crawl (`tools/crawl.py`) | Signs in as each demo role and opens every page reachable by links (lists, filters, details, edit forms, PDFs, exports, chart data), with demo data loaded | admin 293 pages, director 236, accounts 89, engineer 218, coordinator 200: **0 server errors, 0 links to forbidden pages** (dev and PostgreSQL) |
| Browser test (`tools/ui_smoke.py`, Chromium via Playwright) | Each role at desktop 1366 px and phone 390 px: sign-in, dashboard cards and charts, every menu page, no horizontal scrolling, search, no JavaScript errors; quotation form "Add line" and live totals; lead Kanban move; pipeline Kanban drag & drop; notification bell | **77/77 passed** (runserver + SQLite); **63/63 passed** on Gunicorn + PostgreSQL with production settings (demo.admin not present there by design) |
| Production build rehearsal | `build.sh` steps with `config.settings.prod` against PostgreSQL 16: `check --deploy`, `collectstatic`, `migrate`, first admin, demo users, demo data; Gunicorn serving; `/healthz/` with a foreign Host header; security headers (HSTS, X-Frame-Options, nosniff, Referrer-Policy) | **Passed** (one expected warning: W021 HSTS preload) |
| Backup and restore | `deploy/backup.sh` then a deliberate change, then `deploy/restore.sh` | **Passed**: data returned to the backed-up state, documents archive restored |
| Lint | pyflakes on all Python code | Clean (only star-import notices in settings files) |

### Business workflow (test `tests/test_workflow_web.py`)

Run through the actual pages as three different users (engineer, director, accounts):

Lead created → stage changed → converted to new customer + opportunity → quotation with two lines
(10 % line discount, 5 % VAT: 98,000 + 4,900 = 102,900) → submitted → engineer's own approval refused →
Director approves → approved quotation cannot be edited → PDF → sent → accepted → order with 30/70 milestones →
engineer cannot confirm → Director confirms (opportunity marked Won) → two invoices (30,870 + 72,030 = order
total), duplicate invoice for a milestone refused → partial payment → final payment with 130 over-payment kept as
credit → over-allocation refused → payment reversed (invoice back to partially paid) → statement, collections,
dashboard, report and Excel/CSV/PDF exports opened → dashboard figures checked: orders booked 98,000,
invoiced 102,900, collected 10,000, outstanding 92,900. **Passed.**

### Module verification (Step 3 of the brief)

✓ = covered by an automated test or the crawl/browser run · — = not applicable

| # | Module | Create | View | Edit | Delete / archive | Search & filter | Validation | Permissions | Errors | Phone layout |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Users & roles | ✓ | ✓ | ✓ | ✓ deactivate | ✓ | ✓ | ✓ | ✓ | ✓ |
| 2 | Customers | ✓ | ✓ | ✓ | ✓ archive / protected delete | ✓ | ✓ required, TRN duplicate | ✓ scope | ✓ | ✓ |
| 3 | Leads | ✓ | ✓ | ✓ stage, Kanban (edit form: crawl only) | ✓ archive | ✓ | ✓ lost reason | ✓ | ✓ | ✓ |
| 4 | Customer visits | ✓ | ✓ calendar, week | ✓ complete (reschedule: crawl only) | ✓ cancel | ✓ | ✓ notes, follow-up owner | ✓ coordinator for team | ✓ | ✓ |
| 5 | Pipeline & projects | ✓ | ✓ | ✓ stage, drag & drop (edit form: crawl only) | archive: crawl only | ✓ | ✓ lost reason | ✓ | ✓ | ✓ |
| 6 | Quotations | ✓ | ✓ | ✓ revisions | ✓ draft delete | ✓ | ✓ locking | ✓ no self-approval | ✓ | ✓ |
| 7 | Sales orders | ✓ | ✓ | milestone edit: crawl only | cancel: crawl only | ✓ | ✓ preset milestones | ✓ confirm | ✓ | ✓ |
| 8 | Invoices & payments | ✓ | ✓ | issue ✓ (draft edit form: crawl only) | ✓ reverse (never delete) | ✓ | ✓ over-invoice / over-allocate | ✓ | ✓ | ✓ |
| 9 | Targets & KPIs | ✓ | ✓ | ✓ weights | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| 10 | Tasks | ✓ | ✓ | ✓ edit, status, comments | delete: crawl only | ✓ | ✓ | ✓ | ✓ | ✓ |
| 11 | Communications | ✓ | ✓ | crawl only | delete: crawl only | ✓ | ✓ | ✓ | ✓ | ✓ |
| 12 | Documents | ✓ | ✓ | new version: crawl only | archive: crawl only | ✓ | ✓ type, magic bytes | ✓ private download | ✓ | ✓ |
| 13 | Dashboards, reports, import, search, notifications | ✓ | ✓ | — | — | ✓ | ✓ import preview | ✓ per report | ✓ | ✓ |

"Crawl only" means the page or form opened without error for each role (and the action is built on the same
tested services), but submitting it was not exercised by a test.

## 3. Bugs found and fixed during Phases 3–8 testing

- Edit pages of tasks, visits, communications, quotations and opportunities crashed for engineers and
  coordinators (combining a team-scoped DISTINCT query) — fixed in `core/related.py`.
- Order, invoice and statement pages linked Accounts / engineers to quotation, opportunity or payment pages
  their role cannot open — links now shown as plain text without the permission.
- Lead conversion failed when the opportunity data repeated the owner — fixed in the demo loader.
- Demo data loader required `demo.admin`, which cannot exist next to a real administrator — removed.
- Notification e-mail links had no site address on Render — `SITE_URL` now defaults to the Render address.
- (Phase 2 audit fixes are listed in the Phase 2 report: parameter crashes, numbering, self-reset, unlock,
  per-IP lockout, hidden department, profile crash, reporting loops.)

## 4. Not done, not tested, and limitations

| Item | Status |
| --- | --- |
| Sending real e-mails | Implemented with standard SMTP; verified only with Django's test mail backend. Needs your SMTP details (ADMIN_GUIDE §3) and a real test |
| Uploaded documents on Render's free plan | Files are lost on each deploy/restart; needs a paid web service with a persistent disk or your own server |
| Daily reminders on Render's free plan | No scheduler; they run on the first dashboard visit each day or with *Run reminders now* |
| WhatsApp / e-mail inbox integration | Not built; communications are logged manually |
| Accounting-system integration | Not built; use Excel exports |
| Multiple currencies | Each quotation/order/invoice has a currency, but dashboards and reports add amounts without exchange-rate conversion. Use one currency (AED), or read foreign-currency figures separately |
| Arabic text in PDFs | Not tested; the PDF engine (xhtml2pdf) has limited right-to-left support |
| Two-step sign-in secret | Stored in the database unencrypted (protected by database access control) |
| Real-time updates | Notifications appear on the next page load (no live push) |
| Load / performance testing | Not done; designed for ~10 users |
| Browsers | Tested in Chromium only (desktop and phone sizes); not tested in Safari or Firefox |
| Penetration test | Not done; security controls are covered by the automated tests listed above |

## 5. Before going live

1. Set `LOAD_DEMO_DATA=false` (or never run `load_demo_data`) and deactivate demo users.
2. Upgrade the Render database before its 30-day expiry, or move to your own server, and set up backups.
3. Decide document storage (persistent disk) and e-mail (SMTP), then test a password-reset e-mail.
4. Review Settings: company details and TRN (printed on PDFs), approval threshold and discount limit, tax
   rates, numbering formats, stages, drop-down lists.
5. Create the real users (limits 1 / 2 / 2 / 2 / 3) and ask everyone to turn on two-step sign-in.
6. Import existing customers and leads (Settings → Import data), checking the preview carefully.
