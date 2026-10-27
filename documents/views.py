from django import forms
from django.contrib import messages
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import capability_required, has_capability
from core.audit import log_action
from core.crud import (ChoiceFilter, Column, CrmFormMixin, CrmListView, DateRangeFilter, ModelFilter, UserFilter,
                       safe_next)
from core.models import LookupValue
from core.registry import document_targets

from . import services
from .models import Document


class UploadForm(CrmFormMixin, forms.Form):
    file = forms.FileField()
    title = forms.CharField(max_length=200, required=False, help_text="Leave empty to use the file name.")
    category = forms.ModelChoiceField(queryset=LookupValue.objects.filter(category="document_category",
                                                                           is_active=True), required=False)
    description = forms.CharField(max_length=500, required=False)


def _target_from_request(request):
    label = request.POST.get("target_type") or request.GET.get("target_type", "")
    info = document_targets.get(label)
    if info is None:
        raise Http404
    try:
        pk = int(request.POST.get("target_id") or request.GET.get("target_id"))
    except (TypeError, ValueError):
        raise Http404
    obj = info["model"].objects.filter(pk=pk).first()
    if obj is None or not services.can_view_target(request.user, obj):
        raise Http404
    return obj


def _get_visible(request, pk):
    doc = get_object_or_404(Document, pk=pk)
    if not services.can_view(request.user, doc):
        raise Http404
    return doc


class DocumentList(CrmListView):
    model = Document
    capability = "documents.view"
    title = "Documents"
    subtitle = "Files attached to customers, leads, opportunities, projects, visits, quotations, orders and invoices."
    icon = "folder2-open"
    owner_fields = None
    search_fields = ("title", "description", "original_name", "customer__company_name")
    columns = [
        Column("Document", "title", link=True), Column("File", "original_name"),
        Column("Version", lambda d: f"v{d.version}"), Column("Category", "category"),
        Column("Attached to", lambda d: f"{document_targets.get(d.target_type.model_class()._meta.label_lower, {}).get('label', '')}: {d.target}"),
        Column("Uploaded by", "uploaded_by"), Column("Uploaded", "created_at", date=True),
        Column("Size", lambda d: f"{d.size / 1024:,.0f} KB", align="end"),
    ]
    sort_options = {"newest": ("Newest first", ["-created_at"]), "title": ("Title", ["title"])}
    default_sort = "newest"

    def base_queryset(self):
        qs = Document.objects.select_related("category", "uploaded_by", "target_type", "customer")
        qs = services.visible_documents(self.request.user, qs)
        if self.request.GET.get("versions") != "all":
            qs = qs.filter(is_current=True)
        return qs

    def get_filters(self):
        types = [(label, info["label"]) for label, info in document_targets.items()]
        return [
            ModelFilter("category", "Category", lambda: LookupValue.objects.filter(category="document_category")),
            ChoiceFilter("type", "Attached to", types,
                         lookups={label: _ct_q(info["model"]) for label, info in document_targets.items()}),
            UserFilter("uploader", "Uploaded by", ["uploaded_by"]),
            DateRangeFilter("date", "Uploaded", "created_at"),
            ChoiceFilter("versions", "Versions", [("all", "Include older versions")], lookups={"all": _all()}),
        ]


def _ct_q(model):
    from django.db.models import Q

    return Q(target_type=ContentType.objects.get_for_model(model))


def _all():
    from django.db.models import Q

    return Q()


@capability_required("documents.view")
def document_detail(request, pk):
    doc = _get_visible(request, pk)
    versions = []
    v = doc
    while v.previous_id:
        v = v.previous
        versions.append(v)
    newer = []
    n = doc
    while hasattr(n, "next_version"):
        try:
            n = n.next_version
        except Document.DoesNotExist:
            break
        newer.append(n)
    return render(request, "documents/detail.html", {
        "doc": doc, "older": versions, "newer": newer,
        "target_label": document_targets.get(doc.target_type.model_class()._meta.label_lower, {}).get("label"),
        "replace_form": UploadForm(user=request.user) if doc.is_current and not doc.is_archived and has_capability(
            request.user, "documents.upload") else None,
        "can_delete": has_capability(request.user, "documents.delete"),
    })


@capability_required("documents.view")
def document_download(request, pk):
    doc = _get_visible(request, pk)
    try:
        handle = doc.file.open("rb")
    except FileNotFoundError:
        messages.error(request, "The file is missing from storage. Restore it from the document backup.")
        return redirect(doc.get_absolute_url())
    log_action("download", doc, message=f"Downloaded {doc.original_name}")
    response = FileResponse(handle, as_attachment=True, filename=doc.original_name,
                            content_type=doc.content_type_mime)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@require_POST
@capability_required("documents.upload")
def document_upload(request):
    target = _target_from_request(request)
    form = UploadForm(request.POST, request.FILES, user=request.user)
    replaces = None
    if request.POST.get("replaces"):
        replaces = _get_visible(request, request.POST["replaces"])
        target = replaces.target
    if form.is_valid():
        d = form.cleaned_data
        try:
            doc = services.upload(target=target, f=d["file"], title=d["title"] or (replaces.title if replaces else ""),
                                  user=request.user, description=d["description"],
                                  category=d["category"] or (replaces.category if replaces else None),
                                  replaces=replaces)
        except ValidationError as exc:
            messages.error(request, "Upload refused: " + " ".join(exc.messages))
        else:
            messages.success(request, f"'{doc.title}' uploaded (version {doc.version}).")
    else:
        messages.error(request, "Upload refused: " + " ".join(e for errs in form.errors.values() for e in errs))
    return redirect(safe_next(request, target.get_absolute_url()))


@require_POST
@capability_required("documents.delete")
def document_archive(request, pk):
    doc = _get_visible(request, pk)
    services.archive(doc, request.user, archived=not doc.is_archived)
    messages.success(request, f"'{doc.title}' {'archived' if doc.is_archived else 'restored'}.")
    return redirect(doc.get_absolute_url())


@require_POST
@capability_required("documents.delete")
def document_delete(request, pk):
    doc = _get_visible(request, pk)
    target_url = doc.target.get_absolute_url() if doc.target else None
    try:
        services.delete_permanently(doc, request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect(doc.get_absolute_url())
    messages.success(request, "Document deleted permanently. The deletion is recorded in the audit log.")
    return redirect(target_url or "documents:list")


def panel_context(user, target):
    if not has_capability(user, "documents.view") or services.target_info(target) is None:
        return None
    if not services.can_view_target(user, target):
        return None
    ct = ContentType.objects.get_for_model(target.__class__)
    docs = Document.objects.filter(target_type=ct, target_id=target.pk, is_current=True, is_archived=False) \
        .select_related("uploaded_by", "category")
    return {"docs": docs, "target": target, "target_type": target._meta.label_lower,
            "can_upload": has_capability(user, "documents.upload"), "form": UploadForm(user=user)}

