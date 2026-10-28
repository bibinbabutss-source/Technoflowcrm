from decimal import Decimal

from django import template

from quotations.document import rich_text

register = template.Library()


@register.filter
def rich(value):
    return rich_text(value)


@register.filter
def amount(value):
    """1234.5 -> '1,234.50' (no currency, as on the printed price schedule)."""
    try:
        return f"{Decimal(value):,.2f}"
    except Exception:
        return value


@register.filter
def qty(value):
    try:
        d = Decimal(value).normalize()
        return f"{d:f}"
    except Exception:
        return value
