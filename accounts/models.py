from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.utils import timezone

from core.models import TimeStampedModel

from . import capabilities as caps


class Capability(models.Model):
    """One thing a role may do, e.g. 'quotations.approve'."""

    code = models.CharField(max_length=60, unique=True)
    module = models.CharField(max_length=60)
    label = models.CharField(max_length=150)

    class Meta:
        ordering = ["module", "code"]
        verbose_name_plural = "capabilities"

    def __str__(self):
        return f"{self.module}: {self.label}"


class Role(TimeStampedModel):
    class Scope(models.TextChoices):
        ALL = "all", "All records"
        TEAM = "team", "Own records and records of linked team members"
        OWN = "own", "Own and assigned records only"

    code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=60, unique=True)
    description = models.CharField(max_length=255, blank=True)
    max_accounts = models.PositiveSmallIntegerField(
        "Maximum active accounts", validators=[MinValueValidator(1), MaxValueValidator(50)]
    )
    data_scope = models.CharField(max_length=10, choices=Scope.choices, default=Scope.OWN)
    capabilities = models.ManyToManyField(Capability, blank=True, related_name="roles")
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self):
        return self.name

    @property
    def is_admin_role(self):
        return self.code == caps.ADMIN

    def active_count(self, exclude_user_id=None):
        qs = EmployeeProfile.objects.filter(role=self, user__is_active=True)
        if exclude_user_id:
            qs = qs.exclude(user_id=exclude_user_id)
        return qs.count()

    def clean(self):
        if self.pk and self.max_accounts is not None:
            active = self.active_count()
            if self.max_accounts < active:
                raise ValidationError(
                    {"max_accounts": f"{active} active account(s) already hold this role. "
                                     f"Deactivate accounts before lowering the limit below {active}."}
                )


class AccountLimitError(ValidationError):
    pass


def check_role_capacity(role, user_id=None):
    """
    Raise AccountLimitError if giving `role` to an active user would exceed
    the role's account limit. Locks the role row so two administrators
    saving at the same moment cannot both pass the check.
    """
    with transaction.atomic():
        locked = Role.objects.select_for_update().get(pk=role.pk)
        if locked.active_count(exclude_user_id=user_id) >= locked.max_accounts:
            raise AccountLimitError(
                f"The {locked.name} role already has {locked.max_accounts} active account(s), "
                f"which is its limit. Deactivate an account or raise the limit in Settings > Roles."
            )


class EmployeeProfile(TimeStampedModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="profile")
    employee_id = models.CharField("Employee ID", max_length=20, unique=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="profiles")
    department = models.CharField(max_length=100, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    phone = models.CharField("Contact number", max_length=40, blank=True)
    reporting_manager = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="direct_reports"
    )
    team_members = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="supported_by",
        help_text="For Sales Coordinators: the engineers whose records they can see and coordinate.",
    )
    must_change_password = models.BooleanField(default=True)
    # Optional two-step sign-in (TOTP authenticator app). The secret is only stored once confirmed.
    mfa_enabled = models.BooleanField("Two-step sign-in", default=False)
    mfa_secret = models.CharField(max_length=64, blank=True, editable=False)
    mfa_last_counter = models.BigIntegerField(null=True, blank=True, editable=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["user__first_name", "user__last_name"]

    def __str__(self):
        return self.full_name

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    def clean(self):
        if self.reporting_manager_id and self.reporting_manager_id == self.pk:
            raise ValidationError({"reporting_manager": "An employee cannot report to themselves."})

    def save(self, *args, **kwargs):
        # Backend enforcement of role account limits, whatever screen or
        # script saves the profile.
        role_changed = True
        if self.pk:
            old_role_id = EmployeeProfile.objects.filter(pk=self.pk).values_list("role_id", flat=True).first()
            role_changed = old_role_id != self.role_id
            if role_changed and old_role_id:
                old_role = Role.objects.get(pk=old_role_id)
                if old_role.is_admin_role and self.user.is_active and old_role.active_count(self.user_id) == 0:
                    raise ValidationError("The last active System Administrator cannot be moved to another role.")
        if role_changed and self.user.is_active:
            check_role_capacity(self.role, user_id=self.user_id)
        super().save(*args, **kwargs)

    # -- permissions --------------------------------------------------
    def capability_codes(self):
        """
        The role's permissions, minus the Finance permissions while the Finance module is turned off
        (Settings > Modules & approvals). Roles keep their stored permissions, so turning Finance on again
        restores access exactly as before.
        """
        if not hasattr(self, "_cap_cache"):
            codes = set(self.role.capabilities.values_list("code", flat=True))
            if codes & caps.FINANCE_CAPABILITIES:
                from core.models import CompanyProfile

                if not CompanyProfile.get().finance_enabled:
                    codes -= caps.FINANCE_CAPABILITIES
            self._cap_cache = codes
        return self._cap_cache


class LoginHistory(models.Model):
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="login_history"
    )
    username = models.CharField(max_length=150, help_text="Username as typed")
    event = models.CharField(
        max_length=10, choices=[("login", "Login"), ("logout", "Logout"), ("failed", "Failed")]
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name_plural = "login history"

    def __str__(self):
        return f"{self.timestamp:%d-%b-%Y %H:%M} {self.username} {self.event}"
