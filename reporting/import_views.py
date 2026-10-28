from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import any_capability_required, has_capability
from core.crud import CrmFormMixin
from core.exports import csv_response

from . import imports
from .import_kinds import KINDS
from .models import ImportBatch


def _can_import(user):
    return has_capability(user, "data.import") or has_capability(user, "imports.own")


def _kinds_for(user):
    return [(k, v["label"]) for k, v in KINDS.items() if has_capability(user, v["create_cap"])]


class UploadForm(CrmFormMixin, forms.Form):
    kind = forms.ChoiceField(label="What are you importing?")
    mode = forms.ChoiceField(choices=ImportBatch.Mode.choices, initial="skip", widget=forms.RadioSelect,
                             required=False, label="When a row matches a record already in the CRM")
    file = forms.FileField(help_text="Excel (.xlsx) or CSV, first row = column headings, at most 2,000 rows and 5 MB.")

    def __init__(self, *args, kinds=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = list(kinds)


def _guard(request):
    if not _can_import(request.user):
        raise PermissionDenied


def _check_kind(user, kind):
    if kind not in KINDS or not has_capability(user, KINDS[kind]["create_cap"]):
        raise PermissionDenied("You are not allowed to import this type of record.")


@any_capability_required("data.import", "imports.own")
def import_start(request):
    _guard(request)
    kinds = _kinds_for(request.user)
    form = UploadForm(request.POST or None, request.FILES or None, user=request.user, kinds=kinds,
                      initial={"kind": request.GET.get("kind")})
    if request.method == "POST" and form.is_valid():
        kind = form.cleaned_data["kind"]
        _check_kind(request.user, kind)
        try:
            headers, rows = imports.parse_file(form.cleaned_data["file"])
        except ValidationError as exc:
            form.add_error("file", exc.messages)
        else:
            batch = ImportBatch.objects.create(kind=kind, mode=form.cleaned_data["mode"] or "skip",
                                               file_name=form.cleaned_data["file"].name[:255],
                                               uploaded_by=request.user, headers=headers, rows=rows,
                                               mapping=imports.guess_mapping(kind, headers))
            if not imports.missing_required(kind, batch.mapping):
                try:
                    imports.preview(batch, request.user)
                except Exception:  # never show internals; the user can still map columns by hand
                    imports.log.exception("Import preview failed for batch %s", batch.pk)
            return redirect(batch.get_absolute_url() + ("#preview" if batch.status == "preview" else ""))
    recent = ImportBatch.objects.filter(uploaded_by=request.user)[:10]
    return render(request, "reporting/import_start.html", {
        "form": form, "recent": recent, "kinds": [(k, KINDS[k]) for k, _ in kinds],
        "full": has_capability(request.user, "data.import")})


@any_capability_required("data.import", "imports.own")
def import_template(request, kind):
    _guard(request)
    _check_kind(request.user, kind)
    response = HttpResponse(imports.template_workbook(kind), content_type=(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
    response["Content-Disposition"] = f'attachment; filename="technoflow_import_template_{kind}.xlsx"'
    return response


def _get(request, pk):
    _guard(request)
    batch = get_object_or_404(ImportBatch, pk=pk)
    if batch.uploaded_by != request.user and not has_capability(request.user, "users.manage"):
        raise Http404
    return batch


@any_capability_required("data.import", "imports.own")
def import_detail(request, pk):
    batch = _get(request, pk)
    fields = KINDS[batch.kind]["fields"]
    if request.method == "POST" and batch.status in (batch.Status.MAPPING, batch.Status.PREVIEW):
        _check_kind(request.user, batch.kind)
        mapping = {}
        for f in fields:
            raw = request.POST.get(f"map_{f.name}", "")
            if raw.isdigit() and int(raw) < len(batch.headers):
                mapping[f.name] = int(raw)
        batch.mapping = mapping
        mode = request.POST.get("mode")
        if mode in ImportBatch.Mode.values:
            batch.mode = mode
        missing = imports.missing_required(batch.kind, mapping)
        if missing:
            batch.save()
            messages.error(request, "Choose a column for: " + ", ".join(missing))
            return redirect(batch.get_absolute_url())
        try:
            imports.preview(batch, request.user)
        except Exception:
            imports.log.exception("Import preview failed for batch %s", batch.pk)
            messages.error(request, "The file could not be checked. Make sure each column holds the right kind "
                                    "of data and try again.")
            return redirect(batch.get_absolute_url())
        return redirect(batch.get_absolute_url() + "#preview")
    results = batch.results or []
    preview_rows = []
    if batch.status in (batch.Status.PREVIEW, batch.Status.IMPORTED) and results:
        col_idx = [batch.mapping.get(f.name) for f in fields]
        for res, raw in list(zip(results, batch.rows))[:300]:
            preview_rows.append({"res": res, "cells": [raw[i] if raw and i is not None and i < len(raw) else ""
                                                      for i in col_idx]})
    return render(request, "reporting/import_detail.html", {
        "batch": batch, "fields": [(f.name, f.label, f.required, batch.mapping.get(f.name), f.help) for f in fields],
        "headers": list(enumerate(batch.headers)), "preview_rows": preview_rows,
        "field_labels": [f.label for f in fields], "sample": [r for r in batch.rows if r][:3],
        "modes": ImportBatch.Mode.choices,
        "missing": imports.missing_required(batch.kind, batch.mapping)})


@require_POST
@any_capability_required("data.import", "imports.own")
def import_run(request, pk):
    batch = _get(request, pk)
    _check_kind(request.user, batch.kind)
    try:
        created, updated = imports.run_import(batch, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    except Exception:
        imports.log.exception("Import failed for batch %s", batch.pk)
        messages.error(request, "The import failed and nothing was saved. Check the file and try again; if it "
                                "fails again, ask the System Administrator to look at the error log.")
    else:
        batch.refresh_from_db()
        messages.success(request, f"{created} created, {updated} updated. {batch.summary.get('duplicates', 0)} "
                                  f"duplicates and {batch.summary.get('errors', 0)} rows with errors were skipped.")
    return redirect(batch.get_absolute_url())


@any_capability_required("data.import", "imports.own")
def import_errors(request, pk):
    batch = _get(request, pk)
    return csv_response(f"import_{batch.pk}_rows_not_imported", ["Excel row", "Problem", "Details"] + batch.headers,
                        imports.problem_rows(batch))


@require_POST
@any_capability_required("data.import", "imports.own")
def import_cancel(request, pk):
    batch = _get(request, pk)
    if batch.status != batch.Status.IMPORTED:
        batch.status = batch.Status.CANCELLED
        batch.rows = []
        batch.results = []
        batch.save()
        messages.success(request, "Import cancelled; the uploaded rows were discarded. Nothing was saved.")
    return redirect("reporting:import_start")
