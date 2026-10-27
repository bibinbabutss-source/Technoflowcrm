from django.contrib import admin

from .models import AuditLog, CompanyProfile, LookupValue, NumberSequence


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("timestamp", "user", "action", "content_type", "object_repr", "ip_address")
    list_filter = ("action", "content_type")
    search_fields = ("object_repr", "message", "user__username")
    date_hierarchy = "timestamp"


@admin.register(CompanyProfile)
class CompanyProfileAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not CompanyProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NumberSequence)
class NumberSequenceAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "include_year", "reset_yearly", "padding", "last_number")
    readonly_fields = ("last_number", "current_year")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LookupValue)
class LookupValueAdmin(admin.ModelAdmin):
    list_display = ("category", "value", "sort_order", "is_active")
    list_filter = ("category", "is_active")
