# Technoflow CRM — Enhancement Report (Employee Performance, Daily Reports, Excel Import Center)

Date: 28-Oct-2026 · Builds on the existing CRM; nothing was removed or replaced.

> **Live site status:** the online CRM (https://technoflow-crm.onrender.com) has **not** been updated.
> This package has been tested locally only. Follow section 8 to deploy it after backing up the database.

---

## 1. What was added

### 1.1 Employee Performance (menu: Work → Employee Performance, address `/team/`)
- **Employee list** with, per employee: leads created, open leads (now), visits completed, quotations created,
  deals won / lost, won value, monthly target with a progress bar and achievement %, pending follow-ups,
  overdue tasks and last CRM activity.
- **Filters:** search (name or employee ID), employee, designation, department, reporting manager, active /
  inactive / all. **Sorting** by any figure. **Export** to Excel or CSV (needs the export permission).
- **Periods:** Today, Yesterday, This week, Last week, This month, Last month and Custom (from–to).
  Weeks run Monday–Sunday and all dates are Asia/Dubai.
- **Individual dashboard** (click an employee):
  - summary cards and a monthly-target bar;
  - an activity chart that shows daily bars for periods up to 62 days and monthly bars for longer periods;
  - sections for Leads, Customer visits, Sales and Follow-ups/tasks, plus that employee's daily reports.
- Totals row equals the sum of the rows (each record counts for one employee only, see section 4).

### 1.2 Daily Work Reports (menu: Work → Daily Reports, address `/daily-reports/`)
- **Writing a report.** Each employee writes one report per working day, covering:
  - calls and follow-ups, visits and outcomes, quotations, opportunities, tasks completed;
  - pending work, challenges, and the next-day plan;
  - optional activity rows (type, customer, lead, what was done, outcome).
- **Who and when.** The employee and the submitted time are recorded automatically and cannot be typed in.
- **Drafts.** An employee can save a report as a draft first. Drafts are private: managers cannot see them
  in lists, on dashboards or by opening the address.
- **Edits and history.** Reports can be edited until a manager reviews them. Every change is kept in the
  audit log with old and new values, and the report page shows this history in a "Change history" panel.
- **Manager review.** A manager can mark a report as reviewed and add a comment. After that, the report is locked.
- **Weekly and monthly summary.** For each employee the summary shows reports submitted and working days
  (Mon–Fri) missing.
- **Self-reported vs CRM-tracked.** A yellow "Self-reported by the employee — not independently verified"
  banner sits next to a separate panel, **"Recorded by the CRM on this day"**, which holds the figures taken
  from CRM records. The two are never mixed.

### 1.3 Excel Import Center (menu: Import from Excel, address `/import/`)
- **Five record types:**
  - customers;
  - sales leads;
  - customer visits;
  - follow-ups and tasks;
  - opportunities and completed sales.
- **Steps:**
  1. Download the template. Each has a Data sheet and an Instructions sheet listing the allowed values.
  2. Upload the file.
  3. Check the automatic column matching.
  4. Look at the preview, which shows each row as New, Update, Duplicate or Error, with the reason and the Excel row number.
  5. Confirm, then read the report.
  6. Download the rows that were not imported as a CSV, with a reason column, to correct them and upload again.
- **Nothing is saved before you confirm.** The import runs as **one transaction**: if anything fails, nothing is saved.
- **Duplicate handling** — you choose one of three options:
  - **Import new records, skip duplicates** (the default);
  - **Import new records and update reliable matches**;
  - **Only update reliable matches**.
- **What counts as a reliable match:**
  - Customers: CRM code, TRN, your own Reference, or the same email **and** phone.
  - Other records: their CRM code or your Reference.
- **Name-only matches are never updated.** A row whose company name matches but nothing else does is shown
  as a possible duplicate and skipped.
- **Empty cells never blank existing values.** A customer's name is never changed by an import.
- **Re-uploading the same file adds nothing.** Every imported row's reference or fingerprint is stored, so
  completed-sales revenue is never counted twice.
- **Ownership comes from the file.** The CRM uses the Employee / Sales Engineer column, matched by username,
  email or employee ID.
  - Salespeople import for themselves only. A row naming someone else is refused, not changed.
  - Administrators must name the employee. Nothing is attributed to the person uploading the file by default.
- **Historical dates are kept:**
  - date received for leads;
  - visit date, with the completed time on that date;
  - completed date for tasks;
  - closing date for won and lost deals.

  The CRM does **not** invent call or activity logs for the past.
- **Completed sales:**
  - a deal is Won only when the Status / stage column says so (Won, Closed won, Completed, Sold). An amount
    alone never makes a sale;
  - Won and Lost deals need a closing date that is not in the future;
  - Lost deals need a reason.
- **Limits:**
  - .xlsx or .csv only, checked by content as well as name (a renamed text file is refused);
  - at most 5 MB, 2,000 rows and 60 columns;
  - formulas are never evaluated;
  - errors shown to users never include server paths or technical details.

### 1.4 Passwords
- Passwords are still stored only as secure Django hashes. **No screen, export, report or log shows a password**,
  and no "reveal password" button exists. Tests check that neither the passwords nor their hashes appear on
  any of the new pages or exports.
- New: **"Email a password-reset link"** on each user's page (Settings → Users).
  - The employee receives a one-time link that expires, and sets their own password.
  - The action is written to the audit log.
  - This needs the e-mail (SMTP) settings to be filled in on the server.
  - The existing "Reset password" (temporary password) option is unchanged.
- No credential storage was added.

### 1.5 Look and feel
- Colour-coded KPI cards (green, blue, orange, red, brand) and initials avatars.
- Progress bars and period chips.
- Statuses always show text and an icon as well as colour.
- All new pages were checked at desktop (1366 px) and phone (390 px) widths, with no sideways page scrolling.

---

## 2. Roles and permissions

Your request named four roles. The CRM already has five, and they map as follows:

| Your role | CRM role | Can see |
|---|---|---|
| Owner / Admin | **System Administrator** | Everyone; all settings; send reset links; import for any employee |
| Sales Director | **Sales Director** | Everyone in sales; review reports; import for any employee |
| Sales Manager | **Sales Coordinator** (team scope) | Their team (team members and direct reports); review their reports; import for their team (not opportunities) |
| Salesperson | **Sales Engineer** | Only their own dashboard, own reports, own imports |
| — | Accounts | No access to performance, daily reports or import |

Everything is checked on the server. Changing the address in the browser gives "Not found" or "Forbidden",
never another person's data. New permissions, which can be adjusted in Settings → Roles:

| Permission | Meaning | Default roles |
|---|---|---|
| `performance.view` | Open Employee Performance (your own dashboard) and Daily Reports | Admin, Director, Coordinator, Engineer |
| `employees.monitor` | See other employees' dashboards and reports within your data scope; review reports | Admin, Director, Coordinator |
| `dailyreports.submit` | Write your own daily reports | Admin, Director, Coordinator, Engineer |
| `imports.own` | Import your own records from Excel (owner = yourself) | Admin, Director, Coordinator, Engineer |
| `data.import` (existing, wider meaning) | Import for any employee in your data scope | Admin, Director, Coordinator |

Each import type also needs the normal "create" permission for that record type. For example, opportunities
need "pipeline.edit", which the Coordinator does not have.

---

## 3. Calculation rules

- **Owner of a record:**
  - Lead or opportunity: the assigned Sales Engineer, otherwise the Coordinator, otherwise its creator.
  - Quotation: its salesperson.
  - Visit or task: the person it is assigned to.
- **"Leads created"** counts leads the employee created.
- **Figures in a period** use each record's own date, in Asia/Dubai time:
  - a lead's received date;
  - a visit's date;
  - a quotation's date;
  - a deal's closing date.
- **Figures marked "now"** show today's situation and do not change with the period: open leads, pending
  follow-ups and overdue tasks.
- **Won value** is the sum of the estimated value of opportunities won in the period.
  - It is measured against the monthly KPI target **"Won deals value"**, which you set in Targets & KPIs.
  - Its weight in the existing performance score is 0, so earlier scores are unchanged.
- **No target, or a target of zero,** shows "No target set" instead of a misleading percentage.
- **Last activity** is the latest audit-log entry for that employee, excluding sign-ins.

---

## 4. Test report (actual results, 28-Oct-2026)

| Check | Result |
|---|---|
| Full automated suite, SQLite | **201 passed, 0 failed** |
| Full automated suite, PostgreSQL 16 | **201 passed, 0 failed** |
| — of which the original suite | 156 passed. Two assertions in `tests/test_modules.py` were deliberately changed: Sales Engineers may now open the importer (own records), and the preview summary has new count keys. |
| — Employee Performance and Daily Reports (`test_employee_performance.py`) | 13 passed |
| — Import Center (`test_import_center.py`) | 27 passed |
| — Security (`test_enhancement_security.py`) | 5 passed |
| Migrations check (`makemigrations --check`) | No missing migrations |
| Upgrade rehearsal on PostgreSQL holding the existing demo data | All new migrations applied. Customers, leads, quotations and payments all still present (5 / 6 / 8 / 3). |
| Rollback rehearsal (previous version run against the upgraded database) | Imports work. With "Won deals value" active, the Targets pages gave 3 errors. With it switched off: 0 errors on 769 pages for 3 roles. See section 8. |
| Production settings check (`check --deploy`) | 1 known warning (HSTS preload, intentionally off), same as before |
| Page crawl, all 5 roles, every reachable page | 1,137 pages, **0 server errors, 0 forbidden links** |
| Browser test of the new pages (`tools/ui_enhancement.py`, desktop and phone) | **62 passed, 0 failed** on a new database; 66 of 66 when run again on the same database (extra checks that a second report for the same day is refused) |
| Original browser test, all roles (`tools/ui_smoke.py`) | **77 passed, 0 failed** on a new database. When repeated many times on the same database, the Kanban drag check eventually fails, because each run moves a card one stage further until it reaches a stage that needs extra details. That is test data running out, not a defect. |
| Code check (pyflakes) | Clean |

**Import tests cover:**
- templates for every type download and re-import cleanly;
- refused files: wrong type, fake .xlsx, corrupt .xlsx, binary CSV, empty file, blank file, headings only;
- the 5 MB and 2,000-row limits;
- missing required columns;
- bad dates, numbers, emails, phones, future dates and unknown employees, each with its Excel row number;
- the failed-rows CSV content;
- cancel;
- rollback when an error happens midway (nothing saved);
- customer duplicates by TRN, email+phone, name only and repeated rows;
- update mode changing only reliable matches and never blanking values;
- duplicate leads and the same file uploaded twice;
- ownership rules for engineer, admin and director;
- permissions for Accounts and Coordinator;
- CSRF;
- visits and tasks keeping historical dates;
- customer / lead mismatches;
- completed sales: won requires a status, lost requires a reason, no future closing dates;
- **re-uploading the same sales file twice adds no revenue**;
- updating an open deal to Won by reference;
- formulas are not evaluated.

**Security tests cover:**
- the reset-link e-mail contains no password, and the link works only once;
- only user managers can send reset links, and CSRF is enforced on that action;
- no password or hash appears on user pages, performance pages or Excel/CSV exports;
- every new page requires sign-in;
- Accounts users are refused;
- missing records give a plain 404;
- daily reports are protected by CSRF.

**Problems found by testing and fixed:**
1. The Excel/CSV export buttons and the page-2 links on the Employee Performance and Daily Reports lists were
   broken (the link started with `??`). Fixed, and a test was added.
2. A manager could see an employee's **draft** report on the employee dashboard and by its address. Drafts
   are now private. Fixed, and a test was added.
3. The import page header showed "0 rows". Fixed, and a test was added.
4. The employee-name column was too narrow and the Status filter was cut off. Layout fixed.
5. The edit history of a daily report was stored but not shown. A "Change history" panel was added to the
   report page, showing who changed which field, from what, to what, and when. Tested.
6. After a rollback, the previous version could not save an import, because the new column had no database
   default. Migration `reporting.0003` adds one, and this was re-checked.

**Not run / not verified:**
- Not deployed to Render.
- Sending real e-mail was not tested. The tests use Django's test mailbox, so reset links need the SMTP
  settings on the server.
- Not tested in Safari, Firefox or real phones (Chromium only, with a phone-sized window).
- No load testing.
- Imports of real company spreadsheets were not tried. Only test files were used.

---

## 5. Changed and new files

**New:**
- Employee Performance and Daily Reports code:
  - `performance/monitoring.py`
  - `performance/team_views.py`
  - `performance/team_urls.py`
  - `performance/report_urls.py`
  - `performance/migrations/0002_dailyreport_dailyreportentry_and_more.py`
- Import Center code:
  - `reporting/import_kinds.py`
  - `reporting/migrations/0002_importbatch_imported_at_importbatch_mode_and_more.py`
  - `reporting/migrations/0003_importbatch_mode_db_default.py`
- Templates and script (`templates/performance/`):
  - `team.html`, `employee.html`, `_kpi.html`, `_period.html`
  - `reports.html`, `report_form.html`, `report_detail.html`, `_entry_row.html`
  - `static/js/performance.js`
- Tests and tools:
  - `tests/test_employee_performance.py`, `tests/test_import_center.py`, `tests/test_enhancement_security.py`
  - `tools/ui_enhancement.py`
- Documentation:
  - `docs/ENHANCEMENT_REPORT.md` (this file)
  - `docs/import_templates/` (5 Excel templates)

**Changed:**
- Permissions and accounts:
  - `accounts/capabilities.py` (new permissions)
  - `accounts/permissions.py`
  - `accounts/views.py`, `accounts/urls.py`, `templates/accounts/user_detail.html` (reset link)
- Site wiring:
  - `config/urls.py`
  - `core/navigation.py` (menu)
  - `core/management/commands/load_demo_data.py` (fictional demo daily reports)
- Performance models and figures:
  - `performance/models.py`, `performance/apps.py`
  - `performance/services.py`, `reporting/metrics.py` (Won value KPI)
- Import Center:
  - `reporting/models.py`, `reporting/imports.py`, `reporting/import_views.py`, `reporting/urls.py`
  - `templates/reporting/import_start.html`, `templates/reporting/import_detail.html`
  - `templates/core/_settings_tabs.html`
- Styles and tests:
  - `static/css/technoflow.css`
  - `tests/test_modules.py`
- Documentation: `README.md`, `docs/USER_MANUAL.md`, `docs/ADMIN_GUIDE.md`, `docs/PROJECT_STATUS.md`, `docs/HANDOVER.md`

---

## 6. Environment variables

**No new environment variables.** The password-reset link uses the existing `SITE_URL` and the e-mail
settings (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`,
`DEFAULT_FROM_EMAIL`). If those are empty, use the existing "Reset password" button instead.

---

## 7. Database changes

The build script (`build.sh`) applies the new migrations automatically:
- `performance.0002`: new daily report tables;
- `reporting.0002`: import mode / date and the import-key table;
- `reporting.0003`: adds a database default for the import mode, so the previous version still works after a rollback;
- `quotations.0002`: from the earlier quotation and logo update, if that update has not been deployed yet.

The migrations only **add** tables and columns. No existing data is changed or deleted. New permissions are
created automatically, and existing roles keep their current permissions.

---

## 8. How to deploy (when you are ready)

1. **Back up first.** In Render, go to technoflow-crm-db → Recovery / Backups and make sure a recent backup
   exists, or use the export described in `docs/ADMIN_GUIDE.md` section 5.
2. Unzip `Technoflow_Trading_CRM_Enhanced.zip` into your GitHub Desktop folder. Replace the files, but keep
   your `.git` folder, and do not add any `.env` file.
3. GitHub Desktop: write a summary such as "Employee performance, daily reports, import center", then click
   **Commit to main** and **Push origin**.
4. Render starts a new deploy automatically. Wait for "Live", then open the site and check:
   - **Employee Performance** and **Daily Reports** appear in the menu;
   - **Import from Excel** shows five template downloads.
5. Optional: in Targets & KPIs, set monthly **"Won deals value"** targets so the target bars appear.
6. If something goes wrong, roll back to the previous version in two steps:
   - **First**, in the CRM go to Targets & KPIs → **KPI definitions** → open
     **"Won deals value"**, untick "Active" and save. The previous version does not recognise this KPI and its Targets pages would
     show an error while it is active.
   - **Then** use Render → your service → **Rollback** to the previous deploy.

   The new tables and columns stay in the database and do not affect the previous version. This was
   rehearsed locally: with that KPI switched off, the previous version opened every page for three roles
   with 0 errors and could still upload imports.

---

## 9. Limitations

- **Sales Manager** is the existing **Sales Coordinator** role (team scope). A separate fifth sales role was
  not created.
- Employees are shown with initials. There are no profile photos.
- Working days for the "missing reports" count are Monday–Friday. Public holidays are not excluded.
- Daily reports can be written for today and up to 31 days back, and not for future dates.
- Visits and calls logged inside daily reports are self-reported. They do not create CRM visit or
  communication records.
- Import matching for customers needs a code, TRN, reference or email+phone. Rows matching on the name
  alone are always skipped for you to check by hand.
- WhatsApp / Outlook integration is not part of this update.
- Render's free database expires around 26-Nov-2026. Upgrade the plan or move the data before then.
