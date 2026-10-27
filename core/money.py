"""
The single calculation layer for quotations, orders and invoices.

Rules (Phase 1 plan, section 8):

    Line net      = round(Qty × Unit price × (1 − Line discount % / 100), 2)
    Subtotal      = Σ Line net
    Taxable       = Subtotal − Header discount   (the header discount is spread across lines
                                                  in proportion to their net, so each tax rate
                                                  gets the right base; the last line takes any
                                                  rounding remainder)
    Tax           = Σ over each tax rate: round(Taxable at that rate × rate / 100, 2)
    Grand total   = Taxable + Tax

All amounts are Decimal and rounded half-up to 2 places; floats are never used.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

TWO = Decimal("0.01")
ZERO = Decimal("0.00")


def q2(value):
    return Decimal(value or 0).quantize(TWO, rounding=ROUND_HALF_UP)


def line_net(quantity, unit_price, discount_pct=0):
    q, p, d = Decimal(quantity or 0), Decimal(unit_price or 0), Decimal(discount_pct or 0)
    return q2(q * p * (Decimal(1) - d / Decimal(100)))


def line_gross(quantity, unit_price):
    return q2(Decimal(quantity or 0) * Decimal(unit_price or 0))


@dataclass
class LineInput:
    quantity: Decimal
    unit_price: Decimal
    discount_pct: Decimal
    tax_rate: Decimal  # percent


@dataclass
class LineResult:
    gross: Decimal
    line_discount: Decimal
    net: Decimal
    header_discount_share: Decimal
    taxable: Decimal
    tax: Decimal


@dataclass
class Totals:
    gross: Decimal = ZERO
    line_discounts: Decimal = ZERO
    subtotal: Decimal = ZERO          # Σ line net
    header_discount: Decimal = ZERO
    discount_total: Decimal = ZERO    # line discounts + header discount
    taxable: Decimal = ZERO
    tax: Decimal = ZERO
    grand_total: Decimal = ZERO
    tax_by_rate: "OrderedDict" = field(default_factory=OrderedDict)
    lines: list = field(default_factory=list)


def calculate(lines, header_discount=ZERO):
    """lines: iterable of LineInput. Returns Totals with a LineResult per line (same order)."""
    lines = list(lines)
    header_discount = q2(header_discount)
    results = []
    for ln in lines:
        gross = line_gross(ln.quantity, ln.unit_price)
        net = line_net(ln.quantity, ln.unit_price, ln.discount_pct)
        results.append([gross, gross - net, net])
    subtotal = sum((r[2] for r in results), ZERO)
    if header_discount < 0:
        raise ValueError("The header discount cannot be negative.")
    if header_discount > subtotal:
        raise ValueError("The header discount cannot be larger than the subtotal.")
    # spread the header discount in proportion to line net
    shares = [ZERO] * len(results)
    if header_discount and subtotal:
        remaining = header_discount
        positive = [i for i, r in enumerate(results) if r[2] > 0]
        for n, i in enumerate(positive):
            if n == len(positive) - 1:
                shares[i] = remaining
            else:
                shares[i] = q2(header_discount * results[i][2] / subtotal)
                remaining -= shares[i]
    totals = Totals(header_discount=header_discount, subtotal=subtotal)
    by_rate = OrderedDict()
    for ln, r, share in zip(lines, results, shares):
        taxable = r[2] - share
        rate = Decimal(ln.tax_rate or 0)
        by_rate.setdefault(rate, ZERO)
        by_rate[rate] += taxable
        totals.lines.append(LineResult(gross=r[0], line_discount=r[1], net=r[2], header_discount_share=share,
                                       taxable=taxable, tax=q2(taxable * rate / Decimal(100))))
    totals.gross = sum((r[0] for r in results), ZERO)
    totals.line_discounts = sum((r[1] for r in results), ZERO)
    totals.discount_total = totals.line_discounts + header_discount
    totals.taxable = subtotal - header_discount
    for rate, base in by_rate.items():
        tax = q2(base * rate / Decimal(100))
        totals.tax_by_rate[rate] = {"base": base, "tax": tax}
        totals.tax += tax
    totals.grand_total = totals.taxable + totals.tax
    return totals


def achievement_pct(actual, target):
    """Achievement % = Actual ÷ Target × 100. Returns None when there is no target (never divides by zero)."""
    target = Decimal(target or 0)
    if target <= 0:
        return None
    return (Decimal(actual or 0) / target * Decimal(100)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def split_by_percentages(total, percentages):
    """Split an amount by percentages; the last part takes the rounding remainder so parts add up exactly."""
    total = q2(total)
    parts, remaining = [], total
    for i, pct in enumerate(percentages):
        if i == len(percentages) - 1:
            parts.append(remaining)
        else:
            part = q2(total * Decimal(pct) / Decimal(100))
            parts.append(part)
            remaining -= part
    return parts
