"""Optional two-step sign-in with an authenticator app (TOTP, RFC 6238)."""
import time

import pyotp
import segno
from django.utils import timezone

ISSUER = "Technoflow CRM"
PENDING_SECONDS = 300
MAX_ATTEMPTS = 5


def new_secret():
    return pyotp.random_base32()


def provisioning_uri(secret, user):
    from core.models import CompanyProfile

    issuer = f"{CompanyProfile.get().company_name} CRM"[:60] or ISSUER
    return pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name=issuer)


def qr_svg(uri):
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)


def clean_code(code):
    return "".join(ch for ch in str(code or "") if ch.isdigit())


def verify(secret, code, last_counter=None):
    """Return the time-step counter used if the code is valid (and not a replay), else None."""
    code = clean_code(code)
    if len(code) != 6 or not secret:
        return None
    totp = pyotp.TOTP(secret)
    now = int(time.time())
    for offset in (0, -1, 1):
        counter = (now // totp.interval) + offset
        if totp.at(counter * totp.interval) == code:
            if last_counter is not None and counter <= last_counter:
                return None  # code already used
            return counter
    return None


def confirm_for_profile(profile, code):
    counter = verify(profile.mfa_secret, code, profile.mfa_last_counter)
    if counter is None:
        return False
    profile.mfa_last_counter = counter
    profile.save(update_fields=["mfa_last_counter"])
    return True


def start_pending(request, user, next_url):
    request.session["mfa_user"] = user.pk
    request.session["mfa_backend"] = getattr(user, "backend", "django.contrib.auth.backends.ModelBackend")
    request.session["mfa_next"] = next_url
    request.session["mfa_started"] = timezone.now().timestamp()
    request.session["mfa_attempts"] = 0


def clear_pending(request):
    for key in ("mfa_user", "mfa_backend", "mfa_next", "mfa_started", "mfa_attempts"):
        request.session.pop(key, None)
