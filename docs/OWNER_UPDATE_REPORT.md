# Technoflow CRM — Update Report: Owner, Lead Categories, Opportunities, Uploaded Quotations

Date: 30-Oct-2026 · Builds on the existing CRM (the Oct-2026 enhancement included). Nothing was removed or rebuilt.

> **Live site status:** https://technoflow-crm.onrender.com has **not** been updated. This package was tested on a
> local copy only. Follow section 7 (back up first) to deploy it.

## 1. Your decisions

| Question | Your answer | How it is built |
|---|---|---|
| Quotations | Upload by default, keep the builder | "Upload quotation" is the main button. "Prepare in the CRM" is still there, and existing quotations, orders and invoices keep working. |
| Approvals | Owner, with the Sales Director as backup | Requests go to the Owner. The Director can approve only when the Owner ticks "Sales Director may approve as backup" (Modules & Approvals). |

## 2. What was added

### 2.1 Leads
- **Lead category**: Job in Hand, Tender or Purchase Enquiry.
  - Shown as three large coloured buttons on Add / Edit lead. It is **required** for new leads.
  - Shown in the lead list (coloured badge) and on the lead page.
  - Filterable on the Leads list and the Leads Dashboard.
- **Changes are recorded:**
  - a category change is written to the lead's activity ("Category changed from Tender to Job in Hand");
  - every field change, with old → new value, who and when, appears under **Change history** on the lead page.
- **Smaller changes:**
  - "Service / product interest" is now **"Product interest"**.
  - **Estimated value is optional**; an empty value shows as "Not given", and it is never counted as sales.
- **Ownership:**
  - the lead page shows the **Creator** (who registered it) and the **Responsible employee** (owner);
  - every lead must have a responsible employee. Salespeople own what they register; managers choose;
  - any authorised user can edit a lead, not only its creator (role permissions apply);
  - Stage history and Assignment history stay as before.
- **Lead sources** (Settings → Drop-down lists → Lead / opportunity source): add, **edit (rename)**, activate,
  deactivate.
  - Used values are never deleted: deactivated ones stay on old leads but cannot be chosen for new ones.
- **Filters on the Leads list:** category, status / stage, source, employee, priority, created date range,
  overdue follow-up, unassigned, converted.

### 2.2 Opportunities (menu: Opportunities)
- **Separate menu items:**
  - **Opportunities** opens the opportunity list.
  - **Sales Pipeline** opens the pipeline board and forecast.
- Each opportunity is linked to its lead and customer.
- **Create opportunity** from a converted lead copies the title, product interest, value, source, city and
  responsible employee. The lead itself is never changed.
- **Duplicates are prevented**: a lead can have only one active opportunity.
- **Team members** can be added to an opportunity. Revenue is still credited **once**, to the responsible employee.
- **Stages:**
  - "Initial Discussion" is renamed **Qualification** and "Proposal Preparation" is renamed **Proposal**
    (only if those default names were still in use).
  - Negotiation, Won and Lost are unchanged.
  - Stages remain editable in Settings, and lost reasons are recorded as before.

### 2.3 Quotations: uploaded documents with revisions
- **Upload quotation** stores a finished document from your quotation system:
  - formats: PDF recommended; Word, Excel and images also accepted;
  - details: its number in your system, date, validity, value, notes;
  - links: customer, lead and opportunity.
- **Upload revision** adds **R1, R2, …**.
  - Every revision keeps its own file. **Files are never overwritten or deleted.**
  - The **Revision history** table shows the date, uploader, notes, status, value and a download button for each
    revision, and marks the **Latest** one.
- **Mark as final** marks the current revision as **Final**, shown as e.g. "Final (R2)".
- **Counted once:**
  - a quotation with several revisions is still **one** quotation in every count;
  - only the latest revision's value and status count;
  - quotation values are **never** sales revenue.
- **Approval and audit:**
  - uploaded quotations use the same approval flow (submit → Owner approves → sent → accepted or declined);
  - every upload and download is in the audit log.
- **File storage:**
  - uploaded files are stored **in the database**, at most 15 MB each.
  - Render's free web service loses disk files at every deploy; database storage avoids that, and files are
    included in database backups.
  - File type and content are checked: a renamed .exe is refused.

### 2.4 Owner
- **Owner role:** a new role (1 account) that starts with every permission. Create the Owner login in
  User Management (role "Owner").
