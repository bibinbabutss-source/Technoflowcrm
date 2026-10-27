from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from accounts.permissions import has_capability
from core.crud import CrmFormMixin, EmployeeChoiceField, active_employees, restrict_lookups
from core.related import apply_related_fields
from core.scopes import owners
from customers.models import CustomerContact

from .models import Visit

User = get_user_model()

RELATED = {
    "customer": ("customers.Customer", "customers.view", owners("customers.customer"), Q(is_archived=False)),
    "lead": ("leads.Lead", "leads.view", owners("leads.lead")),
    "opportunity": ("sales.Opportunity", "pipeline.view", owners("sales.opportunity")),
}


def _assignee_queryset(form, field):
    if form.user is not None and has_capability(form.user, "records.assign"):
        return active_employees()
    ids = {form.user.pk} if form.user else set()
    current = getattr(form.instance, f"{field}_id", None)
    if current:
        ids.add(current)
    return User.objects.filter(pk__in=ids)


class VisitForm(CrmFormMixin, forms.ModelForm):
    prefill_fields = ("customer", "lead", "opportunity")
    assigned_to = EmployeeChoiceField(queryset=User.objects.none(), label="Assigned employee")

    fieldsets = [
        ("Visit", ["customer", "contact", "contact_person", "site_name", "purpose", "priority", "agenda"]),
        ("When and where", ["visit_date", "start_time", "end_time", "location", "assigned_to", "status"]),
        ("Related to", ["opportunity", "lead"]),
    ]

    class Meta:
        model = Visit
        fields = ["customer", "contact", "contact_person", "site_name", "purpose", "priority", "agenda",
                  "visit_date", "start_time", "end_time", "location", "assigned_to", "status", "opportunity",
                  "lead"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_related_fields(self, RELATED)
        restrict_lookups(self, {"purpose": "visit_purpose"})
        self.fields["assigned_to"].queryset = _assignee_queryset(self, "assigned_to")
        # Completing a visit is a separate, deliberate action (never automatic)
        self.fields["status"].choices = [c for c in Visit.Status.choices
                                         if c[0] in ("scheduled", "confirmed")
                                         or c[0] == getattr(self.instance, "status", None)]
        if not self.instance.pk:
            self.fields["assigned_to"].initial = self.user.pk if self.user else None
        customer_id = self.data.get("customer") or self.initial.get("customer") or self.instance.customer_id
        try:
            customer_id = int(customer_id)
        except (TypeError, ValueError):
            customer_id = None
        self.fields["contact"].queryset = CustomerContact.objects.filter(customer_id=customer_id)

    def clean(self):
        data = super().clean()
        customer = data.get("customer")
        for name in ("lead", "opportunity"):
            rec = data.get(name)
            if rec is not None and customer is not None and rec.customer_id not in (None, customer.pk):
                self.add_error(name, f"This {name} belongs to another customer.")
        if not self.instance.pk and data.get("visit_date") and data["visit_date"] < timezone.localdate():
            self.add_error("visit_date", "A new visit cannot be scheduled in the past. "
                                         "To record a past meeting, use Log communication.")
        if data.get("contact") and not data.get("contact_person"):
            data["contact_person"] = data["contact"].name
            self.instance.contact_person = data["contact"].name
        return data


class CompleteForm(CrmFormMixin, forms.ModelForm):
    next_follow_up_owner = EmployeeChoiceField(queryset=User.objects.none(), required=False,
                                               label="Next follow-up owner")
    create_task = forms.BooleanField(required=False, initial=True,
                                     label="Create a follow-up task for the owner on the follow-up date")
    update_opportunity = forms.CharField(required=False, max_length=255, label="Next action on the opportunity",
                                         help_text="Saved on the linked opportunity, if any.")
    schedule_next = forms.BooleanField(required=False, label="Schedule the next visit now")

    fieldsets = [
        ("Meeting outcome", ["meeting_notes", "customer_requirements", "agreed_actions", "key_developments",
                             "potential_value"]),
        ("Follow-up", ["next_follow_up_date", "next_follow_up_owner", "create_task", "update_opportunity",
                       "schedule_next"]),
    ]

    class Meta:
        model = Visit
        fields = ["meeting_notes", "customer_requirements", "agreed_actions", "key_developments", "potential_value",
                  "next_follow_up_date", "next_follow_up_owner"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["meeting_notes"].required = True
        self.fields["next_follow_up_owner"].queryset = (
            _assignee_queryset(self, "next_follow_up_owner") | User.objects.filter(pk=self.instance.assigned_to_id)
        ).distinct()
        self.fields["next_follow_up_owner"].initial = self.instance.assigned_to_id
        if not self.instance.opportunity_id:
            del self.fields["update_opportunity"]

    def clean(self):
        data = super().clean()
        if data.get("create_task"):
            if not data.get("next_follow_up_date"):
                self.add_error("next_follow_up_date", "Enter the follow-up date for the task.")
            if not data.get("next_follow_up_owner"):
                self.add_error("next_follow_up_owner", "Choose who follows up.")
        return data


class RescheduleForm(CrmFormMixin, forms.Form):
    visit_date = forms.DateField(label="New date")
    start_time = forms.TimeField()
    end_time = forms.TimeField()
    reason = forms.CharField(max_length=255, required=False)

    def clean(self):
        data = super().clean()
        if data.get("visit_date") and data["visit_date"] < timezone.localdate():
            self.add_error("visit_date", "Choose today or a future date.")
        if data.get("start_time") and data.get("end_time") and data["end_time"] <= data["start_time"]:
            self.add_error("end_time", "The end time must be after the start time.")
        return data


class CancelForm(CrmFormMixin, forms.Form):
    reason = forms.CharField(max_length=255, label="Reason for cancelling")
