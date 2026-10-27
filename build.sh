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

echo "==> Demo users"
if [ -n "${DEMO_USERS_PASSWORD:-}" ]; then
  python manage.py load_demo_users --password-env DEMO_USERS_PASSWORD --allow-production --no-password-change
  if [ "${LOAD_DEMO_DATA:-false}" = "true" ]; then
    echo "==> Fictional demo records"
    python manage.py load_demo_data --allow-production --if-missing
  fi
else
  echo "    DEMO_USERS_PASSWORD is not set; no demo users created."
fi

echo "==> Build finished"