- **Owner Dashboard** (Owner only):
  - cards: won revenue, open pipeline (and weighted), leads by category, visits, quotations and revisions,
    pending approvals, overdue activities;
  - a **sales target chart** (target, won revenue, open pipeline due in the period) with a
    Monthly / Quarterly / Yearly switch;
  - the latest pending approvals;
  - an employee table (see 2.5).
- **Pending Approvals:**
  - every request waiting for a decision, oldest first, showing the employee, the module, the submitted date,
    the reason approval is needed and a link to download the document;
  - **Approve** / **Reject** buttons, with comments (required when rejecting);
  - recent decisions;
  - the employee is notified of every decision;
  - permissions are checked on the server: nobody can approve a quotation they prepared or are the salesperson for.
- **Team Calendar:**
  - one combined calendar, or one employee's calendar, in Month or List view;
  - includes customer visits, meetings (logged in Communication History), follow-ups, tasks and deadlines
    (expected closing dates, quotation expiry);
  - filters: employee, activity type, dates;
  - statuses are shown with colour **and** text: Completed, Upcoming, Due today, Overdue, Cancelled;
  - each person sees only employees within their own access level: the Owner and Director see everyone, a
    Coordinator sees their team, a Salesperson sees only themselves.
- **Targets:** monthly, quarterly and yearly targets are set in Targets & KPIs → Set targets, using the
  "Won deals value" KPI. Each employee then shows one of these statuses:
  - Target achieved;
  - Pipeline can reach target;
  - Below target;
  - No target set.

### 2.5 Employee performance
Figures per employee:
- leads created, leads assigned, leads handled now;
- visits planned and completed;
- opportunities created, won and lost;
- quotations uploaded and revised;
- won revenue;
- pending and overdue activities;
- target and achievement.

Periods: Today, Yesterday, This / last week, month, **quarter** and **year**, or Custom.
The list adds a target period choice and an achieved / not achieved filter.

### 2.6 Dashboards
- **Module dashboards:** Leads, Customer Visits, Customers, Sales Pipeline, Opportunities, Projects and Quotations.
  - Each has coloured cards, charts, period and employee filters.
  - **Click a card or bar to open the matching records.**
  - Reach them from the "Dashboard" tab on each list.
- **Other dashboards:** the existing Main Dashboard and Employee Performance pages stay, plus the new Owner Dashboard.

### 2.7 Finance on/off, menu, look and feel
- **Finance switch:** Modules & Approvals → "Show the Finance module".
  - When it is off, Sales Orders, Invoices, Collections and the order / invoice reports and cards are **hidden
    and blocked** for everyone.
  - No data is deleted, roles keep their permissions, and turning it on restores everything.
  - The Owner and System Administrator can change it.
- **Menu order:** Dashboard, Leads, Customer Visits, Customers, Sales Pipeline, Opportunities, Projects,
  Quotations, then Finance (when on). The Owner section sits at the top for the Owner.
  - Exactly one menu item is highlighted. Before, Projects also highlighted Sales Pipeline.
- **Look and feel:**
  - searchable drop-downs in forms with long lists (type to filter);
  - coloured category buttons;
  - status badges that always include text.

### 2.8 Demo data
- **Deploys no longer create demo data**: `LOAD_DEMO_DATA` and `DEMO_USERS_PASSWORD` were removed from `render.yaml`.
- Every deploy prints a **preview** of any demo records it finds and changes nothing.
- **Removing them:** after a backup, set `REMOVE_DEMO_DATA=yes` for one deploy.
  - Only records of the fictional "Demo:" companies and the demo logins are removed (now including uploaded
    quotation files).
  - Demo logins are deactivated, not deleted.
  - Genuine records, users, roles and settings are kept.
- Demo records are identified only by their "Demo:" names and DEMO- employee IDs. Nothing uncertain is deleted.

## 3. Roles

| Your role | CRM role | Notes |
|---|---|---|
| Owner | **Owner** (new) | Everything, Owner Dashboard, approvals, all calendars, Finance switch |
| Admin | System Administrator | Users, settings, Finance switch; **no longer approves** once an Owner account exists |
| Sales Director | Sales Director | All sales data; approves only as backup when the Owner allows it |
| Sales Manager | Sales Coordinator | Their team's data and calendar |
| Salesperson | Sales Engineer | Own data, own calendar, uploads quotations |

Until an active Owner account exists, approvals follow the previous rule (Director or Administrator), so nothing
gets stuck after the update.

