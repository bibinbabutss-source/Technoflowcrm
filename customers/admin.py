from django.contrib import admin

from .models import Customer, CustomerContact


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("code", "company_name", "status", "assigned_engineer", "is_archived")
    search_fields = ("code", "company_name", "email")

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(CustomerContact)
