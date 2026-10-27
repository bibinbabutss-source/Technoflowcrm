from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory

from accounts.permissions import has_capability
from core.crud import CrmFormMixin, EmployeeChoiceField, active_employees

from .models import PaymentMilestone, SalesOrder
from .services import MILESTONE_PRESETS

User = get_user_model()


class CreateOrderForm(CrmFormMixin, forms.Form):
    order_date = forms.DateField()
    milestones = forms.ChoiceField(
        label="Payment milestones",
        choices=[("100", "100% on invoice"), ("50-50", "50% advance / 50% final"),
                 ("30-40-30", "30% advance / 40% progress / 30% final"), ("30-70", "30% advance / 70% on delivery")],
        help_text="You can adjust the milestones on the order before invoicing starts.")
    customer_po_ref = forms.CharField(max_length=100, required=False, label="Customer PO reference")
    delivery_details = forms.CharField(widget=forms.Textarea, required=False, label="Delivery / service details")
    notes = forms.CharField(widget=forms.Textarea, required=False)

    def clean_milestones(self):
        value = self.cleaned_data["milestones"]
        if value not in MILESTONE_PRESETS:
            raise forms.ValidationError("Choose a milestone plan.")
        return value


class OrderForm(CrmFormMixin, forms.ModelForm):
    assigned_to = EmployeeChoiceField(queryset=User.objects.none(), label="Assigned employee")

    class Meta:
        model = SalesOrder
        fields = ["customer_po_ref", "assigned_to", "delivery_details", "payment_terms", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.user is not None and has_capability(self.user, "records.assign"):
            qs = active_employees()
        else:
            qs = User.objects.filter(pk=self.instance.assigned_to_id)
        self.fields["assigned_to"].queryset = (qs | User.objects.filter(pk=self.instance.assigned_to_id)).distinct()


class MilestoneForm(forms.ModelForm):
    class Meta:
        model = PaymentMilestone
        fields = ["name", "percentage", "due_date"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "percentage": forms.NumberInput(attrs={"class": "form-control form-control-sm", "step": "0.01"}),
            "due_date": forms.DateInput(attrs={"class": "form-control form-control-sm", "type": "date"},
                                        format="%Y-%m-%d"),
        }


class BaseMilestoneFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        total = Decimal(0)
        count = 0
        for f in self.forms:
            if f.cleaned_data and not f.cleaned_data.get("DELETE"):
                total += f.cleaned_data.get("percentage") or 0
                count += 1
        if count == 0:
            raise forms.ValidationError("Add at least one milestone.")
        if total != Decimal(100):
            raise forms.ValidationError(f"Milestone percentages must add up to 100% (now {total}%).")


MilestoneFormSet = inlineformset_factory(SalesOrder, PaymentMilestone, form=MilestoneForm,
                                         formset=BaseMilestoneFormSet, extra=1, can_delete=True)


class CancelOrderForm(CrmFormMixin, forms.Form):
    reason = forms.CharField(max_length=255, label="Reason for cancelling")
