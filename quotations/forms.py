from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.forms import inlineformset_factory

from accounts import capabilities as caps
from accounts.permissions import has_capability
from core.crud import CrmFormMixin, EmployeeChoiceField, active_employees
from core.models import TaxRate
from core.related import apply_related_fields
from core.scopes import owners

from .models import Quotation, QuotationLine, QuotationRevision

User = get_user_model()


class TaxRateSelect(forms.Select):
    """Adds data-rate to each option so the page can preview totals while typing."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        rate = getattr(getattr(value, "instance", None), "rate", None)
        if rate is not None:
            option["attrs"]["data-rate"] = str(rate)
        return option


class QuotationForm(CrmFormMixin, forms.ModelForm):
    prefill_fields = ("customer", "opportunity")
    salesperson = EmployeeChoiceField(queryset=User.objects.none())

    class Meta:
        model = Quotation
        fields = ["customer", "opportunity", "salesperson", "currency"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_related_fields(self, {
            "customer": ("customers.Customer", "customers.view", owners("customers.customer"), Q(is_archived=False)),
            "opportunity": ("sales.Opportunity", "pipeline.view", owners("sales.opportunity"),
                            Q(is_archived=False, stage__is_won=False, stage__is_lost=False)),
        })
        if self.user is not None and has_capability(self.user, "records.assign"):
            qs = active_employees([caps.ENGINEER, caps.DIRECTOR, caps.ADMIN, caps.COORDINATOR])
        else:
            qs = User.objects.filter(pk=self.user.pk) if self.user else User.objects.none()
        if self.instance.pk and self.instance.salesperson_id:
            qs = (qs | User.objects.filter(pk=self.instance.salesperson_id)).distinct()
        self.fields["salesperson"].queryset = qs
        if not self.instance.pk and self.user is not None:
            self.fields["salesperson"].initial = self.user.pk
        self.fields["currency"].widget.attrs["maxlength"] = 3

    def clean_currency(self):
        value = (self.cleaned_data.get("currency") or "").upper()
        if len(value) != 3 or not value.isalpha():
            raise forms.ValidationError("Use a 3-letter currency code, e.g. AED.")
        return value

    def clean(self):
        data = super().clean()
        opp, customer = data.get("opportunity"), data.get("customer")
        if opp and customer and opp.customer_id != customer.pk:
            self.add_error("opportunity", "This opportunity belongs to another customer.")
        return data


class RevisionForm(CrmFormMixin, forms.ModelForm):
    fieldsets = [
        ("Dates", ["quotation_date", "expiry_date", "validity"]),
        ("Terms", ["payment_terms", "delivery_terms", "warranty_terms"]),
        ("Scope", ["scope_of_work", "exclusions"]),
        ("Notes", ["customer_notes", "internal_remarks", "header_discount"]),
    ]

    class Meta:
        model = QuotationRevision
        fields = ["quotation_date", "expiry_date", "validity", "payment_terms", "delivery_terms", "warranty_terms",
                  "scope_of_work", "exclusions", "customer_notes", "internal_remarks", "header_discount"]

    def clean(self):
        data = super().clean()
        if data.get("quotation_date") and data.get("expiry_date") and data["expiry_date"] < data["quotation_date"]:
            self.add_error("expiry_date", "The expiry date cannot be before the quotation date.")
        return data


class LineForm(forms.ModelForm):
    class Meta:
        model = QuotationLine
        fields = ["description", "quantity", "unit", "unit_price", "discount_pct", "tax_rate"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2, "class": "form-control form-control-sm"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.001",
                                                 "min": "0.001"}),
            "unit": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01",
                                                   "min": "0"}),
            "discount_pct": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01",
                                                     "min": "0", "max": "100"}),
            "tax_rate": TaxRateSelect(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.tax_rate_id if self.instance.pk else None
        qs = TaxRate.objects.filter(Q(is_active=True) | Q(pk=current)) if current else TaxRate.objects.filter(
            is_active=True)
        self.fields["tax_rate"].queryset = qs
        self.fields["tax_rate"].empty_label = None
        default = TaxRate.default()
        if not self.instance.pk and default:
            self.fields["tax_rate"].initial = default.pk


class BaseLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        active = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]
        if not active:
            raise forms.ValidationError("Add at least one line.")


LineFormSet = inlineformset_factory(QuotationRevision, QuotationLine, form=LineForm, formset=BaseLineFormSet,
                                    extra=0, can_delete=True, min_num=1, validate_min=False)


class DecisionForm(forms.Form):
    comments = forms.CharField(widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}), required=False,
                               label="Comments")


class AcceptanceForm(CrmFormMixin, forms.Form):
    date = forms.DateField(label="Acceptance date")
    accepted_by_name = forms.CharField(max_length=150, label="Accepted by (customer contact)")
    customer_reference = forms.CharField(max_length=100, required=False, label="Customer PO / reference")


class DeclineForm(CrmFormMixin, forms.Form):
    date = forms.DateField(label="Date")
    reason = forms.CharField(max_length=255, label="Reason given by the customer")


class ReviseForm(CrmFormMixin, forms.Form):
    reason = forms.CharField(max_length=255, required=False, label="Reason for the revision")
