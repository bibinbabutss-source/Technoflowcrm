"""
Sales meetings: the minutes of each meeting held with a customer about a lead or an opportunity.

A meeting always belongs to a customer, and to the lead and / or opportunity it was about. Meetings recorded
while the deal was still a lead stay linked to that lead, so the opportunity (which carries the same lead) shows
the whole story and the CRM can count how many meetings happened before the deal entered the sales pipeline.
Future appointments are planned as Customer Visits; a meeting records what was actually discussed.
"""
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import TimeStampedModel


class Meeting(TimeStampedModel):
    class Type(models.TextChoices):
        IN_PERSON = "in_person", "In person / at site"
        ONLINE = "online", "Online (Teams, Zoom ...)"
        PHONE = "phone", "Phone call"

    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="meetings")
    lead = models.ForeignKey("leads.Lead", null=True, blank=True, on_delete=models.PROTECT, related_name="meetings")
    opportunity = models.ForeignKey("sales.Opportunity", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="meetings")
    meeting_date = models.DateField("Meeting date", default=timezone.localdate, db_index=True)
    start_time = models.TimeField("Time", null=True, blank=True)
    meeting_type = models.CharField("Type", max_length=12, choices=Type.choices, default=Type.IN_PERSON)
    location = models.CharField(max_length=200, blank=True)
    attendees = models.CharField("Customer attendees", max_length=255, blank=True,
                                 help_text="Names and roles of the people from the customer's side.")
    held_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="meetings_held",
                                verbose_name="Held by")
    summary = models.TextField("Meeting summary")
    points_discussed = models.TextField("Points discussed", blank=True,
                                        help_text="One point per line: requirements, prices, objections, decisions.")
    next_action = models.CharField("Next action", max_length=255, blank=True)
    next_follow_up = models.DateField("Next follow-up date", null=True, blank=True, db_index=True)
    in_pipeline = models.BooleanField("Held after the deal entered the sales pipeline", default=False,
                                      editable=False, db_default=False)

    class Meta:
        ordering = ["-meeting_date", "-start_time", "-pk"]

    def __str__(self):
        return f"Meeting {self.meeting_date:%d-%b-%Y} · {self.customer}"

    def get_absolute_url(self):
        if self.opportunity_id:
            return reverse("sales:opportunity_detail", args=[self.opportunity_id]) + f"#meeting-{self.pk}"
        if self.lead_id:
            return reverse("leads:detail", args=[self.lead_id]) + f"#meeting-{self.pk}"
        return reverse("customers:detail", args=[self.customer_id])

    @property
    def points(self):
        return [p.strip(" -•\t") for p in (self.points_discussed or "").splitlines() if p.strip(" -•\t")]

    @property
    def stage_label(self):
        return "In the pipeline" if self.in_pipeline else "Lead stage"
