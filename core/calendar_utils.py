"""Month calendar grid used by the visits and tasks calendars."""
import calendar
import datetime

from .params import get_int


def month_from_request(request):
    today = datetime.date.today()
    year = get_int(request.GET, "year", today.year)
    month = get_int(request.GET, "month", today.month)
    if not (1 <= month <= 12) or not (2000 <= year <= 2100):
        year, month = today.year, today.month
    return year, month


def build_month(year, month, events):
    """
    events: iterable of dicts {date, title, url, tone}
    returns weeks: [[{date, in_month, is_today, events:[...]}, ...7], ...]
    """
    by_day = {}
    for ev in events:
        by_day.setdefault(ev["date"], []).append(ev)
    cal = calendar.Calendar(firstweekday=0)  # weeks start on Monday
    today = datetime.date.today()
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        weeks.append([{"date": d, "in_month": d.month == month, "is_today": d == today,
                       "events": by_day.get(d, [])} for d in week])
    first = datetime.date(year, month, 1)
    prev_month = (first - datetime.timedelta(days=1)).replace(day=1)
    next_month = (first + datetime.timedelta(days=32)).replace(day=1)
    return {"weeks": weeks, "title": first.strftime("%B %Y"), "prev": prev_month, "next": next_month,
            "start": weeks[0][0]["date"], "end": weeks[-1][-1]["date"],
            "day_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
