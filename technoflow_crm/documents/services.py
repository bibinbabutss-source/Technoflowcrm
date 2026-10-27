"""
Secure document handling.

- Extension must be in Settings > allowed file types, and the file's first bytes must match it
  (a renamed .exe saved as .pdf is refused).
- Size limit from Settings.
- Files get random internal names and are stored outside any public folder.
- A user may see or download a document only if they may see the record it is attached to.
- Files are never executed or displayed inline: downloads are always sent as attachments.
"""
import hashlib
import zipfile
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.permissions import has_capability, scope_queryset
from core.activity import record
from core.audit import log_action
from core.models import CompanyProfile
from core.registry import document_targets

from .models import Document

MIME = {
    "pdf": "application/pdf", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "doc": "application/msword", "xls": "application/vnd.ms-excel", "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "txt": "text/plain",
}
NEVER_ALLOWED = {"exe", "bat", "cmd", "sh", "js", "msi", "ps1", "php", "py", "html", "htm", "svg", "jar", "dll",
                 "com", "scr", "vbs", "hta"}


def _sniff_ok(ext, head, fileobj):
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext in ("doc", "xls"):
        return head.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if ext in ("docx", "xlsx"):
        if not head.startswith(b"PK\x03\x04"):
            return False
        try:
            fileobj.seek(0)
            with zipfile.ZipFile(fileobj) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            return False
        finally:
            fileobj.seek(0)
        return "[Content_Types].xml" in names and (("word/document.xml" in names) if ext == "docx"
                                                     else ("xl/workbook.xml" in names))
    if ext in ("csv", "txt"):
        return b"\x00" not in head
    return False


def validate_upload(f):
    company = CompanyProfile.get()
    name = Path(f.name).name
    ext = Path(name).suffix.lower().lstrip(".")
    allowed = set(company.extension_list) - NEVER_ALLOWED
    if ext not in allowed:
        raise ValidationError(f"Files of type .{ext or '?'} are not allowed. Allowed: {', '.join(sorted(allowed))}.")
    limit = company.max_upload_mb * 1024 * 1024
    if f.size > limit:
        raise ValidationError(f"The file is {f.size / 1024 / 1024:.1f} MB; the limit is {company.max_upload_mb} MB.")
    if f.size == 0:
        raise ValidationError("The file is empty.")
    f.seek(0)
    head = f.read(2048)
    f.seek(0)
    if not _sniff_ok(ext, head, f):
        raise ValidationError(f"The file content does not match a real .{ext} file.")
    return name, ext


def _sha256(f):
    h = hashlib.sha256()
    f.seek(0)
    for chunk in f.chunks():
        h.update(chunk)
    f.seek(0)
    return h.hexdigest()


def target_info(obj):
    return document_targets.get(obj._meta.label_lower)


def can_view_target(user, obj):
    info = target_info(obj)
    if info is None or not has_capability(user, info["capability"]):
        return False
    return scope_queryset(info["model"].objects.filter(pk=obj.pk), user, info["owner_fields"]).exists()


def visible_documents(user, base=None):
    """Documents whose target record the user may see."""
    if not has_capability(user, "documents.view"):
        return Document.objects.none()
    qs = base if base is not None else Document.objects.all()
    cond = Q(pk__in=[])
    for label, info in document_targets.items():
        if not has_capability(user, info["capability"]):
            continue
        ct = ContentType.objects.get_for_model(info["model"])
        ids = scope_queryset(info["model"].objects.all(), user, info["owner_fields"]).values("pk")
        cond |= Q(target_type=ct, target_id__in=ids)
    return qs.filter(cond)


def can_view(user, doc):
    return has_capability(user, "documents.view") and doc.target is not None and can_view_target(user, doc.target)


def _customer_of(obj):
    if obj.__class__.__name__ == "Customer":
        return obj
    return getattr(obj, "customer", None)


@transaction.atomic
def upload(*, target, f, title, user, description="", category=None, replaces=None):
    if not has_capability(user, "documents.upload"):
        raise PermissionDenied("You are not allowed to upload documents.")
    if not can_view_target(user, target):
        raise PermissionDenied("You cannot attach documents to this record.")
    name, ext = validate_upload(f)
    version, previous = 1, None
    if replaces is not None:
        previous = Document.objects.select_for_update().get(pk=replaces.pk)
        if not previous.is_current:
            raise ValidationError("Only the current version can be replaced.")
        version = previous.version + 1
        previous.is_current = False
        previous.save(update_fields=["is_current", "updated_at", "updated_by"])
    doc = Document(title=title or name, description=description, category=category, original_name=name[:255],
                   size=f.size, content_type_mime=MIME.get(ext, "application/octet-stream"), sha256=_sha256(f),
                   version=version, previous=previous, target=target, customer=_customer_of(target),
                   uploaded_by=user)
    doc.file.save(name, f, save=False)
    doc.save()
    msg = f"Document {'replaced (v' + str(version) + ')' if previous else 'uploaded'}: {doc.title}"
    record(target, "document", msg, customer=doc.customer)
    log_action("create", doc, message=f"{msg} ({name}, {f.size} bytes)")
    return doc


def archive(doc, user, archived=True):
    if not has_capability(user, "documents.delete"):
        raise PermissionDenied
    doc.is_archived = archived
    doc.archived_at = timezone.now() if archived else None
    doc.save(update_fields=["is_archived", "archived_at", "updated_at", "updated_by"])
    log_action("archive" if archived else "update", doc, message="Document archived" if archived else "Restored")


@transaction.atomic
def delete_permanently(doc, user):
    """Controlled deletion: administrator only, archived documents only, logged; the file is removed."""
    if not has_capability(user, "documents.delete"):
        raise PermissionDenied
    if not doc.is_archived:
        raise ValidationError("Archive the document first; only archived documents can be deleted.")
    if hasattr(doc, "next_version") and doc.next_version is not None:
        raise ValidationError("Older versions are kept with the current version and cannot be deleted alone.")
    log_action("delete", doc, message=f"Document deleted permanently: {doc.original_name} (sha256 {doc.sha256})")
    record(doc.target, "document", f"Document deleted: {doc.title}", customer=doc.customer) if doc.target else None
    storage, name = doc.file.storage, doc.file.name
    previous = doc.previous
    doc.delete()
    storage.delete(name)
    if previous is not None:
        Document.objects.filter(pk=previous.pk).update(is_current=True)
