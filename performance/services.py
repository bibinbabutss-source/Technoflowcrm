"""
Targets and the KPI scorecard.

    Achievement % = Actual ÷ Target × 100          (no target or a zero target → "No target", never an error)
    KPI score     = min(Achievement %, 100)
    Overall score = Σ (weight × score) ÷ Σ weights of the KPIs that have a target   (out of 100)
    Rating        = bands from Settings (Excellent / Good / Satisfactory / Needs improvement)
"""
from decimal import ROUND_HALF_UP, Decimal

from core.models import CompanyProfile
from core.money import achievement_pct
from reporting.metrics import KPI_CODES, kpi_actual, period_bounds, previous_period

from .models import KPIDefinition, SalesTarget

DEFAULT_WEIGHTS = {"orders_booked": 25, "invoiced": 20, "collected": 15, "visits_completed": 15,
                   "new_customers": 10, "opportunities_won": 5, "quotations_value": 5, "leads_created": 5,
                   "conversion_rate": 0, "followup_completion": 0}

DESCRIPTIONS = {
    "orders_booked": "Confirmed sales orders, value excluding VAT, by confirmation date (assigned employee).",
    "invoiced": "Issued invoices (not drafts or cancelled), total incl. VAT, by invoice date (order's employee).",
    "collected": "Payments allocated to invoices of the employee's orders, by payment date, net of reversals. "
                 "Company-wide: all payments received.",
    "quotations_value": "Grand total of quotation revisions sent to customers, by sent date (salesperson).",
    "leads_created": "Leads registered in the period (by who created them).",
    "visits_completed": "Customer visits marked completed, by visit date (assigned employee).",
    "new_customers": "Customers created in the period (assigned Sales Engineer).",
    "opportunities_won": "Opportunities moved to Won in the period (assigned Sales Engineer).",
    "conversion_rate": "Leads won ÷ leads closed (won + lost) in the period × 100.",
    "followup_completion": "Tasks due in the period completed on or before their due date ÷ tasks due × 100.",
    "won_value": "Estimated value of opportunities moved to Won in the period (by closing date), owner = assigned "
                 "Sales Engineer, else Sales Coordinator, else who created it. Includes imported completed sales.",
}


def seed_kpis():
    for order, (code, label, unit) in enumerate(KPI_CODES):
        KPIDefinition.objects.get_or_create(code=code, defaults={
            "name": label, "unit": unit, "description": DESCRIPTIONS[code], "weight": DEFAULT_WEIGHTS.get(code, 0),
            "sort_order": order})


def scorecard(employee, period_type, ref_date, *, compare=True):
    """KPI rows for one employee (or the company when employee is None) for the period containing ref_date."""
    start, end = period_bounds(period_type, ref_date)
    ids = None if employee is None else {employee.pk}
    targets = {t.kpi_id: t for t in SalesTarget.objects.filter(employee=employee, period_type=period_type,
                                                               period_start=start).select_related("kpi")}
    rows = []
    weighted_sum, weight_total = Decimal(0), Decimal(0)
    pstart, pend = previous_period(period_type, start)
    for kpi in KPIDefinition.objects.filter(is_active=True):
        actual = kpi_actual(kpi.code, ids, start, end)
        target = targets.get(kpi.pk)
        pct = achievement_pct(actual, target.target_value) if target and actual is not None else None
        score = min(pct, Decimal(100)) if pct is not None else None
        if score is not None and kpi.weight > 0:
            weighted_sum += kpi.weight * score
            weight_total += kpi.weight
        prev = kpi_actual(kpi.code, ids, pstart, pend) if compare else None
        rows.append({
            "kpi": kpi, "target": target.target_value if target else None, "actual": actual,
            "remaining": max(target.target_value - actual, Decimal(0)) if target and actual is not None else None,
            "pct": pct, "score": score, "previous": prev,
            "change": (actual - prev) if (actual is not None and prev is not None) else None,
        })
    overall = (weighted_sum / weight_total).quantize(Decimal("0.1"), ROUND_HALF_UP) if weight_total else None
    return {"rows": rows, "start": start, "end": end, "overall": overall,
            "rating": CompanyProfile.get().rating_for(overall), "previous_start": pstart, "previous_end": pend}


def ranking(users, period_type, ref_date):
    """Team ranking by overall score, then by order bookings."""
    rows = []
    for u in users:
        card = scorecard(u, period_type, ref_date, compare=False)
        booked = next((r["actual"] for r in card["rows"] if r["kpi"].code == "orders_booked"), Decimal(0))
        rows.append({"user": u, "overall": card["overall"], "rating": card["rating"], "booked": booked or 0,
                     "rows": card["rows"]})
    rows.sort(key=lambda r: (r["overall"] is None, -(r["overall"] or 0), -(r["booked"] or 0)))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows
