from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from accounts.permissions import has_capability
from core.crud import CrmFormMixin, EmployeeChoiceField, active_employees
from core.related import apply_related_fields
from core.scopes import owners
from customers.models import CustomerContact

from .models import Communication

User = get_user_model()

RELATED = {
    "customer": ("customers.Customer", "customers.view", owners("customers.customer"), Q(is_archived=False)),
    "lead": ("leads.Lead", "leads.view", owners("leads.lead")),
    "opportunity": ("sales.Opportunity", "pipeline.view", owners("sales.opportunity")),
}


class CommunicationForm(CrmFormMixin, forms.ModelForm):
    prefill_fields = ("customer", "lead", "opportunity", "kind")
    employee = EmployeeChoiceField(queryset=User.objects.none(), label="Employee")
    create_task = forms.BooleanField(required=False, label="Create a follow-up task on the follow-up date")

    fieldsets = [
        ("Interaction", ["customer", "contact", "kind", "direction", "occurred_at", "employee", "subject",
                         "summary"]),
        ("Outcome and next step", ["outcome", "next_action", "follow_up_date", "create_task"]),
        ("Related to", ["lead", "opportunity"]),
    ]

    class Meta:
        model = Communication
        fields = ["customer", "contact", "kind", "direction", "occurred_at", "employee", "subject", "summary",
                  "outcome", "next_action", "follow_up_date", "lead", "opportunity"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_related_fields(self, RELATED)
        if self.user is not None and has_capability(self.user, "records.assign"):
            self.fields["employee"].queryset = active_employees()
        else:
            ids = {self.user.pk} if self.user else set()
            if self.instance.employee_id:
                ids.add(self.instance.employee_id)
            self.fields["employee"].queryset = User.objects.filter(pk__in=ids)
        if not self.instance.pk:
            self.fields["employee"].initial = self.user.pk if self.user else None
            self.fields["occurred_at"].initial = timezone.localtime().replace(second=0, microsecond=0)
        customer_id = self.data.get("customer") or self.initial.get("customer") or self.instance.customer_id
        try:
            customer_id = int(customer_id)
        except (TypeError, ValueError):
            customer_id = None
        self.fields["contact"].queryset = CustomerContact.objects.filter(customer_id=customer_id)
        self.fields["contact"].help_text = "Contacts of the selected customer (save once to load a new list)."

    def clean(self):
        data = super().clean()
        customer = data.get("customer")
        for name in ("lead", "opportunity"):
            rec = data.get(name)
            if rec is not None and customer is not None and rec.customer_id not in (None, customer.pk):
                self.add_error(name, f"This {name} belongs to another customer.")
        if data.get("contact") and customer and data["contact"].customer_id != customer.pk:
            self.add_error("contact", "This contact belongs to another customer.")
        if data.get("create_task") and not data.get("follow_up_date"):
            self.add_error("follow_up_date", "Enter the follow-up date for the task.")
        if data.get("occurred_at") and data["occurred_at"] > timezone.now() + timezone.timedelta(days=1):
            self.add_error("occurred_at", "A logged communication cannot be in the future.")
        return data
