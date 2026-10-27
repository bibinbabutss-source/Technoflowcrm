from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm
from django.contrib.auth.password_validation import password_validators_help_text_html

from core.forms import BootstrapMixin
from core.models import LookupValue

from .models import Capability, EmployeeProfile, Role

User = get_user_model()


class LoginForm(BootstrapMixin, AuthenticationForm):
    username = forms.CharField(label="Username", widget=forms.TextInput(attrs={"autofocus": True,
                                                                            "autocomplete": "username"}))
    password = forms.CharField(label="Password", strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not hasattr(user, "profile"):
            raise forms.ValidationError(
                "This account is not linked to an employee profile. Contact the System Administrator.",
                code="no_profile",
            )


class CrmPasswordChangeForm(BootstrapMixin, PasswordChangeForm):
    pass


class CrmSetPasswordForm(BootstrapMixin, SetPasswordForm):
    pass


def _department_choices(current=""):
    values = list(LookupValue.choices_for(LookupValue.Category.DEPARTMENT).values_list("value", flat=True))
    if current and current not in values:
        values.append(current)  # a value hidden later stays valid for employees who already have it
    return [("", "—")] + [(v, v) for v in values]


class EmployeeForm(BootstrapMixin, forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(label="Work email")
    employee_id = forms.CharField(label="Employee ID", max_length=20)
    role = forms.ModelChoiceField(queryset=Role.objects.all())
    department = forms.ChoiceField(required=False)
    job_title = forms.CharField(max_length=100, required=False)
    phone = forms.CharField(label="Contact number", max_length=40, required=False)
    reporting_manager = forms.ModelChoiceField(
        queryset=EmployeeProfile.objects.filter(user__is_active=True).select_related("user"), required=False
    )
    team_members = forms.ModelMultipleChoiceField(
        queryset=EmployeeProfile.objects.filter(user__is_active=True).select_related("user", "role"),
        required=False, widget=forms.SelectMultiple(attrs={"size": 5}),
        help_text="Sales Coordinators see and coordinate the records of these employees.",
    )

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and "initial" not in kwargs:
            u = instance.user
            kwargs["initial"] = {
                "first_name": u.first_name, "last_name": u.last_name, "email": u.email,
                "employee_id": instance.employee_id, "role": instance.role, "department": instance.department,
                "job_title": instance.job_title, "phone": instance.phone,
                "reporting_manager": instance.reporting_manager,
                "team_members": list(instance.team_members.all()),
            }
        super().__init__(*args, **kwargs)
        self.fields["department"].choices = _department_choices(instance.department if instance else "")
        if instance is not None:
            self.fields["reporting_manager"].queryset = self.fields["reporting_manager"].queryset.exclude(pk=instance.pk)
            self.fields["team_members"].queryset = self.fields["team_members"].queryset.exclude(pk=instance.pk)

    def clean_reporting_manager(self):
        manager = self.cleaned_data.get("reporting_manager")
        if manager and self.instance is not None:
            seen, current = set(), manager
            while current is not None and current.pk not in seen:
                if current.pk == self.instance.pk:
                    raise forms.ValidationError("This would create a reporting loop (the manager reports to this employee).")
                seen.add(current.pk)
                current = current.reporting_manager
        return manager

    def clean_employee_id(self):
        value = self.cleaned_data["employee_id"].strip().upper()
        qs = EmployeeProfile.objects.filter(employee_id__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This employee ID is already in use.")
        return value

    def clean_email(self):
        value = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("This work email is already in use.")
        return value


class NewEmployeeForm(EmployeeForm):
    username = forms.CharField(max_length=150, help_text="Used to sign in. Letters, digits and . _ - only.")
    temporary_password = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
        help_text="The employee must change it at first sign-in. " + password_validators_help_text_html(),
    )
    field_order = ["first_name", "last_name", "username", "email", "employee_id", "role", "department",
                   "job_title", "phone", "reporting_manager", "team_members", "temporary_password"]

    def clean_username(self):
        value = self.cleaned_data["username"].strip()
        if not all(c.isalnum() or c in "._-" for c in value):
            raise forms.ValidationError("Use letters, digits and . _ - only.")
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError("This username is already in use.")
        return value


class AdminResetPasswordForm(BootstrapMixin, forms.Form):
    temporary_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="The employee will be signed out everywhere and must change this password at next sign-in.",
    )


class RoleForm(BootstrapMixin, forms.ModelForm):
    capabilities = forms.ModelMultipleChoiceField(
        queryset=Capability.objects.all(), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Role
        fields = ["name", "description", "max_accounts", "data_scope", "capabilities"]

    def clean(self):
        data = super().clean()
        if self.instance.is_admin_role:
            required = {"users.manage", "roles.manage", "settings.manage"}
            chosen = {c.code for c in data.get("capabilities") or []}
            missing = required - chosen
            if missing:
                raise forms.ValidationError(
                    "The System Administrator role must keep user, role and settings management.")
        return data
