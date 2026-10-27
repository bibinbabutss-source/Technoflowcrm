from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "orders"
    verbose_name = "Sales orders"

    def ready(self):
        from django.db.models import Q

        from accounts.permissions import scope_queryset
        from core.audit import track_model
        from core.crud import Column, badge
        from core.registry import register_customer_section, register_document_target, register_search

        from .models import OWNER_FIELDS, SalesOrder

        track_model(SalesOrder)

        def customer_orders(customer, user):
            return scope_queryset(customer.orders.all(), user, OWNER_FIELDS)

        register_customer_section("orders", "Sales orders", "orders.view", customer_orders, [
            Column("Order", "number", link=True), Column("Date", "order_date", date=True),
            Column("Excl. VAT", "net_amount", money=True),
            Column("Status", render=lambda o: badge(o.get_status_display(), o.tone()))], order=45)

        def search(user, q):
            qs = scope_queryset(SalesOrder.objects.select_related("customer"), user, OWNER_FIELDS).filter(
                Q(number__icontains=q) | Q(customer_po_ref__icontains=q) | Q(customer__company_name__icontains=q))[:8]
            return [(o.number, f"{o.customer.company_name} · {o.get_status_display()} · "
                               f"{o.currency} {o.net_amount:,.2f} excl. VAT", o.get_absolute_url()) for o in qs]

        register_search("Sales orders", "orders.view", search, order=60)
        register_document_target(SalesOrder, "Sales order", "orders.view", OWNER_FIELDS)
