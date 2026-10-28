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

from .models import Quotation, QuotationLine, QuotationRevision, QuotationTemplate, QuotationTerm

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
        ("Quotation details", ["quotation_date", "expiry_date", "header_discount", "payment_terms"]),
        ("Cover letter", ["customer_name", "attention", "customer_address", "subject", "project_name", "consultant",
                          "letter_body", "letter_closing", "signatory_name", "signatory_designation"]),
        ("Price schedule", ["manufacturer", "schedule_note", "sales_engineer_name", "sales_in_charge_name",
                            "approved_by_name"]),
        ("Scope and notes", ["scope_of_work", "exclusions", "customer_notes", "internal_remarks"]),
    ]

    class Meta:
        model = QuotationRevision
        fields = ["quotation_date", "expiry_date", "header_discount", "payment_terms",
                  "customer_name", "attention", "customer_address", "subject", "project_name", "consultant",
                  "letter_body", "letter_closing", "signatory_name", "signatory_designation",
                  "manufacturer", "schedule_note", "sales_engineer_name", "sales_in_charge_name", "approved_by_name",
                  "scope_of_work", "exclusions", "customer_notes", "internal_remarks"]
        widgets = {"customer_address": forms.Textarea(attrs={"rows": 3}),
                   "letter_body": forms.Textarea(attrs={"rows": 9}),
                   "letter_closing": forms.Textarea(attrs={"rows": 2}),
                   "payment_terms": forms.Textarea(attrs={"rows": 2}),
                   "scope_of_work": forms.Textarea(attrs={"rows": 3}),
                   "exclusions": forms.Textarea(attrs={"rows": 3}),
                   "customer_notes": forms.Textarea(attrs={"rows": 3}),
                   "internal_remarks": forms.Textarea(attrs={"rows": 3})}
        labels = {"payment_terms": "Payment terms (short — copied to the sales order)",
                  "scope_of_work": "Scope of work (printed in the terms table)",
                  "exclusions": "Exclusions (printed in the terms table)",
                  "customer_notes": "Notes to customer (printed in the terms table)",
                  "internal_remarks": "Internal remarks (never printed)"}

    def clean(self):
        data = super().clean()
        if data.get("quotation_date") and data.get("expiry_date") and data["expiry_date"] < data["quotation_date"]:
            self.add_error("expiry_date", "The expiry date cannot be before the quotation date.")
        return data


class LineForm(forms.ModelForm):
    class Meta:
        model = QuotationLine
        fields = ["part_no", "description", "quantity", "unit", "unit_price", "discount_pct", "tax_rate"]
        widgets = {
            "part_no": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
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


class TermForm(forms.ModelForm):
    def has_changed(self):
        # Rows pre-filled from the template count as entered, even when the user did not touch them.
        if self.is_bound and (self.data.get(self.add_prefix("heading"), "").strip()
                              or self.data.get(self.add_prefix("content"), "").strip()):
            return True
        return super().has_changed()

    class Meta:
        model = QuotationTerm
        fields = ["heading", "content"]
        widgets = {"heading": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
                   "content": forms.Textarea(attrs={"rows": 3, "class": "form-control form-control-sm"})}


TermFormSet = inlineformset_factory(QuotationRevision, QuotationTerm, form=TermForm, extra=0, can_delete=True)


def term_formset(data, rev, initial_rows):
    """Terms formset; a revision without saved rows starts from initial_rows (template or older fields)."""
    if rev.pk and rev.terms.exists():
        return TermFormSet(data, instance=rev, prefix="terms")
    factory = inlineformset_factory(QuotationRevision, QuotationTerm, form=TermForm, can_delete=True,
                                    extra=len(initial_rows))
    return factory(data, instance=rev, prefix="terms",
                   initial=[{"heading": h, "content": c} for h, c in initial_rows])


class QuotationTemplateForm(CrmFormMixin, forms.ModelForm):
    fieldsets = [
        ("Letterhead", ["letterhead_tagline", "arabic_name"]),
        ("Cover letter defaults", ["letter_body", "letter_closing", "signatory_designation", "signature_label"]),
        ("Price schedule", ["schedule_note", "show_unit"]),
        ("Footer", ["footer_tagline", "footer_website", "footer_business_lines", "footer_contact"]),
    ]

    class Meta:
        model = QuotationTemplate
        fields = ["letterhead_tagline", "arabic_name", "letter_body", "letter_closing", "signatory_designation",
                  "signature_label", "schedule_note", "show_unit", "footer_tagline", "footer_website",
                  "footer_business_lines", "footer_contact"]
        widgets = {"letter_body": forms.Textarea(attrs={"rows": 9}), "letter_closing": forms.Textarea(attrs={"rows": 2})}


class DefaultTermForm(forms.Form):
    heading = forms.CharField(max_length=100, widget=forms.TextInput(attrs={"class": "form-control form-control-sm"}))
    content = forms.CharField(widget=forms.Textarea(attrs={"rows": 3, "class": "form-control form-control-sm"}))


DefaultTermFormSet = forms.formset_factory(DefaultTermForm, extra=0, can_delete=True)


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
