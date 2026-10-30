# Technoflow CRM — Handover Notes

Paste this file (or attach it with the project zip) at the start of a new Claude chat or account so the work
can continue without the original conversation.

## Project

- **Client:** Technoflow Trading LLC (technoflow.com). Built by Mohamed Aniq.
- **What:** an enterprise CRM in Django 5.2 + PostgreSQL with 13 modules, 5 roles (account limits
  Admin 1 / Director 2 / Accounts 2 / Engineer 2 / Coordinator 3) and 8 phases. All 8 phases are delivered.
- **Phase 1 plan** (Claude Docs artifact): "Technoflow CRM — Phase 1 Architecture & Plan".
- **Defaults agreed in Phase 1:**
  - every quotation needs approval (threshold AED 0)
  - numbering QT-2026-0001 / SO- / INV-
  - 30-day payment terms
  - "orders booked" counted excluding VAT
  - coordinators see only their linked engineers' records
- **Branding:** logo colours #C1CD23 (green) and #5F6062 (grey). The Excel file CRM_Technoflow-1.xlsx was used
  for reference only.

## Where things are

- **Code:** private GitHub repository `bibinbabutss-source/Technoflowcrm` (branch `main`). The files sit at the
  repository root, with `manage.py` and `render.yaml` at the top level.
- **Online:** Render Blueprint `technoflow-crm`, deployed on 27-Oct-2026.
  - web service `technoflow-crm` (free plan): https://technoflow-crm.onrender.com
  - database `technoflow-crm-db` (free plan) — **expires about 26-Nov-2026 and is deleted about 10-Dec-2026
    unless upgraded**
- **First deploy issue:** it failed with "password too similar to the email address". Fixed by choosing a
  different ADMIN_TEMP_PASSWORD.

## Documents in the repository

| File | Contents |
| --- | --- |
| `README.md` | Quick start, modules, permissions |
| `docs/PROJECT_STATUS.md` | Phase checklist, test results, known limitations |
| `docs/USER_MANUAL.md` | How to use the CRM, by role |
| `docs/ADMIN_GUIDE.md` | Settings, backups, updates, own-server install |
| `docs/DEPLOYMENT.md` | GitHub + Render guide |
| `docs/DATABASE.md` | Tables and ER diagrams |

## Test status at delivery

**Update 30-Oct-2026 (Owner role, lead categories, opportunities, uploaded quotations — see
docs/OWNER_UPDATE_REPORT.md):**
- 232 automated tests passed on SQLite and PostgreSQL 16.
- Crawl: 1,624 pages, 0 errors (and 0 with Finance turned off).
- Browser checks: 66 + 62 + 77, all passed.
- Upgrade and rollback rehearsed on PostgreSQL.
- **Not yet deployed to Render.**

**Update 28-Oct-2026 (Employee Performance, Daily Reports, Excel Import Center — see
docs/ENHANCEMENT_REPORT.md):**
- 201 automated tests passed on SQLite and on PostgreSQL 16.
- Page crawl: 1,137 pages with 0 errors.
- New-page browser checks: 62 of 62 passed. Original browser test: 77 of 77 passed.
- Upgrade and rollback rehearsed on a local copy.
- **Not yet deployed to Render.**

Earlier status:

- **156 automated tests** passed on both SQLite and PostgreSQL 16 (after the 28-Oct quotation format and
  logo update — see docs/QUOTATION_LOGO_UPDATE.md).
- **Page crawl:** every page reachable from the menus, for every role, with 0 server errors.
- **Browser test:** 77 of 77 checks passed (Playwright, desktop and phone size).
- **Production rehearsal:** the Gunicorn + PostgreSQL production setup passed.
- **Some actions only opened, not submitted** (form opens without errors, but no test pressed Save):
  - editing order milestones
  - rescheduling a visit
  - deleting a task
  - editing or deleting a communication
  - archiving an opportunity
  - new document version and document archive
- **Not tested:**
  - sending email through a real SMTP server
  - Arabic text in PDFs
  - Safari and Firefox
  - many users at the same time

## Open items / next steps

1. **Upgrade the Render database** before 26-Nov-2026, or move hosting.
2. **Document uploads are not kept on the free plan.** Use a paid Starter plan with a disk, or a cPanel or
   VPS host.
3. **cPanel hosting** was asked about. It needs Python App support, PostgreSQL (or MySQL, untested) and
   SSH, plus a `passenger_wsgi.py` file — not yet prepared.
4. **SMTP email:** fill in `EMAIL_HOST`, `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`, then test a
   password reset.
5. **Before real use:**
   - remove the demo data with `REMOVE_DEMO_DATA=yes` for one deploy (after a backup)
   - deactivate the demo users
   - fill in Settings → Company (TRN, address)
   - turn on two-step sign-in
6. **Not built:**
   - WhatsApp / mailbox sync
   - accounting-system integration
   - currency conversion in reports (use AED only)
