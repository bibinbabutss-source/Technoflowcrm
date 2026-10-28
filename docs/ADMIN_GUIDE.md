# Technoflow CRM — Administrator Guide

For the System Administrator and whoever runs the server. Online deployment on Render is covered step by step
in [DEPLOYMENT.md](DEPLOYMENT.md); this guide covers daily administration and running on your own server.

## Contents

1. [Daily administration in the CRM](#1-daily-administration-in-the-crm)
2. [Settings reference](#2-settings-reference)
3. [External services and what still needs setting up](#3-external-services-and-what-still-needs-setting-up)
4. [Installing on your own server](#4-installing-on-your-own-server)
5. [Backups and restore](#5-backups-and-restore)
6. [Updating the CRM](#6-updating-the-crm)
7. [Logs and monitoring](#7-logs-and-monitoring)
8. [Recovery procedures](#8-recovery-procedures)
9. [Management commands](#9-management-commands)

---

## 1. Daily administration in the CRM

**Users** (User Management)
- **Add employee**: username, e-mail, role, temporary password (they must change it at first sign-in).
  The role's account limit is checked; deactivate someone before adding beyond the limit.
- **Deactivate** instead of deleting: history stays, the person can no longer sign in, the seat is freed.
  Reassign their open leads/customers first (edit the records or use the list filters).
- **Reset password** sets a temporary password and signs the person out everywhere.
- **Email a password-reset link** sends the employee a one-time link that expires, so they choose their own
  password. Nobody, including administrators, can see a password. This needs the e-mail settings (SMTP) to
  be filled in.
- **Unlock sign-in** clears a lockout after too many wrong passwords.
- **Reset two-step sign-in** if someone lost the phone with their authenticator app.
- **Login history** shows successful and failed sign-ins with IP address.

**Roles & Limits**: account limit, data scope (all / team / own) and the capability checklist per role.
The last active System Administrator cannot be deactivated or moved to another role.

**Employee Performance, Daily Reports, Import from Excel**: who may use them is set by the permissions
`performance.view`, `employees.monitor`, `dailyreports.submit`, `imports.own` and `data.import`
(Roles & Limits). Set monthly **"Won deals value"** targets in Targets & KPIs to show the target bars. See
`docs/ENHANCEMENT_REPORT.md` for the rules and for the rollback step (switch that KPI off before rolling back).

**Audit log**: every create, change, delete, approval, sign-in and settings change, with before/after values.
It cannot be edited. Filter and export to CSV.

## 2. Settings reference

| Tab | What it controls |
| --- | --- |
| Company | Name, legal name, TRN, address, contacts (printed on PDFs), currency, financial year start, default quotation validity and payment terms, upload size and allowed file types |
| Approvals & reminders | Auto-approval threshold (0 = every quotation needs approval), discount limit %, expiry-warning days, e-mail notifications on/off, visit / task / overdue-invoice reminder days, performance rating bands. **Run reminders now** button and last run |
| Quotation template | Line under the logo, company name in Arabic, default cover letter, closing, signatory designation, price-schedule note, "show unit next to quantity", footer lines and the default commercial terms copied into new quotations. Legal name and TRN under the logo come from the Company tab |
| Tax rates | VAT 5 % (default), Zero-rated, Exempt; add or deactivate rates. Existing documents keep the rate they were made with |
| Stages | Lead stages (and which count as "qualified") and opportunity stages with default probability. Hide instead of delete; Won/Lost are fixed |
| Document numbering | Prefix, year, padding and yearly reset for customers, leads, quotations, orders, invoices, payments, etc. Invoices get their number only when issued, without gaps |
| Drop-down lists | Customer categories, industries, sources, visit purposes, lost reasons, document categories… |
| Import data | Customers / leads from Excel or CSV (preview, duplicates flagged, never overwrites) |

KPI names, weights and on/off: Targets & KPIs → **KPI definitions** (System Administrator or Sales Director).

## 3. External services and what still needs setting up

| Service | Needed for | Status | What you do |
| --- | --- | --- | --- |
| PostgreSQL 14+ | Production database | Implemented and tested (PostgreSQL 16) | Render creates it; own server: section 4 |
| SMTP e-mail server | Password-reset e-mails and e-mail notifications | Implemented; tested with Django's test mail backend only — **not tested against a real mail server** | Set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`, `SITE_URL`; then tick *E-mail notifications* in Settings → Approvals & reminders. Office 365: `smtp.office365.com`, port 587, TLS, a licensed mailbox or SMTP relay |
| Persistent file storage | Uploaded documents | Implemented (private folder `MEDIA_ROOT`) | Own server: nothing extra. Render: a paid web service with a persistent disk (DEPLOYMENT.md) |
| Scheduler | Daily reminders | Implemented three ways | Own server: `technoflow-reminders.timer`. Render free: runs on first dashboard visit each day. Manual: Settings → Run reminders now |
| Authenticator app | Two-step sign-in | Implemented (standard TOTP) | Users install any authenticator app; nothing to configure |
| WhatsApp / mailbox sync | — | **Not implemented**: communications are logged manually | Would need WhatsApp Business API / Microsoft Graph credentials and a separate project |
| Accounting system (e.g. Tally, Zoho Books) | — | **Not implemented** | Export invoices/payments to Excel from Reports |

## 4. Installing on your own server

Tested configuration: Ubuntu 24.04, Python 3.12, PostgreSQL 16, Nginx, Gunicorn.

```bash
# 1. System packages and a service account
sudo apt update && sudo apt install -y python3-venv python3-dev postgresql nginx certbot python3-certbot-nginx
sudo adduser --system --group --home /srv/technoflow_crm technoflow

# 2. Database
sudo -u postgres psql -c "CREATE USER technoflow WITH PASSWORD 'choose-a-strong-password';"
sudo -u postgres psql -c "CREATE DATABASE technoflow_crm OWNER technoflow;"

# 3. Code (copy the project folder to /srv/technoflow_crm, e.g. git clone of your private repository)
cd /srv/technoflow_crm
sudo -u technoflow python3 -m venv .venv
sudo -u technoflow .venv/bin/pip install -r requirements.txt

# 4. Configuration
sudo -u technoflow cp .env.example .env && sudo chmod 600 .env
#    edit .env: SECRET_KEY, DATABASE_URL, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, SITE_URL,
#    MEDIA_ROOT=/var/lib/technoflow_crm/media, LOG_DIR=/var/log/technoflow_crm, TRUST_X_FORWARDED_FOR=True,
#    e-mail settings. (Static files are collected into /srv/technoflow_crm/staticfiles.)
sudo mkdir -p /var/lib/technoflow_crm/media /var/log/technoflow_crm /var/backups/technoflow_crm
sudo chown technoflow: /var/lib/technoflow_crm/media /var/log/technoflow_crm /var/backups/technoflow_crm

# 5. Build (same script Render uses; it skips pip if you comment that line)
sudo -u technoflow bash -c 'set -a; . ./.env; set +a; .venv/bin/python manage.py check --deploy && \
  .venv/bin/python manage.py collectstatic --no-input && .venv/bin/python manage.py migrate && \
  .venv/bin/python manage.py create_system_admin --username aniq --email aniq@technoflow.com \
  --first-name Mohamed --last-name Aniq'

# 6. Services
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now technoflow-crm technoflow-reminders.timer technoflow-backup.timer
sudo cp deploy/nginx/technoflow-crm.conf /etc/nginx/sites-available/technoflow-crm
sudo ln -s /etc/nginx/sites-available/technoflow-crm /etc/nginx/sites-enabled/
sudo certbot --nginx -d crm.technoflow.com
sudo nginx -t && sudo systemctl reload nginx
```

`config/settings/prod.py` refuses to start if DEBUG is on, the secret key is short, the database is SQLite or
ALLOWED_HOSTS is empty. Uploaded documents live in `MEDIA_ROOT`, which Nginx never serves; downloads go
through the CRM's permission check.

## 5. Backups and restore

**What to back up**: the PostgreSQL database **and** the documents folder (`MEDIA_ROOT`). The code is in Git.

- Own server: `deploy/backup.sh` (enabled nightly by `technoflow-backup.timer`) writes
  `db-<date>.dump` and `media-<date>.tar.gz` to `/var/backups/technoflow_crm`, checks the dump is readable,
  and keeps 30 days. **Copy that folder off the server** (another machine, NAS or cloud) — a backup on the same
  disk does not survive a disk failure.
- Render: paid databases have automatic backups / point-in-time recovery; you can also run
  `pg_dump "<External Database URL>" -Fc -f crm.dump` from any computer with PostgreSQL tools.
- Windows laptop installation: `powershell -ExecutionPolicy Bypass -File deploy\backup_windows.ps1`.

**Restore** (own server):

```bash
sudo systemctl stop technoflow-crm
sudo -u technoflow bash -c 'set -a; . ./.env; set +a; bash deploy/restore.sh \
     /var/backups/technoflow_crm/db-YYYYMMDD-HHMMSS.dump /var/backups/technoflow_crm/media-YYYYMMDD-HHMMSS.tar.gz'
sudo systemctl start technoflow-crm
```

The script asks you to type YES, replaces the database contents, unpacks the documents and runs `migrate` in
case the backup is older than the code. **Test a restore every few months** on a spare database.

## 6. Updating the CRM

1. On a test copy: get the new code, `pip install -r requirements.txt`, `python -m pytest` (all tests must pass).
2. Take a backup (`bash deploy/backup.sh`).
3. On the server: update the code (`git pull`), then
   `.venv/bin/pip install -r requirements.txt && .venv/bin/python manage.py migrate && .venv/bin/python manage.py collectstatic --no-input`
4. `sudo systemctl restart technoflow-crm`.
5. Open the CRM, sign in, open a few records. If something is wrong, restore the backup and the previous code.

Migrations only add or change structure; they never delete business records. On Render, steps 3–4 happen
automatically on every push (`build.sh`).

## 7. Logs and monitoring

| Log | Where |
| --- | --- |
| Application warnings and errors | `$LOG_DIR/technoflow_crm.log` (own server) · Render → Logs |
| Web requests | `/var/log/technoflow_crm/access.log` · Render → Logs |
| Gunicorn | `/var/log/technoflow_crm/gunicorn.log`, `journalctl -u technoflow-crm` |
| Reminders | `journalctl -u technoflow-reminders`; last result in Settings → Approvals & reminders |
| Who did what | CRM → Audit log |
| Sign-ins | CRM → User Management → Login history |

Health check: `GET /healthz/` returns `ok` (used by Render; usable by any uptime monitor).

## 8. Recovery procedures

| Problem | Fix |
| --- | --- |
| Admin locked out / forgot password | On the server: `python manage.py changepassword <username>` and `python manage.py axes_reset_username <username>` |
| Admin lost the authenticator phone | Another admin: User Management → Reset two-step sign-in. If none: `python manage.py shell -c "from accounts.models import EmployeeProfile as P; P.objects.filter(user__username='aniq').update(mfa_enabled=False, mfa_secret='')"` |
| Everyone locked out after an attack | `python manage.py axes_reset` |
| Site shows "Server error" | Read the error log (section 7); after a failed update, restore the previous code and backup |
| Disk full | Remove old backups / logs; check `MEDIA_ROOT` size |
| Wrong data entered | Use the audit log to see the previous values; payments: reverse; invoices: cancel (if unpaid) and reissue; quotations: revise |

## 9. Management commands

| Command | Purpose |
| --- | --- |
| `create_system_admin --username … --email … --first-name … --last-name … [--password-env VAR] [--if-missing]` | First / emergency System Administrator |
| `load_demo_users --password … [--no-password-change] [--allow-production]` | The five demo logins |
| `load_demo_data [--allow-production] [--if-missing]` | Fictional demonstration records (never on real data) |
| `send_reminders [--force]` | Daily reminders (once per day unless `--force`) |
| `migrate`, `collectstatic`, `check --deploy` | Standard Django maintenance |
| `axes_reset`, `axes_reset_username <name>` | Clear sign-in lockouts |
