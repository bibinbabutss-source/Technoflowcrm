from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required, has_capability
from core.crud import CrmFormMixin
from core.exports import csv_response

from . import imports
from .models import ImportBatch


class UploadForm(CrmFormMixin, forms.Form):
    kind = forms.ChoiceField(choices=ImportBatch.Kind.choices, label="Import")
    file = forms.FileField(help_text="Excel (.xlsx) or CSV, first row = column headings, at most 2,000 rows, 5 MB.")


def _check_kind(user, kind):
    if kind == "leads" and not has_capability(user, "leads.create"):
        raise PermissionDenied("You cannot create leads.")
    if kind == "customers" and not has_capability(user, "customers.create"):
        raise PermissionDenied("You cannot create customers.")


@capability_required("data.import")
def import_start(request):
    form = UploadForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        kind = form.cleaned_data["kind"]
        _check_kind(request.user, kind)
        try:
            headers, rows = imports.parse_file(form.cleaned_data["file"])
        except ValidationError as exc:
            form.add_error("file", exc.messages)
        else:
            batch = ImportBatch.objects.create(kind=kind, file_name=form.cleaned_data["file"].name[:255],
                                               uploaded_by=request.user, headers=headers, rows=rows,
                                               mapping=imports.guess_mapping(kind, headers))
            return redirect("reporting:import_detail", pk=batch.pk)
    recent = ImportBatch.objects.filter(uploaded_by=request.user)[:10]
    return render(request, "reporting/import_start.html", {"form": form, "recent": recent})


def _get(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk)
    if batch.uploaded_by != request.user and not has_capability(request.user, "users.manage"):
        raise PermissionDenied
    return batch


@capability_required("data.import")
def import_detail(request, pk):
    batch = _get(request, pk)
    fields = imports.FIELDS[batch.kind]
    if request.method == "POST" and batch.status in (batch.Status.MAPPING, batch.Status.PREVIEW):
        _check_kind(request.user, batch.kind)
        mapping = {}
        for fname, *_ in fields:
            raw = request.POST.get(f"map_{fname}", "")
            if raw.isdigit() and int(raw) < len(batch.headers):
                mapping[fname] = int(raw)
        batch.mapping = mapping
        missing = [label for fname, label, req, _ in fields if req and fname not in mapping]
        if missing:
            batch.save()
            messages.error(request, "Choose a column for: " + ", ".join(missing))
            return redirect(batch.get_absolute_url())
        imports.preview(batch, request.user)
        return redirect(batch.get_absolute_url() + "#preview")
    results = batch.results or []
    preview_rows = []
    if batch.status in (batch.Status.PREVIEW, batch.Status.IMPORTED) and results:
        col_idx = [batch.mapping.get(f[0]) for f in fields]
        for res, raw in list(zip(results, batch.rows))[:300]:
            preview_rows.append({"res": res, "cells": [raw[i] if i is not None and i < len(raw) else ""
                                                      for i in col_idx]})
    return render(request, "reporting/import_detail.html", {
        "batch": batch, "fields": [(f, label, req, batch.mapping.get(f)) for f, label, req, _ in fields],
        "headers": list(enumerate(batch.headers)), "preview_rows": preview_rows,
        "field_labels": [label for _, label, _, _ in fields],
        "sample": batch.rows[:3]})


@require_POST
@capability_required("data.import")
def import_run(request, pk):
    batch = _get(request, pk)
    _check_kind(request.user, batch.kind)
    try:
        created = imports.run_import(batch, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"{created} {batch.get_kind_display().lower()} imported. "
                                  f"{batch.summary.get('duplicates', 0)} duplicates and "
                                  f"{batch.summary.get('errors', 0)} rows with errors were skipped.")
    return redirect(batch.get_absolute_url())


@capability_required("data.import")
def import_errors(request, pk):
    batch = _get(request, pk)
    rows = [[r["row"], r["status"], "; ".join(r["messages"])] + raw
            for r, raw in zip(batch.results, batch.rows) if r["status"] != "ok"]
    return csv_response(f"import_{batch.pk}_problems", ["File row", "Problem", "Details"] + batch.headers, rows)


@require_POST
@capability_required("data.import")
def import_cancel(request, pk):
    batch = _get(request, pk)
    if batch.status != batch.Status.IMPORTED:
        batch.status = batch.Status.CANCELLED
        batch.rows = []
        batch.save()
        messages.success(request, "Import cancelled; the uploaded rows were discarded.")
    return redirect("reporting:import_start")
