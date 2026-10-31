"""
Shared settings for Technoflow CRM.

Every secret and environment-specific value is read from environment
variables (or a .env file in the project root). Nothing sensitive is
hardcoded here. See .env.example for the full list.
"""
import re
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, []),
    CSRF_TRUSTED_ORIGINS=(list, []),
    TIME_ZONE=(str, "Asia/Dubai"),
    MAX_UPLOAD_MB=(int, 20),
    AXES_FAILURE_LIMIT=(int, 5),
    AXES_COOLOFF_MINUTES=(int, 30),
    SESSION_IDLE_MINUTES=(int, 60),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")
# True only when the app runs behind our own Nginx reverse proxy
TRUST_X_FORWARDED_FOR = env.bool("TRUST_X_FORWARDED_FOR", default=False)
AXES_IPWARE_META_PRECEDENCE_ORDER = (
    ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"] if TRUST_X_FORWARDED_FOR else ["REMOTE_ADDR"]
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # third party
    "rest_framework",
    "axes",
    "simple_history",
    # Technoflow CRM apps (one per module)
    "core",
    "accounts",
    "customers",
    "leads",
    "visits",
    "communications",
    "tasks",
    "sales",
    "quotations",
    "orders",
    "invoicing",
    "performance",
    "reporting",
    "documents",
    "notifications",
    "owner",
    "meetings",
]

MIDDLEWARE = [
    # Answers the hosting platform's /healthz/ check before any other middleware,
    # so it works whatever Host header the platform sends.
    "core.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # serves CSS/JS/images in production
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "core.middleware.RequestContextMiddleware",
    "accounts.middleware.ForcePasswordChangeMiddleware",
    # django-axes must be last
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

ROOT_URLCONF = "config.urls"
# Django's technical admin, for the System Administrator only. Change the path in production.
# Only letters, digits, "-" and "_" are kept, so any value is a safe single URL segment.
ADMIN_URL = re.sub(r"[^A-Za-z0-9_-]", "", env("ADMIN_URL", default="tf-admin")) or "tf-admin"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.crm_context",
            ],
        },
    },
]

# Database: DATABASE_URL, e.g.
#   postgres://technoflow:password@localhost:5432/technoflow_crm
#   sqlite:///db.sqlite3   (development only)
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Passwords: Django's PBKDF2 hashing (never stored in plain text)
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True
DATE_FORMAT = "d-M-Y"
DATETIME_FORMAT = "d-M-Y H:i"
SHORT_DATE_FORMAT = "d-M-Y"

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded documents are private: they are stored outside the web root
# in production and only served through permission-checked views.
MEDIA_ROOT = Path(env("MEDIA_ROOT", default=str(BASE_DIR / "media" / "private")))
MAX_UPLOAD_MB = env("MAX_UPLOAD_MB")
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_MB * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# Sessions
SESSION_COOKIE_AGE = env("SESSION_IDLE_MINUTES") * 60
SESSION_SAVE_EVERY_REQUEST = True  # idle timeout, refreshed on activity
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# Login lockout (django-axes)
AXES_FAILURE_LIMIT = env("AXES_FAILURE_LIMIT")
AXES_COOLOFF_TIME = env("AXES_COOLOFF_MINUTES") / 60  # hours
# Lock a username only for the address the failures came from. Locking by address alone
# would block every employee in an office that shares one internet connection.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/locked_out.html"

# Email (SMTP). Leave EMAIL_HOST empty to write emails to the console.
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="crm@technoflow.com")
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
}

# Public address of the CRM, used in notification emails (e.g. https://crm.technoflow.com)
SITE_URL = env("SITE_URL", default="").rstrip("/")

# Logging: errors to file, never logs passwords or secrets
LOG_DIR = Path(env("LOG_DIR", default=str(BASE_DIR / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}},
    "formatters": {"standard": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "technoflow_crm.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 10,
            "formatter": "standard",
        },
    },
    "loggers": {
        "django": {"handlers": ["console", "file"], "level": "WARNING"},
        "technoflow": {"handlers": ["console", "file"], "level": "INFO"},
    },
}

# CRM defaults (the System Administrator changes these in Settings,
# these are only the first-run values)
CRM_COMPANY_NAME = "Technoflow Trading LLC"
CRM_DEFAULT_CURRENCY = "AED"
