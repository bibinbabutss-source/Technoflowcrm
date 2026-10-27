from django import forms

from .models import TaxRate, CompanyProfile, LookupValue, NumberSequence


class BootstrapMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.CheckboxSelectMultiple):
                pass
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class CompanyProfileForm(BootstrapMixin, forms.ModelForm):
    website = forms.URLField(required=False, assume_scheme="https")

    class Meta:
        model = CompanyProfile
        fields = [
            "company_name", "legal_name", "tax_registration_number", "address", "city", "country",
            "phone", "email", "website", "default_currency", "fiscal_year_start_month",
            "quotation_validity_days", "default_payment_terms_days", "max_upload_mb",
            "allowed_upload_extensions",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 3})}

    def clean_default_currency(self):
        value = self.cleaned_data["default_currency"].upper()
        if len(value) != 3 or not value.isalpha():
            raise forms.ValidationError("Use a 3-letter ISO currency code, e.g. AED.")
        return value

    def clean_allowed_upload_extensions(self):
        value = self.cleaned_data["allowed_upload_extensions"]
        blocked = {"exe", "bat", "cmd", "sh", "js", "msi", "ps1", "php", "py", "html", "htm", "svg", "jar", "dll"}
        exts = [e.strip().lower().lstrip(".") for e in value.split(",") if e.strip()]
        bad = sorted(set(exts) & blocked)
        if bad:
            raise forms.ValidationError(f"These file types are not allowed for security reasons: {', '.join(bad)}")
        return ",".join(exts)


class NumberSequenceForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = NumberSequence
        fields = ["prefix", "include_year", "reset_yearly", "padding"]

    def clean(self):
        data = super().clean()
        if data.get("reset_yearly") and not data.get("include_year"):
            raise forms.ValidationError(
                "Numbers can only restart each year when the year is part of the number; "
                "otherwise the same number would be issued again next year.")
        return data

    def clean_prefix(self):
        value = self.cleaned_data["prefix"].upper().strip()
        if not value.replace("-", "").isalnum():
            raise forms.ValidationError("Use letters and numbers only.")
        return value


class LookupValueForm(BootstrapMixin, forms.ModelForm):
    sort_order = forms.IntegerField(min_value=0, max_value=999, required=False)

    def clean_value(self):
        value = " ".join(self.cleaned_data["value"].split())
        if not value:
            raise forms.ValidationError("Enter a value.")
        return value

    def clean_sort_order(self):
        return self.cleaned_data.get("sort_order") or 0

    class Meta:
        model = LookupValue
        fields = ["category", "value", "sort_order", "is_active"]


class WorkflowSettingsForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CompanyProfile
        fields = ["approval_threshold", "discount_approval_limit", "quotation_expiry_warning_days",
                  "email_notifications_enabled", "visit_reminder_days", "task_reminder_days",
                  "overdue_reminder_days", "rating_excellent", "rating_good", "rating_satisfactory"]

    def clean_overdue_reminder_days(self):
        value = self.cleaned_data["overdue_reminder_days"]
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not parts or not all(p.isdigit() for p in parts):
            raise forms.ValidationError("Use whole numbers separated by commas, e.g. 1,7,30.")
        return ",".join(str(n) for n in sorted({int(p) for p in parts}))


class TaxRateForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = TaxRate
        fields = ["name", "rate", "is_default", "is_active", "sort_order"]

    def clean(self):
        data = super().clean()
        if data.get("is_default") and not data.get("is_active"):
            self.add_error("is_active", "The default rate must be active.")
        return data
