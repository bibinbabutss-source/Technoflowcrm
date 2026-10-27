"""
Lets modules plug into shared pages without depending on each other:

- customer_sections: related-record lists on the customer page (leads, visits, quotations...)
- search_providers: global search
- document_targets: record types documents can be attached to

Each app registers its entries in AppConfig.ready().
"""
customer_sections = []
search_providers = []
document_targets = {}


def register_customer_section(key, label, capability, getter, columns, *, order=50, add_url=None,
                              add_capability=None):
    """
    getter(customer, user) -> queryset of related records the user may see.
    add_url(customer) -> url to create a related record (optional).
    """
    customer_sections.append({
        "key": key, "label": label, "capability": capability, "getter": getter, "columns": columns,
        "order": order, "add_url": add_url, "add_capability": add_capability,
    })
    customer_sections.sort(key=lambda s: s["order"])


def register_search(label, capability, search_fn, *, order=50):
    """search_fn(user, q) -> list of (title, subtitle, url)."""
    search_providers.append({"label": label, "capability": capability, "fn": search_fn, "order": order})
    search_providers.sort(key=lambda s: s["order"])


def register_document_target(model, label, view_capability, owner_fields):
    document_targets[model._meta.label_lower] = {
        "model": model, "label": label, "capability": view_capability, "owner_fields": owner_fields,
    }
