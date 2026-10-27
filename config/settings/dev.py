"""Development settings: SQLite allowed, debug on, emails to console."""
import os

os.environ.setdefault("DEBUG", "True")
os.environ.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
os.environ.setdefault(
    "SECRET_KEY",
    # Development only. prod.py refuses to start without a real SECRET_KEY.
    "dev-only-insecure-key-change-me",
)

from .base import *  # noqa: E402,F401,F403

# WhiteNoise is only needed in production (runserver serves static files itself)
MIDDLEWARE = [m for m in MIDDLEWARE if not m.startswith("whitenoise")]  # noqa: F405
