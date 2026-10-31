from django import forms
from django.utils import timezone

from accounts.permissions import has_capability
from core.crud import CrmFormMixin, active_employees

from .models import Meeting


class MeetingForm(CrmFormMixin, forms.ModelForm):
    fieldsets = [
        ("Meeting", ["meeting_date", "start_time", "meeting_type", "location", "attendees", "held_by"]),
        ("What was discussed", ["summary", "points_discussed"]),
        ("Next step", ["next_action", "next_follow_up"]),
    ]

    class Meta:
        model = Meeting
        fields = ["meeting_date", "start_time", "meeting_type", "location", "attendees", "held_by", "summary",
                  "points_discussed", "next_action", "next_follow_up"]
        widgets = {"meeting_date": forms.DateInput(attrs={"type": "date"}),
                   "start_time": forms.TimeInput(attrs={"type": "time"}),
                   "next_follow_up": forms.DateInput(attrs={"type": "date"}),
                   "summary": forms.Textarea(attrs={"rows": 3}),
                   "points_discussed": forms.Textarea(attrs={"rows": 5,
                                                             "placeholder": "One point per line"})}

    def __init__(self, *args, can_assign=False, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.user
        if can_assign:
            self.fields["held_by"].queryset = active_employees()
        else:
            ids = [user.pk] + ([self.instance.held_by_id] if self.instance.pk else [])
            self.fields["held_by"].queryset = active_employees().filter(pk__in=ids)
        if not self.instance.pk:
            self.fields["held_by"].initial = user.pk
        self.fields["held_by"].required = False
        self.fields["held_by"].help_text = "Left empty: the person recording the meeting."
        self.fields["meeting_date"].help_text = "The day the meeting took place. Plan future meetings as Customer Visits."

    def clean_held_by(self):
        held = self.cleaned_data.get("held_by")
        if held:
            return held
        if self.instance.pk and self.instance.held_by_id:
            return self.instance.held_by
        return self.user

    def clean(self):
        data = super().clean()
        day, follow = data.get("meeting_date"), data.get("next_follow_up")
        if day and day > timezone.localdate():
            self.add_error("meeting_date", "A meeting is recorded after it happens. Plan future meetings as "
                                           "Customer Visits.")
        if day and follow and follow < day:
            self.add_error("next_follow_up", "The next follow-up cannot be before the meeting.")
        return data


def can_assign(user):
    return has_capability(user, "leads.assign") or has_capability(user, "records.assign")
