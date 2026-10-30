"""Rename two default opportunity stages to the names the business uses (Qualification, Proposal).
Only renames when the old default name exists and the new name is free; custom stage names are left alone."""
from django.db import migrations

RENAMES = [("Initial Discussion", "Qualification"), ("Proposal Preparation", "Proposal")]


def forwards(apps, schema_editor):
    Stage = apps.get_model("sales", "OpportunityStage")
    for old, new in RENAMES:
        if not Stage.objects.filter(name=new).exists():
            Stage.objects.filter(name=old).update(name=new)


def backwards(apps, schema_editor):
    Stage = apps.get_model("sales", "OpportunityStage")
    for old, new in RENAMES:
        if not Stage.objects.filter(name=old).exists():
            Stage.objects.filter(name=new).update(name=old)


class Migration(migrations.Migration):
    dependencies = [("sales", "0002_opportunity_team_members")]
    operations = [migrations.RunPython(forwards, backwards)]
