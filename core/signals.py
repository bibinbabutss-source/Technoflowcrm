from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .audit import track_model
from .models import CompanyProfile, LookupValue, NumberSequence

track_model(CompanyProfile)
track_model(NumberSequence, exclude=["last_number", "current_year"])
track_model(LookupValue)


@receiver(post_migrate)
def seed(sender, app_config=None, **kwargs):
    if app_config is not None and app_config.label == "core":
        from .setup import seed_defaults

        seed_defaults()
