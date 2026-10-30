"""Sidebar definition. Each item is shown only to users holding its capability (pages re-check on the server).

The Finance section disappears automatically while the Finance module is turned off, because its
permissions are switched off (see accounts.models.EmployeeProfile.capability_codes).
"""
from django.urls import NoReverseMatch, reverse

from accounts.permissions import get_profile

# label, Bootstrap icon, url name, capability, extra path prefixes that belong to this item
NAV_SECTIONS = [
    ("Owner", [
        ("Owner Dashboard", "speedometer", "owner:dashboard", "owner.dashboard", ()),
        ("Pending Approvals", "patch-check", "owner:approvals", "approvals.view", ()),
    ]),
    ("Sales", [
        ("Dashboard", "speedometer2", "core:dashboard", "dashboard.view", ()),
        ("Leads", "funnel", "leads:list", "leads.view", ("/dashboards/leads/",)),
        ("Customer Visits", "calendar-check", "visits:list", "visits.view", ("/dashboards/visits/",)),
        ("Customers", "building", "customers:list", "customers.view", ("/dashboards/customers/",)),
        ("Sales Pipeline", "kanban", "sales:kanban", "pipeline.view", ("/pipeline/forecast/", "/dashboards/pipeline/")),
        ("Opportunities", "lightning-charge", "sales:pipeline", "pipeline.view", ("/dashboards/opportunities/",)),
        ("Projects", "briefcase", "sales:projects", "projects.view", ("/dashboards/projects/",)),
        ("Quotations", "file-earmark-text", "quotations:list", "quotations.view", ("/dashboards/quotations/",)),
    ]),
    ("Finance", [
        ("Sales Orders", "cart-check", "orders:list", "orders.view", ()),
        ("Invoices", "receipt", "invoicing:list", "invoices.view", ()),
        ("Collections", "cash-coin", "invoicing:collections", "collections.view", ()),
    ]),
    ("Work", [
        ("Employee Performance", "person-lines-fill", "team:list", "performance.view", ()),
        ("Daily Reports", "journal-check", "dailyreports:list", "performance.view", ()),
        ("Targets & KPIs", "bullseye", "performance:overview", "targets.view", ()),
        ("Team Calendar", "calendar3", "owner:calendar", "calendar.view", ()),
        ("Tasks & Follow-ups", "check2-square", "tasks:list", "tasks.view", ()),
        ("Communication History", "chat-left-text", "communications:list", "communications.view", ()),
        ("Documents", "folder2-open", "documents:list", "documents.view", ()),
        ("Reports", "bar-chart-line", "reporting:index", "reports.view", ()),
        ("Import from Excel", "file-earmark-arrow-up", "reporting:import_start", "imports.own", ()),
        ("Notifications", "bell", "notifications:list", "notifications.view", ()),
    ]),
    ("Administration", [
        ("User Management", "people", "accounts:user_list", "users.manage", ()),
        ("Roles & Limits", "shield-lock", "accounts:role_list", "roles.manage", ()),
        ("Modules & Approvals", "toggles", "owner:modules", "modules.manage", ()),
        ("Settings", "gear", "core:settings_home", "settings.manage", ()),
        ("Audit Log", "journal-text", "core:audit_log", "audit.view", ()),
    ]),
]


def _match_length(path, item_path, extras):
    """Length of the longest prefix of `path` claimed by a menu item (0 = no match)."""
    if item_path == "/":
        return 1 if path == "/" else 0
    best = len(item_path) if path.startswith(item_path) else 0
    for extra in extras:
        if path.startswith(extra):
            best = max(best, len(extra))
    return best


def build_nav(user, path=None):
    profile = get_profile(user)
    if profile is None:
        return []
    codes = profile.capability_codes()
    sections, everything = [], []
    for title, items in NAV_SECTIONS:
        visible = []
        for label, icon, url_name, cap, extras in items:
            if cap not in codes:
                continue
            try:
                url = reverse(url_name)
            except NoReverseMatch:
                continue
            item = {"label": label, "icon": icon, "url_name": url_name, "url": url, "active": False,
                    "_score": _match_length(path or "", url, extras)}
            visible.append(item)
            everything.append(item)
        if visible:
            sections.append({"title": title, "items": visible})
    best = max(everything, key=lambda i: i["_score"], default=None)
    if best is not None and best["_score"]:
        best["active"] = True  # exactly one highlighted item: the most specific match
    return sections
