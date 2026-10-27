"""
Request-level helpers.

- HealthCheckMiddleware answers the hosting platform's /healthz/ check.
- RequestContextMiddleware keeps the current request available to model
  save() and audit signals, so every change is stamped with the user and
  IP address that made it.
"""
import ipaddress
import threading

from django.http import HttpResponse

_local = threading.local()

HEALTH_PATH = "/healthz/"


class HealthCheckMiddleware:
    """
    Render (and most hosts) call /healthz/ to check the app is running.
    Their checker may send a Host header such as "localhost:10000", which
    Django's ALLOWED_HOSTS protection would reject with "400 Bad Request"
    and fail the deploy. This middleware runs first and answers the check
    without reading the Host header or touching the database.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == HEALTH_PATH and request.method in ("GET", "HEAD"):
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)


def get_current_request():
    return getattr(_local, "request", None)


def get_current_user():
    request = get_current_request()
    return getattr(request, "user", None) if request else None


def _valid_ip(value):
    """Return value if it is a real IPv4/IPv6 address, otherwise None."""
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


def get_client_ip(request):
    """
    Best available client IP address for the audit log and login history.

    REMOTE_ADDR is the address that connected to the server. Behind a hosting
    platform's proxy (Render, Nginx) that is the proxy itself, so when
    TRUST_X_FORWARDED_FOR is on we use the first valid address in the
    X-Forwarded-For header (the visitor, as reported by the proxy chain).

    The value is validated because the database column only accepts real IP
    addresses: a forged header such as "X-Forwarded-For: hello" must never
    break sign-in.
    """
    if request is None:
        return None
    from django.conf import settings

    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(","):
            ip = _valid_ip(part)
            if ip:
                return ip
    return _valid_ip(request.META.get("REMOTE_ADDR"))


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            return self.get_response(request)
        finally:
            _local.request = None
