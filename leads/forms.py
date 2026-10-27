from django import forms

from accounts.permissions import has_capability, scope_queryset
from core.crud import CrmFormMixin, restrict_lookups
from core.models import LookupValue
from customers.forms import setup_assignment
from customers.models import OWNER_FIELDS as CUSTOMER_OWNERS
from customers.models import Customer

from .models import Lead, LeadStage
from .services import find_lead_duplicates


class LeadForm(CrmFormMixin, forms.ModelForm):
    confirm_duplicates = forms.BooleanField(
        required=False, label="This is a different enquiry — save anyway",
        help_text="Tick only after checking the similar open leads listed above.")

    fieldsets = [
        ("Lead", ["title", "interest", "estimated_value", "priority", "source"]),
        ("Company and contact", ["company_name", "contact_person", "designation", "email", "phone", "city"]),
        ("Assignment and follow-up", ["assigned_engineer", "assigned_coordinator", "last_contact_date",
                                      "next_follow_up", "qualification_notes"]),
        ("Duplicate check", ["confirm_duplicates"]),
    ]

    class Meta:
        model = Lead
        fields = ["title", "interest", "estimated_value", "priority", "source", "company_name", "contact_person",
                  "designation", "email", "phone", "city", "assigned_engineer", "assigned_coordinator",
                  "last_contact_date", "next_follow_up", "qualification_notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicates = []
        restrict_lookups(self, {"source": "lead_source"})
        setup_assignment(self, capability="leads.assign")

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        if not data.get("assigned_engineer") and not self.instance.pk and self.user is not None and not \
                has_capability(self.user, "leads.assign"):
            self.instance.assigned_engineer = self.user
        if not self.instance.pk or {"company_name", "email", "phone"} & set(self.changed_data):
            self.duplicates = find_lead_duplicates(company_name=data.get("company_name"), email=data.get("email"),
                                                   phone=data.get("phone"), exclude_pk=self.instance.pk)
        if self.duplicates and not data.get("confirm_duplicates"):
            raise forms.ValidationError("Similar open leads already exist. Check the list below; if this is a "
                                        "different enquiry, tick 'save anyway'.")
        return data


class StageForm(CrmFormMixin, forms.Form):
    stage = forms.ModelChoiceField(queryset=LeadStage.objects.filter(is_active=True))
    lost_reason = forms.ModelChoiceField(queryset=LookupValue.objects.filter(category="lost_reason", is_active=True),
                                         required=False, help_text="Required when the lead is lost.")
    lost_notes = forms.CharField(max_length=255, required=False, label="Lost details")
    note = forms.CharField(max_length=255, required=False, label="Comment")

    def clean(self):
        data = super().clean()
        stage = data.get("stage")
        if stage and stage.is_lost and not data.get("lost_reason"):
            self.add_error("lost_reason", "Choose why the lead was lost.")
        return data


class ConvertForm(CrmFormMixin, forms.Form):
    MODE_CHOICES = [("existing", "Link to an existing customer"), ("new", "Create a new customer")]
    mode = forms.ChoiceField(choices=MODE_CHOICES, widget=forms.RadioSelect, initial="new", label="Customer")
    existing_customer = forms.ModelChoiceField(queryset=Customer.objects.none(), required=False)
    company_name = forms.CharField(max_length=200, required=False)
    category = forms.ModelChoiceField(queryset=LookupValue.objects.filter(category="customer_category",
                                                                           is_active=True), required=False)
    contact_person = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=40, required=False)
    city = forms.CharField(max_length=100, required=False, label="Emirate / city")
    confirm_new = forms.BooleanField(required=False,
                                     label="I checked the similar customers above — create a new customer anyway")
    create_opportunity = forms.BooleanField(required=False, initial=True, label="Create a sales opportunity")
    opp_title = forms.CharField(max_length=200, required=False, label="Opportunity title")
    opp_value = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False,
                                   label="Estimated value")
    opp_close = forms.DateField(required=False, label="Expected closing date")
    opp_probability = forms.IntegerField(min_value=0, max_value=100, required=False, initial=25,
                                         label="Closing probability (%)")

    def __init__(self, *args, lead=None, duplicates=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.lead = lead
        self.duplicates = list(duplicates)
        self.fields["existing_customer"].queryset = scope_queryset(
            Customer.objects.filter(is_archived=False), self.user, CUSTOMER_OWNERS).order_by("company_name")
        if self.duplicates:
            self.fields["mode"].initial = "existing"
            self.fields["existing_customer"].initial = self.duplicates[0]["customer"].pk
        if not has_capability(self.user, "pipeline.edit"):
            for f in ("create_opportunity", "opp_title", "opp_value", "opp_close", "opp_probability"):
                del self.fields[f]

    def clean(self):
        data = super().clean()
        if data.get("mode") == "existing":
            if not data.get("existing_customer"):
                self.add_error("existing_customer", "Choose the customer.")
        else:
            if not (data.get("company_name") or "").strip():
                self.add_error("company_name", "Enter the company name.")
            definite = [d for d in self.duplicates if d["definite"]]
            if definite:
                raise forms.ValidationError(f"A customer with the same TRN exists: {definite[0]['customer']}.")
            if self.duplicates and not data.get("confirm_new"):
                raise forms.ValidationError("Similar customers already exist. Link to one of them, or tick the "
                                            "box to confirm this is a different company.")
        if data.get("create_opportunity"):
            if not (data.get("opp_title") or "").strip():
                self.add_error("opp_title", "Enter the opportunity title.")
            if data.get("opp_probability") is None:
                self.add_error("opp_probability", "Enter the closing probability.")
        return data