Accounts: the role limits are 1 Owner + 1 / 2 / 2 / 2 / 3, so **11 accounts in total** (previously 10).

**New permissions** (Settings → Roles & Limits):
- `owner.dashboard`;
- `approvals.view`;
- `calendar.view`;
- `modules.manage`.

## 4. Test results (actual, 30-Oct-2026)

| Check | Result |
|---|---|
| Automated tests, SQLite | **232 passed, 0 failed** |
| Automated tests, PostgreSQL 16 | **232 passed, 0 failed** |
| — new tests for this update (`tests/test_owner_features.py`) | 28 passed |
| — earlier tests | 204 passed. Some were updated for intended changes: the Owner role, the 11-seat total, lead category now required in forms and imports, the demo settings removed from `render.yaml`. |
| Migration check | No missing migrations |
| Page crawl, 6 roles, fresh demo database | 1,624 pages, **0 errors, 0 forbidden links** |
| Page crawl, Finance turned off | 1,285 pages, 0 errors, 0 forbidden links (no link points to a hidden page) |
| Browser checks, new features (`tools/ui_v3.py`, desktop and phone) | **66 passed, 0 failed** |
| Browser checks, earlier enhancement (`tools/ui_enhancement.py`) | 62 passed, 0 failed |
| Browser checks, original (`tools/ui_smoke.py`) | 77 passed, 0 failed |
| Upgrade rehearsal (current live version + data → this version, PostgreSQL) | All records kept (customers, leads, deals, quotations, revisions, orders, invoices, payments, visits, tasks, users). Stages renamed, Owner role created. 1,273 pages, 0 errors. |
| Rollback rehearsal (previous version on the upgraded database) | Pages: 0 errors. Creating a lead and a quotation works (the database fills in the new columns itself). |

The new tests cover:
- **Leads:** category required and shown; responsible employee required; category history and change history;
  filters; lead sources added, renamed and deactivated but never deleted.
- **Opportunities:** created from a lead with details copied; duplicates prevented; team members;
  revenue credited once; stage rename.
- **Quotations:** Original → R1 → R2 with every file downloadable; mark as final; files cannot be replaced or
  deleted; fake files refused; access limited to permitted users; no revision while waiting for approval;
  counted once and never as revenue.
- **Approvals:**
  - the Owner approves from Pending Approvals, and the employee is notified;
  - rejecting needs a comment;
  - the Director can approve only when backup is on; the Admin can't approve while an Owner exists;
  - the previous rule applies when no Owner exists;
  - nobody can approve their own quotation;
  - an outside redirect address is ignored.
- **Targets:** quarterly and yearly targets with their statuses.
- **Calendar:** each person's access level respected, filters, statuses, meetings and visits kept separate.
- **Finance switch:** hidden, blocked and restored.
- **Dashboards:** all 7 module dashboards load, with correct figures, the right records per person and
  working drill-down links.
- **Other:** quarter / year periods; demo cleanup including quotation files.

**Problems found during testing and fixed:**
1. A salesperson who cleared the "Responsible employee" field could save a lead with no owner. Now they own
   it automatically.
2. Editing a lead source while sending a different list name moved it to that list. The list is now fixed.
3. The calendar showed every customer visit with the purpose "Initial Meeting" as a "meeting". Visits are now
   always visits, and meetings come from Communication History.
4. Quotations prepared in the CRM showed "Original". They keep "Rev 1, Rev 2".
5. The revision table was wider than its card. It now fits.

**Not tested / not verified:**
- No deploy to Render.
- No real e-mail sending.
- Safari, Firefox and real phones were not tested (Chromium only, desktop and phone sizes).
- No load testing.
- No real quotation files or spreadsheets from your systems were used.
- No separate development branch or staging site: I have no access to your GitHub or Render.

## 5. Changed and new files

**New:**
- Owner features: `owner/` (`rules.py`, `calendar.py`, `views.py`, `urls.py`, `apps.py`) and `templates/owner/`
  (dashboard, approvals, calendar, modules).
- Uploaded quotations: `quotations/uploads.py`, `templates/quotations/upload.html`, `templates/quotations/list.html`.
- Module dashboards:
  - `reporting/module_dashboards.py`, `reporting/dashboard_views.py`, `reporting/dashboard_urls.py`;
  - `templates/reporting/module_dashboard.html`, `static/js/dashboards.js`.
- Searchable drop-downs: `static/js/searchable-select.js`, `static/vendor/tom-select/` (Tom Select 2.3.1,
  Apache-2.0 licence, stored locally).
