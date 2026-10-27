from django import forms

from accounts import capabilities as caps
from accounts.permissions import has_capability
from core.crud import CrmFormMixin, active_employees, limit_assignees, restrict_lookups

from .models import Customer, CustomerContact
from .services import find_duplicates

ENGINEER_ROLES = [caps.ENGINEER, caps.DIRECTOR, caps.ADMIN]
COORDINATOR_ROLES = [caps.COORDINATOR]


def setup_assignment(form, engineer_field="assigned_engineer", coordinator_field="assigned_coordinator",
                     capability="records.assign"):
    """
    Assignment drop-downs: users with the assign capability may pick anyone with the right role;
    others can only assign the engineer field to themselves (and pick a coordinator).
    """
    can_assign = form.user is not None and has_capability(form.user, capability)
    limit_assignees(form, [engineer_field], {engineer_field: ENGINEER_ROLES}, can_assign=can_assign)
    limit_assignees(form, [coordinator_field], {coordinator_field: COORDINATOR_ROLES}, can_assign=True)
    if form.user is not None and not form.instance.pk:
        role = getattr(getattr(form.user, "profile", None), "role", None)
        if role and role.code in ENGINEER_ROLES and engineer_field in form.fields:
            form.fields[engineer_field].initial = form.user.pk
        if role and role.code == caps.COORDINATOR and coordinator_field in form.fields:
            form.fields[coordinator_field].initial = form.user.pk
    if not can_assign and engineer_field in form.fields and not form.instance.pk:
        form.fields[engineer_field].required = False
        form.fields[engineer_field].help_text = "Assigned to you. A coordinator or director can reassign it."


class CustomerForm(CrmFormMixin, forms.ModelForm):
    confirm_duplicates = forms.BooleanField(
        required=False, label="These are different companies — save anyway",
        help_text="Tick only after checking the possible duplicates listed above.")

    fieldsets = [
        ("Company", ["company_name", "category", "industry", "status", "source", "website", "trn"]),
        ("Primary contact", ["contact_person", "designation", "phone", "alt_phone", "email"]),
        ("Address", ["billing_address", "office_address", "city", "country"]),
        ("Ownership and follow-up", ["assigned_engineer", "assigned_coordinator", "next_follow_up", "notes"]),
        ("Duplicate check", ["confirm_duplicates"]),
    ]

    class Meta:
        model = Customer
        fields = ["company_name", "category", "industry", "status", "source", "website", "trn",
                  "contact_person", "designation", "phone", "alt_phone", "email",
                  "billing_address", "office_address", "city", "country",
                  "assigned_engineer", "assigned_coordinator", "next_follow_up", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.duplicates = []
        restrict_lookups(self, {"category": "customer_category", "industry": "industry", "source": "lead_source"})
        setup_assignment(self)
        self.fields["website"].assume_scheme = "https"
        if self.user is not None and not has_capability(self.user, "customers.edit") and "notes" in self.fields:
            del self.fields["notes"]

    def clean_company_name(self):
        name = " ".join(self.cleaned_data["company_name"].split())
        if len(name) < 2:
            raise forms.ValidationError("Enter the company name.")
        return name

    def clean(self):
        data = super().clean()
        if self.errors:
            return data
        if not data.get("assigned_engineer") and self.user is not None and not has_capability(
                self.user, "records.assign") and not self.instance.pk:
            data["assigned_engineer"] = self.user
            self.instance.assigned_engineer = self.user
        self.duplicates = find_duplicates(
            company_name=data.get("company_name"), email=data.get("email"), phone=data.get("phone"),
            trn=data.get("trn"), exclude_pk=self.instance.pk)
        definite = [d for d in self.duplicates if d["definite"]]
        if definite:
            raise forms.ValidationError(
                f"A customer with this TRN already exists: {definite[0]['customer']}. Open that customer instead.")
        if self.duplicates and not data.get("confirm_duplicates"):
            raise forms.ValidationError(
                "Possible duplicate customer found. Check the list below; if this really is a different "
                "company, tick 'save anyway'.")
        return data


class CustomerContactForm(CrmFormMixin, forms.ModelForm):
    class Meta:
        model = CustomerContact
        fields = ["name", "designation", "phone", "email", "is_primary", "notes"]


__all__ = ["CustomerForm", "CustomerContactForm", "setup_assignment", "active_employees"]
