"""
Production settings: PostgreSQL, HTTPS, secure cookies, WhiteNoise static files.

Used on Render (DJANGO_SETTINGS_MODULE=config.settings.prod) and on any
Linux server. Every value comes from environment variables; see .env.example.
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, DATABASES, DEBUG, SECRET_KEY, env

# ---------------------------------------------------------------- safety checks
# The app refuses to start with unsafe production settings instead of running insecurely.
if DEBUG:
    raise ImproperlyConfigured("DEBUG must be False in production.")
if not SECRET_KEY or SECRET_KEY.startswith(("dev-only", "test-only")) or len(SECRET_KEY) < 40:
    raise ImproperlyConfigured("Set a strong SECRET_KEY (40+ characters) in the environment.")
if "sqlite" in DATABASES["default"]["ENGINE"]:
    raise ImproperlyConfigured("Production must use PostgreSQL. Set DATABASE_URL.")

# ---------------------------------------------------------------- Render.com
# Render sets RENDER_EXTERNAL_HOSTNAME automatically, e.g. technoflow-crm.onrender.com
_render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if _render_host:
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, _render_host]
    CSRF_TRUSTED_ORIGINS = [*CSRF_TRUSTED_ORIGINS, f"https://{_render_host}"]
    if not SITE_URL:  # noqa: F405 - links in notification e-mails
        SITE_URL = f"https://{_render_host}"
    # Render's proxy puts the visitor's address in X-Forwarded-For.
    TRUST_X_FORWARDED_FOR = True
    AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS is empty. Set ALLOWED_HOSTS (e.g. crm.example.com) or deploy on Render, "
        "which sets RENDER_EXTERNAL_HOSTNAME automatically."
    )

# ---------------------------------------------------------------- database
# Re-use database connections for 60 seconds instead of opening one per request,
# and check a re-used connection is still alive before using it.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True

# ---------------------------------------------------------------- static files
# collectstatic (run by build.sh) copies CSS/JS/images to STATIC_ROOT with
# fingerprinted, compressed names; WhiteNoise serves them with long caching.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# ---------------------------------------------------------------- HTTPS
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False
