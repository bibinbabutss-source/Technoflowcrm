from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory
from django.utils import timezone

from core.crud import CrmFormMixin
from core.models import TaxRate
from quotations.forms import TaxRateSelect

from .models import Invoice, InvoiceLine, Payment


class InvoiceForm(CrmFormMixin, forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ["invoice_date", "due_date", "payment_terms", "reference", "notes"]

    def clean(self):
        data = super().clean()
        if data.get("invoice_date") and data.get("due_date") and data["due_date"] < data["invoice_date"]:
            self.add_error("due_date", "The due date cannot be before the invoice date.")
        return data


class InvoiceLineForm(forms.ModelForm):
    class Meta:
        model = InvoiceLine
        fields = ["description", "quantity", "unit", "unit_price", "discount_pct", "tax_rate"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2, "class": "form-control form-control-sm"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.001"}),
            "unit": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "discount_pct": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "tax_rate": TaxRateSelect(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.tax_rate_id if self.instance.pk else None
        self.fields["tax_rate"].queryset = TaxRate.objects.filter(Q(is_active=True) | Q(pk=current or 0))
        self.fields["tax_rate"].empty_label = None
        if not self.instance.pk and TaxRate.default():
            self.fields["tax_rate"].initial = TaxRate.default().pk


class BaseInvoiceLineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if not [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get("DELETE")]:
            raise forms.ValidationError("An invoice needs at least one line.")


InvoiceLineFormSet = inlineformset_factory(Invoice, InvoiceLine, form=InvoiceLineForm,
                                           formset=BaseInvoiceLineFormSet, extra=0, can_delete=True)


class ReasonForm(CrmFormMixin, forms.Form):
    reason = forms.CharField(max_length=255)


class DisputeForm(CrmFormMixin, forms.Form):
    is_disputed = forms.BooleanField(required=False, label="The customer disputes this invoice")
    dispute_note = forms.CharField(max_length=255, required=False, label="Details")


class PaymentForm(CrmFormMixin, forms.ModelForm):
    class Meta:
        model = Payment
        fields = ["payment_date", "amount", "method", "reference", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_date"].initial = timezone.localdate()
        self.fields["amount"].widget.attrs["min"] = "0.01"

    def clean_amount(self):
        value = self.cleaned_data["amount"]
        if value is None or value <= 0:
            raise forms.ValidationError("Enter the amount received (greater than zero).")
        return value

    def clean_payment_date(self):
        value = self.cleaned_data["payment_date"]
        if value > timezone.localdate():
            raise forms.ValidationError("The payment date cannot be in the future.")
        return value


class AllocateForm(CrmFormMixin, forms.Form):
    invoice = forms.ModelChoiceField(queryset=Invoice.objects.none())
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01)

    def __init__(self, *args, invoices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["invoice"].queryset = invoices if invoices is not None else Invoice.objects.none()
        self.fields["invoice"].label_from_instance = lambda i: f"{i.display_number} — outstanding {i.outstanding:,.2f}"


class StatementForm(CrmFormMixin, forms.Form):
    start = forms.DateField(label="From")
    end = forms.DateField(label="To")

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["end"] < data["start"]:
            self.add_error("end", "The end date cannot be before the start date.")
        return data
