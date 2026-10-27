from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.models import TimeStampedModel


class KPIDefinition(TimeStampedModel):
    """
    What is measured. The calculation behind each code is fixed (reporting/metrics.py, one place);
    the Administrator or a Sales Director can rename it, change its weight in the scorecard or switch it off.
    """

    code = models.CharField(max_length=40, unique=True, editable=False)
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=10, editable=False)  # amount / count / percent
    description = models.CharField("How it is calculated", max_length=300)
    weight = models.DecimalField("Scorecard weight (%)", max_digits=5, decimal_places=2, default=0,
                                 validators=[MinValueValidator(0), MaxValueValidator(100)])
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "KPI definition"

    def __str__(self):
        return self.name


class SalesTarget(TimeStampedModel):
    class Period(models.TextChoices):
        MONTH = "month", "Monthly"
        QUARTER = "quarter", "Quarterly"
        YEAR = "year", "Annual"

    employee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="targets", help_text="Empty = company-wide target")
    kpi = models.ForeignKey(KPIDefinition, on_delete=models.PROTECT, related_name="targets")
    period_type = models.CharField(max_length=10, choices=Period.choices)
    period_start = models.DateField(help_text="First day of the month, quarter or year")
    target_value = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(0)])
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-period_start", "kpi__sort_order"]
        constraints = [models.UniqueConstraint(fields=["employee", "kpi", "period_type", "period_start"],
                                               name="uniq_target")]

    def __str__(self):
        who = self.employee.get_full_name() if self.employee else "Company"
        return f"{who} · {self.kpi} · {self.get_period_type_display()} {self.period_start:%b %Y}"

    def clean(self):
        from reporting.metrics import period_bounds

        if self.period_start and self.period_type:
            start, _ = period_bounds(self.period_type, self.period_start)
            if start != self.period_start:
                raise ValidationError({"period_start": f"Use the first day of the period ({start:%d-%b-%Y})."})
        if self.kpi_id and self.kpi.unit == "percent" and self.target_value is not None and \
                self.target_value > Decimal(100):
            raise ValidationError({"target_value": "A percentage target cannot exceed 100."})
