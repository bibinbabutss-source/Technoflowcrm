"""Settings pages added in Phases 3–7: workflow & reminders, tax rates, lead / opportunity stages."""
from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required

from .audit import log_action
from .forms import BootstrapMixin, TaxRateForm, WorkflowSettingsForm
from .models import CompanyProfile, SystemJobRun, TaxRate


@capability_required("settings.manage")
def workflow(request):
    company = CompanyProfile.get()
    form = WorkflowSettingsForm(request.POST or None, instance=company)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_action("update", company, message="Workflow, approval and reminder settings changed")
        messages.success(request, "Workflow settings saved.")
        return redirect("core:settings_workflow")
    return render(request, "core/settings_workflow.html", {
        "form": form, "tab": "workflow", "jobs": SystemJobRun.objects.all()})


@require_POST
@capability_required("settings.manage")
def run_reminders(request):
    from notifications import reminders

    from django.utils import timezone

    result = reminders.run()
    SystemJobRun.objects.update_or_create(name=reminders.JOB, defaults={
        "last_run_date": timezone.localdate(), "last_run_at": timezone.now(), "last_result": result[:500]})
    messages.success(request, f"Reminders run: {result}." if result else "Reminders run; nothing was due.")
    return redirect("core:settings_workflow")


@capability_required("settings.manage")
def tax_rates(request, pk=None):
    obj = get_object_or_404(TaxRate, pk=pk) if pk else None
    form = TaxRateForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        if obj and obj.is_default and not form.cleaned_data["is_default"] and \
                not TaxRate.objects.exclude(pk=obj.pk).filter(is_default=True).exists():
            form.add_error("is_default", "Choose another default rate first.")
        else:
            rate = form.save()
            log_action("update" if obj else "create", rate, message=f"Tax rate {rate}")
            messages.success(request, f"Tax rate '{rate}' saved. Existing documents keep the rate they were "
                                      f"created with.")
            return redirect("core:tax_rates")
    return render(request, "core/settings_tax.html", {"form": form, "obj": obj, "rates": TaxRate.objects.all(),
                                                     "tab": "tax"})


def _stage_models():
    from leads.models import LeadStage
    from sales.models import OpportunityStage

    return {"lead": (LeadStage, ["name", "order", "is_qualified", "is_active"], "Lead stages"),
            "opportunity": (OpportunityStage, ["name", "order", "default_probability", "is_active"],
                            "Opportunity stages")}


@capability_required("settings.manage")
def stages(request, kind="lead", pk=None):
    models_ = _stage_models()
    if kind not in models_:
        kind = "lead"
    Model, fields, title = models_[kind]
    obj = get_object_or_404(Model, pk=pk) if pk else None
    Form = forms.modelform_factory(Model, form=type("StageForm", (BootstrapMixin, forms.ModelForm), {}),
                                   fields=fields)
    form = Form(request.POST or None, instance=obj)
    if obj is not None and obj.is_closed:
        form.fields["is_active"].disabled = True
        form.fields["is_active"].help_text = "Won and Lost are system stages and always active."
    if request.method == "POST" and form.is_valid():
        name = form.cleaned_data["name"]
        if Model.objects.filter(name__iexact=name).exclude(pk=getattr(obj, "pk", None)).exists():
            form.add_error("name", "A stage with this name already exists.")
        elif obj is not None and not form.cleaned_data.get("is_active", True) and \
                Model.objects.filter(is_active=True, is_won=False, is_lost=False).exclude(pk=obj.pk).count() == 0:
            form.add_error("is_active", "At least one open stage must stay active.")
        else:
            stage = form.save()
            log_action("update" if obj else "create", stage, message=f"{title}: {stage}")
            messages.success(request, f"Stage '{stage}' saved.")
            return redirect("core:stages", kind=kind)
    return render(request, "core/settings_stages.html", {
        "form": form, "obj": obj, "kind": kind, "title": title, "stages": Model.objects.all(),
        "kinds": [(k, v[2]) for k, v in models_.items()], "tab": "stages"})
