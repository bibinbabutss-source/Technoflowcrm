"""
PDF generation (quotations, invoices, statements, reports).

Uses xhtml2pdf, a pure-Python library: it installs on Windows, Linux and Render
with no extra system software.
"""
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.template.loader import render_to_string

from .models import CompanyProfile


def _link_callback(uri, rel):
    """Resolve /static/... references in PDF templates to files on disk."""
    if uri.startswith(settings.STATIC_URL) or uri.startswith("/" + settings.STATIC_URL):
        relative = uri.split(settings.STATIC_URL.strip("/") + "/", 1)[1]
        found = finders.find(relative)
        if found:
            return found
        candidate = Path(settings.STATIC_ROOT) / relative
        if candidate.exists():
            return str(candidate)
    return uri


def render_pdf_bytes(template, context):
    from xhtml2pdf import pisa

    context = {"company": CompanyProfile.get(), **context}
    html = render_to_string(template, context)
    out = BytesIO()
    result = pisa.CreatePDF(html, dest=out, link_callback=_link_callback, encoding="utf-8")
    if result.err:
        raise RuntimeError(f"PDF generation failed for {template}")
    return out.getvalue()


def pdf_response(template, context, filename, *, download=False):
    data = render_pdf_bytes(template, context)
    response = HttpResponse(data, content_type="application/pdf")
    disposition = "attachment" if download else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}.pdf"'
    return response
