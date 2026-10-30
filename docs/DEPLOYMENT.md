# Deploying the CRM online with GitHub and Render — beginner guide

This guide takes the CRM from your Windows laptop to a public web address such as
`https://technoflow-crm.onrender.com`, for a demonstration.

There are three stages, in this order. Do not skip stage A.

| Stage | Where | What happens |
| --- | --- | --- |
| A. Test locally | Your laptop | Prove the deployment changes work before anything goes online |
| B. Put the code on GitHub | GitHub (private repository) | GitHub stores the code. It does not run it |
| C. Deploy on Render | render.com | Render reads the code from GitHub, builds it and runs it with a PostgreSQL database |

---

## How the online version works (2-minute overview)

- **Your laptop** uses `config/settings/dev.py` and a small file database, `db.sqlite3`.
  Nothing on your laptop changes when you deploy.
- **Render** uses `config/settings/prod.py` and a separate **PostgreSQL** database that Render creates for you.
  Your laptop's `db.sqlite3` is **not** uploaded; the online CRM starts with an empty database
  and its own administrator.
- **render.yaml** tells Render what to create (one database, one web service) and which settings to use.
- **build.sh** runs on Render at every deploy: installs packages, checks settings, prepares CSS/JS
  (`collectstatic`), updates the database structure (`migrate`), and creates the first administrator
  and optional demo users if they do not already exist.
- **Gunicorn** is the program that runs the CRM on Render. **WhiteNoise** serves the CSS, JavaScript and logo.
- **Secrets** (secret key, passwords) are never in GitHub. Render generates or asks for them and keeps
  them in its dashboard.

---

## Stage A — test the changes on your laptop

Open **PowerShell** in the project folder (the folder that contains `manage.py`).
In File Explorer: click the address bar, type `powershell`, press Enter.

### A1. Activate your virtual environment and install packages

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

You should see `(.venv)` at the start of the prompt line. `pip` installs the packages the online
version needs (Gunicorn, WhiteNoise, the PostgreSQL driver). They do not change how the CRM runs locally.

### A2. Run the automated tests

```powershell
python -m pytest
```

Expected last line: **`100 passed`**. The file `tests/test_deployment.py` checks the deployment
settings, the health check, the build script's line endings, and that no secret is written into a file.

If anything fails, stop and send the output before going further.

### A3. Rehearse the production settings (no PostgreSQL needed)

These commands switch **this PowerShell window only** to production settings with a fake database
address. They do not connect to any database and do not touch your local data.

```powershell
$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(50))"
$env:DATABASE_URL = "postgresql://test:test@localhost:5432/test"
$env:RENDER_EXTERNAL_HOSTNAME = "technoflow-crm.onrender.com"

python manage.py check --deploy
python manage.py collectstatic --no-input
```

Expected:

- `check --deploy` shows **one** warning, `security.W021` (HSTS preload). That one is expected and harmless.
  Any line starting with `E` (error) means something is wrong.
- `collectstatic` ends with something like `... static files copied to '...\staticfiles', ... post-processed.`
  If it says a file "could not be found", stop and send the output.

Now **close this PowerShell window**. This removes the production settings from the window, so the next
`runserver` uses your normal laptop settings again.

### A4. Check the CRM still works normally

Open a new PowerShell window in the project folder:

```powershell
.venv\Scripts\activate
python manage.py runserver
```

Open http://127.0.0.1:8000, sign in, open Dashboard, User Management, Roles & Limits and Settings.
Stop the server with `Ctrl + C`.

---

## Stage B — put the code on GitHub

Use **GitHub Desktop** (free, no commands). The GitHub website's upload page accepts only 100 files at a
time, and this project has more.

1. Create an account at https://github.com if you do not have one.
2. Install GitHub Desktop from https://desktop.github.com and sign in.
3. **File → Add local repository** → choose the project folder (the one with `manage.py`).
   If it says the folder is not a repository, click **create a repository** there.
   - Name: `technoflow-crm`
   - Git ignore: **None** (the project already has its own `.gitignore`)
   - Click **Create repository**.
4. **Check the file list on the left before committing.** It must **not** contain:
   `.env`, `db.sqlite3`, `.venv`, `staticfiles`, `logs`.
   If you see any of these, stop: the `.gitignore` file is missing from the folder.
5. Bottom left: Summary `Technoflow CRM - all phases`, click **Commit to main**.
6. Click **Publish repository**. Keep **"Keep this code private"** ticked. Click **Publish**.

Your code is now on GitHub. Nothing is running yet.

---

## Stage C — deploy on Render

### C1. Create the Render account

1. Go to https://render.com → **Get Started** → **Sign up with GitHub**.
2. When GitHub asks which repositories Render may access, choose **Only select repositories** →
   `technoflow-crm`.

### C2. Create everything from the Blueprint

