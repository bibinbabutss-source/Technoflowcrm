from django import template
from django.urls import reverse

register = template.Library()


@register.filter
def has_cap(caps, code):
    """{% if crm_caps|has_cap:'users.manage' %} — display only; views re-check."""
    return code in (caps or ())


@register.simple_tag(takes_context=True)
def nav_active(context, url_name):
    request = context.get("request")
    if not request or not url_name:
        return ""
    path = reverse(url_name)
    if path == "/":
        return "active" if request.path == "/" else ""
    return "active" if request.path.startswith(path) else ""


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    """Keep current filters when changing page or sort."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    return "?" + params.urlencode() if params else "?"


@register.filter
def money(value, currency=None):
    from core.crud import money as fmt

    return fmt(value, currency)


@register.filter
def pct(value, places=1):
    if value is None or value == "":
        return "—"
    return f"{float(value):.{int(places)}f}%"


@register.filter
def fdate(value):
    from core.crud import fmt_date

    return fmt_date(value)


@register.filter
def person(user):
    from core.crud import person as p

    return p(user)


@register.simple_tag(takes_context=True)
def can(context, code):
    """{% can 'quotations.approve' as allowed %} — for showing buttons; views re-check."""
    return code in (context.get("crm_caps") or ())


@register.filter
def get_item(mapping, key):
    try:
        return mapping.get(key)
    except AttributeError:
        return None


@register.filter
def tone_class(tone):
    """'good' / 'info' / 'warn' / 'bad' / 'neutral' -> the CSS class of a status badge."""
    from core.crud import BADGE_CLASSES

    return BADGE_CLASSES.get(tone, "badge-inactive")
