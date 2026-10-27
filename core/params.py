"""
Safe reading of values typed into the address bar (?page=, ?user=, ?date_from= ...).

Anything that is not a valid number or date is ignored instead of causing a
server error, so a mistyped or tampered link always shows a normal page.
"""
import datetime
from decimal import Decimal, InvalidOperation


def get_int(params, key, default=None):
    try:
        value = int(str(params.get(key, "")).strip())
    except (TypeError, ValueError):
        return default
    return value if -2**31 < value < 2**31 else default


def get_date(params, key, default=None):
    raw = str(params.get(key, "") or "").strip()
    if not raw:
        return default
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        return default


def get_decimal(params, key, default=None):
    try:
        return Decimal(str(params.get(key, "")).strip())
    except (InvalidOperation, ValueError):
        return default


def get_choice(params, key, allowed, default=None):
    value = params.get(key)
    return value if value in allowed else default