1. In the Render dashboard: **New + → Blueprint**.
2. Select the `technoflow-crm` repository. Render reads `render.yaml` and shows:
   - a PostgreSQL database `technoflow-crm-db`
   - a web service `technoflow-crm`
3. Give the Blueprint a name (e.g. `technoflow-crm`).
4. Render asks for the values marked `sync: false`. Fill them in:

| Variable | What to type | Example |
| --- | --- | --- |
| `ADMIN_URL` | A hard-to-guess path for Django's technical admin. Letters, digits, `-`, `_` only | `control-7421` |
| `ADMIN_USERNAME` | Your sign-in name for the online CRM | `aniq` |
| `ADMIN_EMAIL` | Your work email | `you@company.com` |
| `ADMIN_FIRST_NAME` | First name | `Mohamed` |
| `ADMIN_LAST_NAME` | Last name | `Aniq` |
| `ADMIN_TEMP_PASSWORD` | A temporary password: **10+ characters, not a common password, not only digits**. You change it at first sign-in | (your choice) |
| `REMOVE_DEMO_DATA` | Leave empty. Set to `yes` for one deploy only, after a backup, to remove the fictional demo records (see "Starting fresh") | (empty) |
| `SITE_URL` | Optional. The CRM's address, used for links in notification e-mails. Empty = the onrender.com address | `https://technoflow-crm.onrender.com` |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | Optional. Your SMTP server, to send password-reset and notification e-mails. Empty = no e-mails (in-app notifications still work) | `smtp.office365.com` |

A deploy never creates demo data (changed Oct 2026). Every deploy prints a preview of any fictional demo
records it finds ("Demo data check"), without changing anything. The demo commands (`load_demo_users`,
`load_demo_data`) are only for a laptop or a separate demo server.

   Do not reuse a password you use anywhere else.

5. Click **Apply** (or **Deploy Blueprint**).

### C3. Watch the first deploy

Click the `technoflow-crm` web service → **Events / Logs**. The first deploy takes a few minutes.
The build log shows these steps, in order:

```text
==> Installing Python packages
==> Checking production settings
==> Collecting static files (CSS, JavaScript, logo)
==> Applying database migrations
==> First System Administrator
System Administrator 'aniq' created. A password change is required at first sign-in.
==> Demo users
==> Fictional demo records
Demo data loaded: 5 customers, 6 leads, 8 opportunities, ...
==> Build finished
```

Two warnings in the "Checking production settings" step are expected: `security.W009` (Render's generated
key is 44 characters; it is a strong 256-bit random value) and `security.W021`.

When the status shows **Live**, click the address at the top of the page
(e.g. `https://technoflow-crm.onrender.com`).

### C4. First sign-in

1. Sign in with `ADMIN_USERNAME` and `ADMIN_TEMP_PASSWORD`.
2. The CRM asks for a new password. Choose a strong one and keep it safe.
3. Go to **Settings** and check the company details.
4. Optional, recommended: in Render → web service → **Environment**, delete `ADMIN_TEMP_PASSWORD`.
   It is only used once.

On a laptop or demo server where you ran `load_demo_users`, these demo logins exist (deploys to Render no
longer create them):

| Username | Role |
| --- | --- |
| `demo.director` | Sales Director |
| `demo.accounts` | Accounts |
| `demo.engineer` | Sales Engineer |
| `demo.coordinator` | Sales Coordinator (linked to demo.engineer) |

There is no `demo.admin` online: the System Administrator role allows one account, and that is yours.
Before real business use, deactivate the demo users in **User Management**.

---

## Keeping your data across deployments

**Deploying does not erase data.** The web service (code) and the database are separate services on Render.
A deploy replaces the code only. `migrate` only adds or changes database structure for new features; the
first-administrator and demo-user steps skip anything that already exists. Sign-in sessions are stored in the
database too, so users stay signed in across deploys.

What **can** lose data, and how to avoid it:

| Risk | What happens | What to do |
| --- | --- | --- |
| **Free database expiry** | Render's free PostgreSQL expires **30 days** after creation. You then have **14 days** to upgrade; after that Render deletes it and its data. Free databases have **no backups**. | For a short demo, free is fine. To keep the records, upgrade the database to the smallest paid plan (`0.1c-256mb`, about USD 6/month) **before day 30**: Render → `technoflow-crm-db` → **Upgrade**. The data stays. Paid plans include point-in-time recovery. Also change `plan: free` to `plan: 0.1c-256mb` under `databases:` in `render.yaml` so the file matches. |
| **Renaming the database in render.yaml** | Render treats a new name as a new, empty database | Never change `name: technoflow-crm-db` after the first deploy |
| **Deleting the database service or the Blueprint in Render** | The database is deleted | Do not delete them; to stop paying for the web service, suspend it instead |
| **Uploaded documents on the web service's disk** | The free web service's disk is temporary: uploaded documents are **lost at every deploy and restart**. Database records are not affected | For a demo, accept it (or do not upload documents). For real use: upgrade the web service to a paid plan (Starter) and add a **persistent disk** mounted at `/var/data`, then set the environment variable `MEDIA_ROOT=/var/data/media` (the commented `disk:` block in `render.yaml` shows how). Or run the CRM on your own server (Admin Guide) |
| **Daily reminders** | The free web service sleeps, so nothing runs on a timer | Reminders run automatically on the first dashboard visit each day; Settings → Approvals & reminders → **Run reminders now** runs them on demand. On a paid plan you can add a Render Cron Job running `python manage.py send_reminders` |
| **No copy of your own** | One accident loses everything | On a paid database, use Render's backups. You can also download a copy: Render → database → **Connect → External Database URL**, then on a computer with PostgreSQL installed: `pg_dump "<External URL>" -Fc -f crm_backup.dump` |

