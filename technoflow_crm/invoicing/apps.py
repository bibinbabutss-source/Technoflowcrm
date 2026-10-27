from django.apps import AppConfig


class InvoicingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "invoicing"
    verbose_name = "Invoicing and collections"

    def ready(self):
        from django.db.models import Q

        from accounts.permissions import scope_queryset
        from core.audit import track_model
        from core.crud import Column, badge
        from core.registry import register_customer_section, register_document_target, register_search

        from .models import OWNER_FIELDS, Invoice, Payment

        track_model(Invoice, exclude=["amount_paid", "last_reminder_days"])
        track_model(Payment)

        def customer_invoices(customer, user):
            return scope_queryset(customer.invoices.all(), user, OWNER_FIELDS)

        register_customer_section("invoices", "Invoices", "invoices.view", customer_invoices, [
            Column("Invoice", "display_number", link=True), Column("Date", "invoice_date", date=True),
            Column("Total", "total", money=True), Column("Outstanding", "outstanding", money=True),
            Column("Status", render=lambda i: badge(i.display_status, i.tone()))], order=50)

        def search(user, q):
            qs = scope_queryset(Invoice.objects.select_related("customer"), user, OWNER_FIELDS).filter(
                Q(number__icontains=q) | Q(reference__icontains=q) | Q(customer__company_name__icontains=q))[:8]
            return [(i.display_number, f"{i.customer.company_name} · {i.currency} {i.total:,.2f} · {i.display_status}",
                     i.get_absolute_url()) for i in qs]

        register_search("Invoices", "invoices.view", search, order=70)
        register_document_target(Invoice, "Invoice", "invoices.view", OWNER_FIELDS)
