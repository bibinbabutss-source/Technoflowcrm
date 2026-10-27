"""Settings used by the automated test suite."""
import os

os.environ.setdefault("SECRET_KEY", "test-only-key")
os.environ.setdefault("DATABASE_URL", "sqlite://:memory:")

from .base import *  # noqa: E402,F401,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast, tests only
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
AXES_FAILURE_LIMIT = 3

# WhiteNoise is only needed in production (runserver serves static files itself)
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith("whitenoise")]  # noqa: F405