The free **web service** loses nothing important when it sleeps: it only stops after 15 minutes without
visitors, and the first visit after that takes about a minute while it starts again.

---

## Starting fresh: removing the demo data

The free plan has no command console, so the removal runs during a deploy:

1. **Back up the database first** (Render → technoflow-crm-db → Recovery / Backups).
2. Render → **technoflow-crm** → **Environment**:
   - delete `LOAD_DEMO_DATA` and `DEMO_USERS_PASSWORD` if they are still there (they are no longer used);
   - add `REMOVE_DEMO_DATA` = `yes`.

   Then click **Save, rebuild, and deploy**.
3. In the deploy log, the line "Removing demo data" lists what was removed.
4. Remove `REMOVE_DEMO_DATA` again and save. Later deploys only show the "Demo data check" preview.

Only the fictional "Demo:" customers and leads, everything linked to them, and the demo logins' targets,
reports and notifications are removed. The demo logins are deactivated, and your real records and users are
kept. Numbering (QT-, INV-, SO- …) restarts at 0001 where no records are left.

## Updating the online CRM later

1. Change and test on your laptop (Stage A).
2. GitHub Desktop: commit, then **Push origin**.
3. Render deploys automatically. The database and its records stay.

---

## Every environment variable

Set by `render.yaml` automatically (nothing to type):

| Variable | Value | Purpose |
| --- | --- | --- |
| `PYTHON_VERSION` | `3.12.8` | Python version on Render |
| `DJANGO_SETTINGS_MODULE` | `config.settings.prod` | Use the production settings |
| `DATABASE_URL` | from `technoflow-crm-db` | PostgreSQL connection, including its password |
| `SECRET_KEY` | generated once | Signs sessions and password-reset links |
| `DEBUG` | `False` | Never show error details to visitors |
| `TIME_ZONE` | `Asia/Dubai` | Dates and times |
| `RENDER_EXTERNAL_HOSTNAME` | set by Render itself | Your onrender.com address; the CRM allows it automatically |
| `PORT` | set by Render itself | The port Gunicorn listens on |

Typed by you in Render: `ADMIN_URL`, `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_FIRST_NAME`, `ADMIN_LAST_NAME`,
`ADMIN_TEMP_PASSWORD`, and, for one deploy only, `REMOVE_DEMO_DATA` (table in C2).

Optional, add in Render → Environment only if needed: `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` (only for your
own domain, e.g. `crm.company.com` and `https://crm.company.com`), `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` (to send password-reset emails; without them the
email text only appears in Render's logs), `AXES_FAILURE_LIMIT`, `AXES_COOLOFF_MINUTES`, `SESSION_IDLE_MINUTES`.
`.env.example` lists them all with explanations.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| Build fails at "First System Administrator" with a password message | `ADMIN_TEMP_PASSWORD` too short, too common or only digits | Render → Environment → change it → **Manual Deploy → Deploy latest commit** |
| Build fails with `$'\r': command not found` | `build.sh` was saved with Windows line endings | Keep `.gitattributes` in the project; in VS Code, set the file's line ending (bottom right) to `LF`, commit, push |
| Build fails at "Collecting static files" with "could not be found" | A CSS/JS file refers to a missing file | Send the log line; do not delete files from `static/` |
| Nobody can sign in | `ADMIN_USERNAME` was left empty | Fill the five `ADMIN_*` values in Render → Environment, then Manual Deploy |
| "Too many failed sign-in attempts" | 5 wrong passwords for that username or from that address | Wait 30 minutes (`AXES_COOLOFF_MINUTES`) |
| "Bad Request (400)" on your own domain | Domain not allowed | Add it to `ALLOWED_HOSTS` and `https://` + domain to `CSRF_TRUSTED_ORIGINS` |
| First page takes about a minute | Free web service was asleep | Normal on the free plan |
| Database "suspended" or "expired" | Free database passed 30 days | Upgrade it within the 14-day grace period |
