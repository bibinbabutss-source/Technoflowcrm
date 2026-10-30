#!/usr/bin/env bash
# Build script run by Render.com on every deploy (also usable on any Linux server).
#
# It never deletes data: "migrate" only applies new database changes, and the
# administrator / demo-user steps skip anything that already exists.
set -o errexit   # stop at the first failing command, so a broken build is never published
set -o nounset   # treat unset variables as errors (optional ones use ${NAME:-})
set -o pipefail

echo "==> Installing Python packages"
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Checking production settings"
python manage.py check --deploy --fail-level ERROR

echo "==> Collecting static files (CSS, JavaScript, logo)"
python manage.py collectstatic --no-input

echo "==> Applying database migrations"
python manage.py migrate --no-input

echo "==> First System Administrator"
if [ -n "${ADMIN_USERNAME:-}" ]; then
  python manage.py create_system_admin --if-missing \
    --username "$ADMIN_USERNAME" --email "${ADMIN_EMAIL:?ADMIN_EMAIL is not set}" \
    --first-name "${ADMIN_FIRST_NAME:?ADMIN_FIRST_NAME is not set}" \
    --last-name "${ADMIN_LAST_NAME:?ADMIN_LAST_NAME is not set}" \
    --password-env ADMIN_TEMP_PASSWORD
else
  echo "    ADMIN_USERNAME is not set; skipping. (Nobody can sign in until a System Administrator exists.)"
fi

# Demo data is never created by a deploy (removed Oct 2026). Use load_demo_users / load_demo_data only on a
# laptop or a separate demo server.
if [ "${REMOVE_DEMO_DATA:-}" = "yes" ]; then
  # Starting fresh (after a database backup): remove the fictional demo records, deactivate the demo logins.
  # Genuine records, users, roles and settings are kept. Running it again does nothing.
  echo "==> Removing demo data (REMOVE_DEMO_DATA=yes)"
  python manage.py remove_demo_data --confirm
else
  echo "==> Demo data check (preview only, nothing is changed; set REMOVE_DEMO_DATA=yes to remove)"
  python manage.py remove_demo_data || true
fi

echo "==> Build finished"
