"""Sidebar definition. Each item is shown only to users holding its capability (pages re-check on the server)."""
from accounts.permissions import get_profile

# label, Bootstrap icon, url name, capability
NAV_SECTIONS = [
    ("Sales", [
        ("Dashboard", "speedometer2", "core:dashboard", "dashboard.view"),
        ("Customers", "building", "customers:list", "customers.view"),
        ("Leads", "funnel", "leads:list", "leads.view"),
        ("Customer Visits", "calendar-check", "visits:list", "visits.view"),
        ("Sales Pipeline", "kanban", "sales:pipeline", "pipeline.view"),
        ("Projects", "briefcase", "sales:projects", "projects.view"),
        ("Quotations", "file-earmark-text", "quotations:list", "quotations.view"),
    ]),
    ("Finance", [
        ("Sales Orders", "cart-check", "orders:list", "orders.view"),
        ("Invoices", "receipt", "invoicing:list", "invoices.view"),
        ("Collections", "cash-coin", "invoicing:collections", "collections.view"),
    ]),
    ("Work", [
        ("Targets & KPIs", "bullseye", "performance:overview", "targets.view"),
        ("Tasks & Follow-ups", "check2-square", "tasks:list", "tasks.view"),
        ("Communication History", "chat-left-text", "communications:list", "communications.view"),
        ("Documents", "folder2-open", "documents:list", "documents.view"),
        ("Reports", "bar-chart-line", "reporting:index", "reports.view"),
        ("Notifications", "bell", "notifications:list", "notifications.view"),
    ]),
    ("Administration", [
        ("User Management", "people", "accounts:user_list", "users.manage"),
        ("Roles & Limits", "shield-lock", "accounts:role_list", "roles.manage"),
        ("Settings", "gear", "core:settings_home", "settings.manage"),
        ("Audit Log", "journal-text", "core:audit_log", "audit.view"),
    ]),
]


def build_nav(user):
    profile = get_profile(user)
    if profile is None:
        return []
    codes = profile.capability_codes()
    sections = []
    for title, items in NAV_SECTIONS:
        visible = [{"label": label, "icon": icon, "url_name": url_name}
                   for label, icon, url_name, cap in items if cap in codes]
        if visible:
            sections.append({"title": title, "items": visible})
    return sections
