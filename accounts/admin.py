from django.contrib import admin

from core.admin import ReadOnlyAdmin

from .models import Capability, EmployeeProfile, LoginHistory, Role


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "max_accounts", "data_scope")
    filter_horizontal = ("capabilities",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Capability)
class CapabilityAdmin(ReadOnlyAdmin):
    list_display = ("code", "module", "label")


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ("employee_id", "full_name", "role", "department")
    list_filter = ("role",)
    search_fields = ("employee_id", "user__first_name", "user__last_name", "user__email")

    def has_delete_permission(self, request, obj=None):
        return False  # deactivate instead; history is kept


@admin.register(LoginHistory)
class LoginHistoryAdmin(ReadOnlyAdmin):
    list_display = ("timestamp", "username", "event", "ip_address")
    list_filter = ("event",)
