"""Add, edit and delete sales meetings. Access always goes through the lead / opportunity the meeting is about."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.permissions import has_capability
from core.audit import log_action
from core.crud import get_scoped_or_404

from .forms import MeetingForm, can_assign
from .models import Meeting
from .services import after_save

KINDS = {"lead": ("leads.Lead", "leads.edit"), "opportunity": ("sales.Opportunity", "pipeline.edit")}


def _parent(request, kind, pk):
    from django.apps import apps

    from core.scopes import owners

    if kind not in KINDS:
        raise Http404
    model_path, cap = KINDS[kind]
    model = apps.get_model(model_path)
    obj = get_scoped_or_404(model, request.user, pk, owners(model._meta.label_lower))
    if not has_capability(request.user, cap):
        raise PermissionDenied
    if getattr(obj, "is_archived", False):
        raise PermissionDenied("Archived records cannot be changed.")
    return obj


def _meeting_parent(request, meeting):
    if meeting.opportunity_id:
        return "opportunity", _parent(request, "opportunity", meeting.opportunity_id)
    if meeting.lead_id:
        return "lead", _parent(request, "lead", meeting.lead_id)
    raise Http404


def meeting_add(request, kind, pk):
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path())
    parent = _parent(request, kind, pk)
    customer = parent.customer
    if customer is None:
        messages.error(request, "Link this lead to a customer first (Edit lead), then record the meeting.")
        return redirect(parent.get_absolute_url())
    form = MeetingForm(request.POST or None, user=request.user, can_assign=can_assign(request.user))
    if request.method == "POST" and form.is_valid():
        m = form.save(commit=False)
        m.customer = customer
        if kind == "opportunity":
            m.opportunity, m.lead, m.in_pipeline = parent, parent.lead, True
        else:
            m.lead = parent
            m.in_pipeline = bool(parent.converted_at and m.meeting_date >= parent.converted_at.date())
            if m.in_pipeline:
                m.opportunity = parent.opportunities.filter(is_archived=False).order_by("-created_at").first()
        m.save()
        after_save(m, created=True)
        messages.success(request, "Meeting recorded.")
        return redirect(m.get_absolute_url())
    return render(request, "meetings/form.html", {"form": form, "parent": parent, "kind": kind,
                                                  "title": f"Record a meeting · {parent}"})


def meeting_edit(request, pk):
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login

        return redirect_to_login(request.get_full_path())
    meeting = get_object_or_404(Meeting, pk=pk)
    kind, parent = _meeting_parent(request, meeting)
    form = MeetingForm(request.POST or None, instance=meeting, user=request.user,
                       can_assign=can_assign(request.user))
    if request.method == "POST" and form.is_valid():
        m = form.save()
        after_save(m, created=False)
        messages.success(request, "Meeting saved.")
        return redirect(m.get_absolute_url())
    return render(request, "meetings/form.html", {"form": form, "parent": parent, "kind": kind, "meeting": meeting,
                                                  "title": f"Edit meeting · {parent}"})


@require_POST
def meeting_delete(request, pk):
    if not request.user.is_authenticated:
        raise PermissionDenied
    meeting = get_object_or_404(Meeting, pk=pk)
    kind, parent = _meeting_parent(request, meeting)
    allowed = meeting.created_by_id == request.user.pk or has_capability(
        request.user, "leads.archive" if kind == "lead" else "pipeline.archive")
    if not allowed:
        raise PermissionDenied("Only the person who recorded the meeting or a manager can delete it.")
    log_action("delete", meeting, message=f"Meeting of {meeting.meeting_date:%d-%b-%Y} deleted: "
                                          f"{meeting.summary[:200]}")
    meeting.delete()
    messages.success(request, "Meeting deleted.")
    return redirect(parent.get_absolute_url() + "#meetings")
