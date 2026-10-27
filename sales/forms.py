from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from core.crud import CrmFormMixin, EmployeeChoiceField, active_employees, restrict_lookups
from core.models import LookupValue
from core.related import apply_related_fields
from core.scopes import owners
from customers.forms import setup_assignment

from .models import Opportunity, OpportunityStage, Project

User = get_user_model()


class OpportunityForm(CrmFormMixin, forms.ModelForm):
    prefill_fields = ("customer", "lead")

    fieldsets = [
        ("Opportunity", ["title", "customer", "lead", "source", "project_type", "location", "products_services",
                         "competitors"]),
        ("Value and forecast", ["estimated_value", "probability", "expected_close_date"]),
        ("Ownership and next step", ["assigned_engineer", "assigned_coordinator", "next_action", "next_follow_up",
                                     "notes"]),
    ]

    class Meta:
        model = Opportunity
        fields = ["title", "customer", "lead", "source", "project_type", "location", "products_services",
                  "competitors", "estimated_value", "probability", "expected_close_date", "assigned_engineer",
                  "assigned_coordinator", "next_action", "next_follow_up", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_related_fields(self, {
            "customer": ("customers.Customer", "customers.view", owners("customers.customer"), Q(is_archived=False)),
            "lead": ("leads.Lead", "leads.view", owners("leads.lead")),
        })
        restrict_lookups(self, {"source": "lead_source", "project_type": "project_type"})
        setup_assignment(self)
        if not self.instance.pk:
            first = OpportunityStage.first_open()
            self.fields["probability"].initial = first.default_probability if first else 10
            self.fields["probability"].help_text = "Defaults to the stage's probability; you may adjust it."
        else:
            self.fields["probability"].help_text = "Won = 100%, Lost = 0% automatically."

    def clean(self):
        data = super().clean()
        lead, customer = data.get("lead"), data.get("customer")
        if lead and customer and lead.customer_id and lead.customer_id != customer.pk:
            self.add_error("lead", "This lead was converted for a different customer.")
        if self.instance.pk and self.instance.stage.is_closed and "probability" in self.changed_data:
            self.add_error("probability", "Probability is fixed for won or lost opportunities.")
        return data


class OpportunityStageForm(CrmFormMixin, forms.Form):
    stage = forms.ModelChoiceField(queryset=OpportunityStage.objects.filter(is_active=True))
    probability = forms.IntegerField(min_value=0, max_value=100, required=False,
                                     help_text="Leave empty to use the stage's default probability.")
    lost_reason = forms.ModelChoiceField(queryset=LookupValue.objects.filter(category="lost_reason", is_active=True),
                                         required=False)
    lost_notes = forms.CharField(max_length=255, required=False, label="Lost details / competitor")
    note = forms.CharField(max_length=255, required=False, label="Comment")

    def clean(self):
        data = super().clean()
        if data.get("stage") and data["stage"].is_lost and not data.get("lost_reason"):
            self.add_error("lost_reason", "Choose why the opportunity was lost.")
        return data


class ProjectForm(CrmFormMixin, forms.ModelForm):
    prefill_fields = ("customer", "opportunity", "sales_order")
    project_manager = EmployeeChoiceField(queryset=User.objects.none(), required=False)

    fieldsets = [
        ("Project", ["name", "customer", "opportunity", "sales_order", "project_type", "location", "description"]),
        ("Delivery", ["project_manager", "status", "progress", "start_date", "end_date"]),
    ]

    class Meta:
        model = Project
        fields = ["name", "customer", "opportunity", "sales_order", "project_type", "location", "description",
                  "project_manager", "status", "progress", "start_date", "end_date"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        apply_related_fields(self, {
            "customer": ("customers.Customer", "customers.view", owners("customers.customer")),
            "opportunity": ("sales.Opportunity", "pipeline.view", owners("sales.opportunity")),
            "sales_order": ("orders.SalesOrder", "orders.view", owners("orders.salesorder"),
                            Q(status__in=["confirmed", "in_progress", "partially_completed", "completed"])),
        })
        restrict_lookups(self, {"project_type": "project_type"})
        qs = active_employees()
        if self.instance.project_manager_id:
            qs = (qs | User.objects.filter(pk=self.instance.project_manager_id)).distinct()
        self.fields["project_manager"].queryset = qs
        self.fields["sales_order"].help_text = "Only confirmed orders can be linked: a project is delivery work."

    def clean(self):
        data = super().clean()
        if data.get("start_date") and data.get("end_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", "Completion cannot be before the start date.")
        customer = data.get("customer")
        for name in ("opportunity", "sales_order"):
            rec = data.get(name)
            if rec is not None and customer is not None and rec.customer_id != customer.pk:
                self.add_error(name, "This belongs to another customer.")
        return data
