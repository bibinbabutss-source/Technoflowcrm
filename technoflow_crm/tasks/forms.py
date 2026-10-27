from django import forms
from django.db.models import Q

from accounts.permissions import has_capability
from core.crud import CrmFormMixin, EmployeeChoiceField, active_employees
from core.related import apply_related_fields
from core.scopes import owners
from django.contrib.auth import get_user_model

from .models import Task, TaskComment

User = get_user_model()

RELATED = {
    "customer": ("customers.Customer", "customers.view", owners("customers.customer"), Q(is_archived=False)),
    "lead": ("leads.Lead", "leads.view", owners("leads.lead"), Q(is_archived=False)),
    "opportunity": ("sales.Opportunity", "pipeline.view", owners("sales.opportunity"), Q(is_archived=False)),
    "quotation": ("quotations.Quotation", "quotations.view", owners("quotations.quotation")),
    "invoice": ("invoicing.Invoice", "invoices.view", owners("invoicing.invoice")),
    "visit": ("visits.Visit", "visits.view", owners("visits.visit")),
}


class TaskForm(CrmFormMixin, forms.ModelForm):
    prefill_fields = ("customer", "lead", "visit", "opportunity", "quotation", "invoice", "category", "title")
    assigned_to = EmployeeChoiceField(queryset=User.objects.none())

    fieldsets = [
        ("Task", ["title", "description", "category", "priority", "status"]),
        ("Schedule and owner", ["assigned_to", "start_date", "due_date"]),
        ("Related to", ["customer", "lead", "opportunity", "visit", "quotation", "invoice"]),
    ]

    class Meta:
        model = Task
        fields = ["title", "description", "category", "priority", "status", "assigned_to", "start_date", "due_date",
                  "customer", "lead", "opportunity", "visit", "quotation", "invoice"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_related_fields(self, RELATED)
        can_assign = self.user is not None and has_capability(self.user, "records.assign")
        if can_assign:
            qs = active_employees()
        else:
            ids = {self.user.pk} if self.user else set()
            if self.instance.assigned_to_id:
                ids.add(self.instance.assigned_to_id)
            qs = User.objects.filter(pk__in=ids)
        self.fields["assigned_to"].queryset = qs
        if not self.instance.pk:
            self.fields["assigned_to"].initial = self.user.pk if self.user else None
            self.fields["status"].initial = Task.Status.OPEN
        if not can_assign:
            self.fields["assigned_to"].help_text = "Only coordinators, directors and administrators assign tasks to others."


class CommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ["text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 2, "class": "form-control",
                                                 "placeholder": "Add a comment"})}
        labels = {"text": "Comment"}
