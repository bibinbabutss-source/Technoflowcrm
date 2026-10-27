from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from core.models import NumberSequence, TimeStampedModel
from core.scopes import owners

OWNER_FIELDS = owners("communications.communication")


class Communication(TimeStampedModel):
    """
    A manually logged interaction. Emails, WhatsApp messages and calls are NOT synchronised
    automatically: no such integration is installed. The model is ready for one to be added.
    """

    class Kind(models.TextChoices):
        CALL = "call", "Telephone call"
        EMAIL = "email", "Email"
        WHATSAPP = "whatsapp", "WhatsApp"
        MEETING = "meeting", "Customer meeting"
        SITE_VISIT = "site_visit", "Site visit"
        ONLINE = "online", "Online meeting"
        INTERNAL = "internal", "Internal discussion"
        FOLLOW_UP = "follow_up", "Follow-up"

    class Direction(models.TextChoices):
        INBOUND = "in", "Inbound"
        OUTBOUND = "out", "Outbound"
        INTERNAL = "internal", "Internal"

    code = models.CharField("Communication ID", max_length=20, unique=True, editable=False)
    customer = models.ForeignKey("customers.Customer", on_delete=models.PROTECT, related_name="communications")
    contact = models.ForeignKey("customers.CustomerContact", null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="+")
    lead = models.ForeignKey("leads.Lead", null=True, blank=True, on_delete=models.PROTECT,
                             related_name="communications")
    opportunity = models.ForeignKey("sales.Opportunity", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="communications")
    kind = models.CharField("Type", max_length=20, choices=Kind.choices, default=Kind.CALL, db_index=True)
    direction = models.CharField(max_length=10, choices=Direction.choices, default=Direction.OUTBOUND)
    occurred_at = models.DateTimeField("Date and time", default=timezone.now, db_index=True)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                 related_name="communications")
    subject = models.CharField(max_length=200)
    summary = models.TextField()
    outcome = models.CharField(max_length=255, blank=True)
    next_action = models.CharField(max_length=255, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=20, default="manual", editable=False,
                              help_text="manual, or the name of an integration that created the record")

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self):
        return f"{self.code} {self.subject}" if self.code else self.subject

    def get_absolute_url(self):
        return reverse("communications:detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = NumberSequence.next_value("communication")
        super().save(*args, **kwargs)
