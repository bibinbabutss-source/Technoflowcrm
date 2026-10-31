from django import forms

from accounts.permissions import has_capability, scope_queryset
from core.crud import CrmFormMixin, restrict_lookups
from core.forms import PillRadioSelect
from core.models import LookupValue
from customers.forms import setup_assignment
from customers.models import OWNER_FIELDS as CUSTOMER_OWNERS
from customers.models import Customer

from django.db import transaction
from django.db.models import Q

from customers.services import find_duplicates as find_customer_duplicates

from .models import Lead, LeadStage
from .services import find_lead_duplicates


class LeadForm(CrmFormMixin, forms.ModelForm):
    """
    Every lead belongs to a customer: the user picks an existing customer or adds a new one here,
    using the company and contact details below. The customer is created together with the lead.
    """
    CUSTOMER_MODES = [("existing", "Existing customer"), ("new", "New customer (use the company details below)")]
    customer_mode = forms.ChoiceField(choices=CUSTOMER_MODES, widget=forms.RadioSelect, initial="existing",
                                      label="Customer")
    confirm_new_customer = forms.BooleanField(
        required=False, label="This is a different company — create a new customer anyway",
        help_text="Tick only after checking the similar customers listed above.")
    confirm_duplicates = forms.BooleanField(
        required=False, label="This is a different enquiry — save anyway",
        help_text="Tick only after checking the similar open leads listed above.")
    prefill_fields = ("customer",)

    fieldsets = [
        ("1. Customer", ["customer_mode", "customer", "confirm_new_customer"]),
        ("Lead", ["category", "title", "interest", "estimated_value", "priority", "source"]),
        ("Company and contact", ["company_name", "contact_person", "designation", "email", "phone", "city"]),
        ("Assignment and follow-up", ["assigned_engineer", "assigned_coordinator", "last_contact_date",
                                      "next_follow_up", "qualification_notes"]),
        ("Duplicate check", ["confirm_duplicates"]),
    ]

    class Meta:
        model = Lead
        fields = ["customer", "category", "title", "interest", "estimated_value", "priority", "source", "company_name",
                  "contact_person", "designation", "email", "phone", "city", "assigned_engineer",
                  "assigned_coordinator", "last_contact_date", "next_follow_up", "qualification_notes"]

        widgets = {"category": PillRadioSelect(attrs={"class": "tf-category-choice"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicates = []
        self.customer_duplicates = []
        self.created_customer = None
        restrict_lookups(self, {"source": "lead_source"})
        setup_assignment(self, capability="leads.assign")
        cat = self.fields["category"]
        cat.required = True
        cat.choices = Lead.Category.choices  # no empty option: one of the three must be chosen
        cat.error_messages["required"] = "Choose the lead category: Job in Hand, Tender or Purchase Enquiry."
        if self.instance.pk and not has_capability(self.user, "leads.edit"):
            cat.disabled = True
        self.fields["estimated_value"].required = False
        if "assigned_engineer" in self.fields:
            self.fields["assigned_engineer"].label = "Responsible employee (owner)"
            if self.fields["assigned_engineer"].required is False and has_capability(self.user, "leads.assign"):
                self.fields["assigned_engineer"].required = True
        self._setup_customer()

    # ---- customer first
    @property
    def customer_locked(self):
        """Once the lead is in the sales pipeline or has meetings, its customer can no longer change."""
        lead = self.instance
        if not (lead.pk and lead.customer_id):
            return False
        return bool(lead.converted_at or lead.meetings.exists() or lead.opportunities.exists())

    def _setup_customer(self):
        field = self.fields["customer"]
        qs = scope_queryset(Customer.objects.filter(is_archived=False), self.user, CUSTOMER_OWNERS)
        if self.instance.customer_id:
            qs = Customer.objects.filter(Q(pk__in=qs.values("pk")) | Q(pk=self.instance.customer_id))
        field.queryset = qs.order_by("company_name")
        field.required = False
        field.label = "Existing customer"
        field.empty_label = "Choose the customer…"
        field.help_text = "Type to search. Not in the list? Choose 'New customer' above."
        self.fields["company_name"].required = False
        self.fields["company_name"].help_text = "Filled from the customer when you choose an existing one."
        if self.customer_locked:
            field.disabled = True
            field.help_text = "The customer cannot change once the lead has meetings or is in the sales pipeline."
            del self.fields["customer_mode"]
            del self.fields["confirm_new_customer"]
            return
        if self.instance.pk and not self.instance.customer_id:
            self.fields["customer_mode"].initial = "new"
        if not self.is_bound and self.initial.get("customer"):
            self.fields["customer_mode"].initial = "existing"

    def clean_customer(self):
        if self.customer_locked:
            return self.instance.customer
        return self.cleaned_data.get("customer")

    def clean_estimated_value(self):
        value = self.cleaned_data.get("estimated_value")
        return value if value is not None else 0

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        if not data.get("assigned_engineer") and self.user is not None and not \
                has_capability(self.user, "leads.assign"):
            # every lead has a responsible employee: someone who may not assign others owns what they register
            if self.instance.pk and self.instance.assigned_engineer_id:
                data["assigned_engineer"] = self.instance.assigned_engineer
            else:
                data["assigned_engineer"] = self.user
        self._clean_customer(data)
        if self.errors:
            return data
        if not self.instance.pk or {"company_name", "email", "phone", "customer"} & set(self.changed_data):
            self.duplicates = find_lead_duplicates(company_name=data.get("company_name"), email=data.get("email"),
                                                   phone=data.get("phone"), exclude_pk=self.instance.pk)
        if self.duplicates and not data.get("confirm_duplicates"):
            raise forms.ValidationError("Similar open leads already exist. Check the list below; if this is a "
                                        "different enquiry, tick 'save anyway'.")
        return data

    def _clean_customer(self, data):
        mode = "existing" if self.customer_locked else data.get("customer_mode") or "existing"
        if mode == "existing":
            customer = data.get("customer")
            if not customer:
                self.add_error("customer", "Choose the customer, or choose 'New customer' and enter the company "
                                           "details.")
                return
            # the lead carries the customer's company name; empty contact details are taken from the customer
            data["company_name"] = customer.company_name
            for name in ("contact_person", "designation", "email", "phone", "city"):
                if not data.get(name) and getattr(customer, name, ""):
                    data[name] = getattr(customer, name)
            return
        data["customer"] = None
        name = (data.get("company_name") or "").strip()
        if not name:
            self.add_error("company_name", "Enter the company name of the new customer.")
            return
        data["company_name"] = name
        self.customer_duplicates = find_customer_duplicates(company_name=name, email=data.get("email"),
                                                            phone=data.get("phone"))
        if self.customer_duplicates and not data.get("confirm_new_customer"):
            self.add_error(None, "Similar customers already exist. Choose one of them as the existing customer, "
                                 "or tick the box to confirm this is a different company.")

    def save(self, commit=True):
        with transaction.atomic():
            if not self.cleaned_data.get("customer") and not self.customer_locked:
                d = self.cleaned_data
                customer = Customer(company_name=d["company_name"], contact_person=d.get("contact_person") or "",
                                    designation=d.get("designation") or "", email=d.get("email") or "",
                                    phone=d.get("phone") or "", city=d.get("city") or "", source=d.get("source"),
                                    assigned_engineer=d.get("assigned_engineer"),
                                    assigned_coordinator=d.get("assigned_coordinator"),
                                    status=Customer.Status.PROSPECT)
                customer.save()
                self.created_customer = customer
                self.instance.customer = customer
            return super().save(commit=commit)


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
        self.fixed_customer = lead.customer if lead is not None and lead.customer_id else None
        if not has_capability(self.user, "pipeline.edit"):
            for f in ("create_opportunity", "opp_title", "opp_value", "opp_close", "opp_probability"):
                del self.fields[f]
        if self.fixed_customer:
            # customer-first leads already have their customer: only the opportunity is asked for
            for f in ("mode", "existing_customer", "company_name", "category", "contact_person", "email", "phone",
                      "city", "confirm_new"):
                del self.fields[f]
            if "create_opportunity" in self.fields:
                del self.fields["create_opportunity"]
                self.fields["opp_title"].required = True
            return
        self.fields["existing_customer"].queryset = scope_queryset(
            Customer.objects.filter(is_archived=False), self.user, CUSTOMER_OWNERS).order_by("company_name")
        if self.duplicates:
            self.fields["mode"].initial = "existing"
            self.fields["existing_customer"].initial = self.duplicates[0]["customer"].pk

    def clean(self):
        data = super().clean()
        if self.fixed_customer:
            data["mode"] = "existing"
            data["existing_customer"] = self.fixed_customer
            data["create_opportunity"] = "opp_title" in self.fields
        elif data.get("mode") == "existing":
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
