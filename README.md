# Technoflow Trading LLC — CRM

Django 5.2 + PostgreSQL customer relationship management system for Technoflow Trading LLC.

**Status: all 8 phases delivered.** 13 modules, 5 roles, 44 reports, 145 automated tests.
What was tested, and what still needs your own setup (e-mail server, document storage online), is listed in
**[docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)**.

| Document | For |
| --- | --- |
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | Everyone: how to use the CRM, by role |
| [docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md) | System Administrator / IT: settings, users, backups, updates, logs, recovery, own-server install |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Putting the CRM online with GitHub + Render (beginner guide) |
| [docs/DATABASE.md](docs/DATABASE.md) | Database tables and relationships (ER diagram) |
| [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) | Phase checklist, test results, known limitations |

---

## Quick start on Windows (development / demonstration)

Requirements: Python 3.12 or 3.13 from python.org (tick "Add Python to PATH" when installing).

```bat
cd technoflow_crm
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_demo_users --password "Demo-Pass-2026!" --no-password-change
python manage.py load_demo_data
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in as one of the demo users (password as typed above):

| Username | Role |
| --- | --- |
| demo.admin | System Administrator |
| demo.director | Sales Director |
| demo.accounts | Accounts |
| demo.engineer | Sales Engineer |
| demo.coordinator | Sales Coordinator (linked to demo.engineer) |

`load_demo_data` creates **fictional** customers (names start with "Demo:"), leads, opportunities, quotations,
orders, invoices, payments, visits, tasks and targets by running them through the real workflow, so every
screen has data. Leave it out to start empty. Never run it on the real production database.

Development uses SQLite (`db.sqlite3`) and `config/settings/dev.py` automatically; no `.env` file is needed.
E-mails (password reset, notifications) are printed in the terminal window.

To start with your real administrator instead of demo users:

```bat
python manage.py create_system_admin --username aniq --email aniq@technoflow.com --first-name Mohamed --last-name Aniq
```

## Run the automated tests

```bat
python -m pytest
```

145 tests: sign-in, lockout, MFA, password rules, role limits, permissions on every module page per role,
record scope, the complete Lead → Quotation → Approval → Order → Invoice → Payment → Reversal workflow through
the real web forms, calculations, revisions, documents security, imports, KPIs, notifications and deployment
readiness.

## Deploy online (GitHub + Render)

Step-by-step guide: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**. `render.yaml` creates the PostgreSQL database and
the web service; `build.sh` installs, checks, collects static files, migrates and creates the first
administrator. Deploys never erase data. Render's **free** database expires after 30 days, and the free web
service cannot keep uploaded documents; the guide explains both.

## Own Linux server

**[docs/ADMIN_GUIDE.md](docs/ADMIN_GUIDE.md)** → "Installing on your own server". Ready-made files in `deploy/`:
Nginx site, Gunicorn systemd service, daily reminder and nightly backup timers, `backup.sh` / `restore.sh`
(PostgreSQL + documents) and `backup_windows.ps1`.

## Modules

| # | Module | Menu |
| --- | --- | --- |
| 1 | Users, roles & permissions (limits 1/2/2/2/3), optional two-step sign-in | User Management, Roles & Limits |
| 2 | Customer master with contacts, duplicate check, 360° view and timeline | Customers |
| 3 | Leads: list + Kanban, assignment, stages, conversion to customer/opportunity | Leads |
| 4 | Customer visits: calendar, week schedule, completion notes, follow-ups | Customer Visits |
| 5 | Sales pipeline (list, Kanban, forecast) and projects | Sales Pipeline, Projects |
| 6 | Quotations: lines, VAT, discounts, approval, revisions, PDF, acceptance | Quotations |
| 7 | Sales orders with payment milestones | Sales Orders |
| 8 | Invoices, payments, allocations, reversals, statements, ageing | Invoices, Collections |
| 9 | Targets & KPIs, scorecards, ranking | Targets & KPIs |
| 10 | Tasks & follow-ups, calendar | Tasks & Follow-ups |
| 11 | Communication history | Communication History |
| 12 | Documents (private, versioned) | Documents (+ panel on each record) |
| 13 | Dashboards, 44 reports (screen, Excel, CSV, PDF), import, global search, notifications | Dashboard, Reports, Notifications |

## Project layout

```text
config/          settings (base / dev / prod / test), URLs
core/            audit log, settings, numbering, tax rates, money calculations, CRUD framework, activity timeline
accounts/        employees, roles, capabilities, account limits, login history, two-step sign-in
customers/ leads/ visits/ communications/ tasks/ sales/ quotations/ orders/ invoicing/
performance/ documents/ notifications/ reporting/      one app per module
templates/       page templates          static/   theme + local Bootstrap 5.3, Bootstrap Icons, Chart.js 4
deploy/          Nginx, systemd, backup / restore scripts
docs/            manuals and guides      tests/    pytest suite
```

Bootstrap, icons and Chart.js are served from `static/vendor/`, so the CRM works without internet access.

## How permissions work

- Each employee has one **role**; roles hold **capabilities** (for example `quotations.approve`). The System
  Administrator edits them in **Roles & Limits** without code changes.
- Every page and action checks the capability **on the server**; hiding a button is cosmetic only.
- **Data scope**: *All records* (Admin, Director, Accounts), *Own and assigned* (Sales Engineer),
  *Own plus linked team members* (Sales Coordinator). Applied to every list, search, dashboard, report and export.
- **Account limits** (1 / 2 / 2 / 2 / 3) are checked whenever an account is created, activated or moved.
- Nobody approves their own quotation; payments are never deleted (reversals instead); issued invoices and
  approved quotation revisions cannot be edited.