- Shared templates:
  - `core/templates/widgets/pill_radio.html`;
  - `templates/partials/change_history.html`;
  - `templates/core/settings_lookup_edit.html`.
- Migrations:
  - `core/0004`, `leads/0002`, `quotations/0003`;
  - `sales/0002`, `sales/0003` (stage rename).
- Tests and tools: `tests/test_owner_features.py`, `tools/ui_v3.py`; `docs/OWNER_UPDATE_REPORT.md`.

**Changed:**
- Permissions and roles: `accounts/` (`capabilities.py`, `models.py`, `setup.py`, `load_demo_users`).
- Shared code and settings:
  - `core/` (`audit.py`, `context_processors.py`, `forms.py`, `models.py`, `navigation.py`, `views.py`,
    `urls.py`, template tags, `load_demo_data`, `remove_demo_data`);
  - `config/` (settings, urls).
- Modules:
  - `leads/` (`models.py`, `forms.py`, `views.py`) and `sales/` (`models.py`, `forms.py`, `services.py`, `views.py`);
  - `quotations/` (`models.py`, `forms.py`, `services.py`, `views.py`, `urls.py`);
  - `performance/` (`monitoring.py`, `team_views.py`) and `reporting/` (`import_kinds.py`, `imports.py`,
    `reports.py`, `views.py`);
  - `customers/views.py`, `visits/views.py`.
- Templates: base, lead detail, opportunity detail, quotation detail, team list, lookups.
- Styles: `static/css/technoflow.css`.
- Deployment: `build.sh`, `render.yaml`.
- Tests and tools: the test files listed in section 4, and `tools/ui_enhancement.py`.
- Documentation and templates:
  - `docs/import_templates/` (the leads template now has a "Lead category" column);
  - `README.md` and the guides in `docs/`.

## 6. Environment variables

| Variable | Change |
|---|---|
| `REMOVE_DEMO_DATA` | **New, optional.** `yes` for one deploy only (after a backup) removes demo records. Leave empty otherwise. |
| `LOAD_DEMO_DATA`, `DEMO_USERS_PASSWORD` | **No longer used.** You may delete them in Render → Environment. |

Nothing else changed. No new secrets are needed.

## 7. How to deploy

1. **Back up**: Render → technoflow-crm-db → Recovery / Backups (make sure a recent backup exists).
2. Unzip the package into your GitHub Desktop folder, replacing the files. Keep the `.git` folder, and do not add `.env`.
3. In GitHub Desktop, commit and **Push origin**. Render deploys automatically. The build applies the
   migrations, which only **add** data structures; no existing data is changed.
4. When it shows **Live**, open the site:
   - check that the menu order and the new pages appear;
   - in **User Management**, create the **Owner** login (role "Owner").
5. **Remove the demo data:** after the backup, set `REMOVE_DEMO_DATA=yes` and click "Save, rebuild, and deploy".
   Check the log ("Demo data removed"), then delete the variable again.
6. **Existing leads** show "Category not set" until someone edits them; the form asks for the category.
7. **Rollback:**
   - first, in Targets & KPIs → KPI definitions, untick "Active" on "Won deals value" (from the previous update);
   - then use Render → Rollback. The previous version works on the upgraded database (rehearsed).

**Testing locally before you deploy:**
1. Create a fresh database: `python manage.py migrate`.
2. Load demo users and data (local only): `load_demo_users --password-env DEMO_USERS_PASSWORD`, then
   `load_demo_data`. This creates `demo.owner` and the other demo logins.
3. Run `python -m pytest`.
4. With the server running: `DEMO_PW=… python tools/ui_v3.py`.

## 8. Limitations
- Existing leads have no category until edited. Reports show them as "Not set".
- **Team members** of an opportunity are recorded and shown, but they do not gain access to it: visibility
  still follows the responsible employee and the coordinator.
- Order confirmation (Finance) is not an approval request, so it is not in Pending Approvals. It stays with the
  Owner, Director and Administrator. The quotation approval is the CRM's approval workflow.
- **Quotation file storage:** files of at most 15 MB, kept in the database. The free Render database is 1 GB and
  **expires around 26-Nov-2026**, so upgrade it before then.
- When Finance is turned off, "Create sales order" from a quotation is also hidden.
- The month calendar shows short names on a phone. Use the List view there.
- WhatsApp / Outlook integration is not included.
