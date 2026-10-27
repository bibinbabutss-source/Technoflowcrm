from django.apps import AppConfig


class QuotationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "quotations"
    verbose_name = "Quotations and proposals"

    def ready(self):
        from django.db.models import Q
        from django.urls import reverse

        from accounts.permissions import scope_queryset
        from core.audit import track_model
        from core.crud import Column, badge
        from core.registry import register_customer_section, register_document_target, register_search

        from .models import OWNER_FIELDS, Quotation, QuotationRevision

        track_model(Quotation, exclude=["status", "grand_total", "quotation_date", "expiry_date"])
        track_model(QuotationRevision)

        def customer_quotes(customer, user):
            return scope_queryset(customer.quotations.select_related("salesperson"), user, OWNER_FIELDS)

        register_customer_section("quotations", "Quotations", "quotations.view", customer_quotes, [
            Column("Number", lambda q: q.display_number, link=True), Column("Date", "quotation_date", date=True),
            Column("Grand total", "grand_total", money=True),
            Column("Status", render=lambda q: badge(QuotationRevision.Status(q.status).label, "info"))],
            order=40, add_url=lambda c: reverse("quotations:create") + f"?customer={c.pk}",
            add_capability="quotations.edit")

        def search(user, q):
            qs = scope_queryset(Quotation.objects.select_related("customer"), user, OWNER_FIELDS).filter(
                Q(number__icontains=q) | Q(customer__company_name__icontains=q))[:8]
            return [(x.display_number, f"{x.customer.company_name} · {x.currency} {x.grand_total:,.2f} · "
                                       f"{QuotationRevision.Status(x.status).label}", x.get_absolute_url()) for x in qs]

        register_search("Quotations", "quotations.view", search, order=50)
        register_document_target(Quotation, "Quotation", "quotations.view", OWNER_FIELDS)
