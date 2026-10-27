"""
Shared building blocks for every CRM module's pages.

A module list page is declared, not hand-written:

    class LeadList(CrmListView):
        model = Lead
        capability = "leads.view"
        title = "Leads"
        owner_fields = ("assigned_engineer", "assigned_coordinator", "created_by")
        search_fields = ("code", "title", "company_name", "email", "phone")
        columns = [Column("Lead", "code", link=True), Column("Status", render=status_badge)]
        filters = [ChoiceFilter("status", "Status", Lead.Status.choices)]

Every list therefore gets the same search, filters, sorting, pagination,
archive toggle, record-level permission scope and CSV / Excel export.
"""
import datetime
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import ProtectedError, Q
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from accounts.permissions import CapabilityRequiredMixin, has_capability, scope_queryset, visible_user_ids

from .audit import log_action
from .exports import csv_response, xlsx_response
from .params import get_choice, get_date, get_int

User = get_user_model()


# ====================================================================== formatting
def money(value, currency=None):
    if value is None or value == "":
        return "—"
    value = Decimal(value).quantize(Decimal("0.01"))
    text = f"{value:,.2f}"
    return f"{currency} {text}" if currency else text


def fmt_date(value):
    if not value:
        return "—"
    if isinstance(value, datetime.datetime):
        value = timezone.localtime(value) if timezone.is_aware(value) else value
        return value.strftime("%d-%b-%Y %H:%M")
    return value.strftime("%d-%b-%Y")


BADGE_CLASSES = {
    "good": "badge-active", "neutral": "badge-inactive", "warn": "badge-warning", "bad": "badge-danger",
    "info": "badge-info",
}


def badge(label, tone="neutral"):
    return format_html('<span class="badge-status {}">{}</span>', BADGE_CLASSES.get(tone, "badge-inactive"), label)


def person(user):
    if not user:
        return "—"
    return user.get_full_name() or user.username


# ====================================================================== columns
class Column:
    def __init__(self, label, attr=None, *, render=None, text=None, sort=None, link=False, money=False,
                 date=False, css="", export=True, align=None):
        self.label = label
        self.attr = attr
        self.render_fn = render
        self.text_fn = text
        self.sort = sort
        self.link = link
        self.money = money
        self.date = date
        self.css = css
        self.export = export
        self.align = align or ("end" if money else None)

    def value(self, obj):
        if callable(self.attr):
            return self.attr(obj)
        value = obj
        for part in (self.attr or "").split("."):
            if value is None:
                return None
            value = getattr(value, part, None)
            if callable(value) and not hasattr(value, "all"):
                value = value()
        return value

    def text(self, obj):
        if self.text_fn:
            return self.text_fn(obj)
        value = self.value(obj)
        if hasattr(value, "get_full_name"):
            return person(value)
        if value is None:
            return ""
        if self.money:
            return Decimal(value)
        if isinstance(value, (datetime.date, datetime.datetime, bool, int, float, Decimal)):
            return value
        return str(value)

    def html(self, obj):
        if self.render_fn:
            content = self.render_fn(obj)
        else:
            value = self.value(obj)
            if hasattr(value, "get_full_name"):
                content = person(value)
            elif self.money:
                content = money(value)
            elif isinstance(value, (datetime.date, datetime.datetime)) or self.date:
                content = fmt_date(value)
            elif isinstance(value, bool):
                content = "Yes" if value else "No"
            elif value in (None, ""):
                content = "—"
            else:
                content = value
        if self.link and hasattr(obj, "get_absolute_url"):
            return format_html('<a class="fw-semibold" href="{}">{}</a>', obj.get_absolute_url(), content)
        return format_html("{}", content)


# ====================================================================== filters
class Filter:
    kind = "choice"

    def __init__(self, key, label, field=None):
        self.key = key
        self.label = label
        self.field = field or key

    def apply(self, qs, params, view):
        return qs

    def context(self, params, view):
        return {"key": self.key, "label": self.label, "kind": self.kind, "value": params.get(self.key, "")}


class ChoiceFilter(Filter):
    def __init__(self, key, label, choices, field=None, lookups=None):
        super().__init__(key, label, field)
        self._choices = choices
        self.lookups = lookups or {}  # value -> Q for computed choices (e.g. "overdue")

    def choices(self):
        choices = self._choices() if callable(self._choices) else self._choices
        return [(str(k), v) for k, v in choices]

    def apply(self, qs, params, view):
        value = params.get(self.key)
        if not value:
            return qs
        if value in self.lookups:
            return qs.filter(self.lookups[value]).distinct()
        if value not in {k for k, _ in self.choices()}:
            return qs
        return qs.filter(**{self.field: value})

    def context(self, params, view):
        ctx = super().context(params, view)
        ctx["choices"] = self.choices()
        return ctx


class ModelFilter(Filter):
    """Filter by a related record id, e.g. customer or stage."""

    def __init__(self, key, label, queryset, field=None, label_fn=str):
        super().__init__(key, label, field)
        self.queryset = queryset
        self.label_fn = label_fn

    def apply(self, qs, params, view):
        pk = get_int(params, self.key)
        return qs.filter(**{self.field: pk}) if pk else qs

    def context(self, params, view):
        ctx = super().context(params, view)
        qs = self.queryset() if callable(self.queryset) else self.queryset
        ctx["choices"] = [(str(o.pk), self.label_fn(o)) for o in qs]
        ctx["kind"] = "choice"
        return ctx


class UserFilter(Filter):
    """Filter by employee across one or more owner fields. Only users the viewer may see are offered."""

    def __init__(self, key, label, fields):
        super().__init__(key, label, fields[0])
        self.fields = fields

    def apply(self, qs, params, view):
        pk = get_int(params, self.key)
        if not pk:
            return qs
        cond = Q()
        for f in self.fields:
            cond |= Q(**{f: pk})
        return qs.filter(cond).distinct()

    def context(self, params, view):
        ctx = super().context(params, view)
        ctx["kind"] = "choice"
        ctx["choices"] = [(str(u.pk), person(u)) for u in employees_visible_to(view.request.user)]
        return ctx


class DateRangeFilter(Filter):
    kind = "daterange"

    def apply(self, qs, params, view):
        start, end = get_date(params, self.key + "_from"), get_date(params, self.key + "_to")
        lookup = self.field
        is_dt = _is_datetime_field(qs.model, self.field)
        if start:
            qs = qs.filter(**{f"{lookup}__date__gte" if is_dt else f"{lookup}__gte": start})
        if end:
            qs = qs.filter(**{f"{lookup}__date__lte" if is_dt else f"{lookup}__lte": end})
        return qs

    def context(self, params, view):
        ctx = super().context(params, view)
        ctx["value_from"] = params.get(self.key + "_from", "")
        ctx["value_to"] = params.get(self.key + "_to", "")
        return ctx


class BoolFilter(Filter):
    def __init__(self, key, label, q_true, q_false=None):
        super().__init__(key, label)
        self.q_true, self.q_false = q_true, q_false

    def apply(self, qs, params, view):
        value = params.get(self.key)
        if value == "yes":
            return qs.filter(self.q_true)
        if value == "no":
            return qs.filter(self.q_false) if self.q_false is not None else qs.exclude(self.q_true)
        return qs

    def context(self, params, view):
        ctx = super().context(params, view)
        ctx["kind"] = "choice"
        ctx["choices"] = [("yes", "Yes"), ("no", "No")]
        return ctx


def _is_datetime_field(model, path):
    from django.db.models import DateTimeField

    field = None
    try:
        for part in path.split("__"):
            field = model._meta.get_field(part)
            if field.is_relation and field.related_model is not None:
                model = field.related_model
    except Exception:
        return False
    return isinstance(field, DateTimeField)


# ====================================================================== people
def active_employees(role_codes=None):
    qs = User.objects.filter(is_active=True, profile__isnull=False).select_related("profile__role")
    if role_codes:
        qs = qs.filter(profile__role__code__in=role_codes)
    return qs.order_by("first_name", "last_name")


def employees_visible_to(user):
    ids = visible_user_ids(user)
    qs = User.objects.filter(profile__isnull=False).order_by("first_name", "last_name")
    return qs if ids is None else qs.filter(pk__in=ids)


class EmployeeChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        role = getattr(getattr(obj, "profile", None), "role", None)
        return f"{person(obj)}" + (f" ({role.name})" if role else "")


# ====================================================================== forms
class CrmFormMixin:
    """Bootstrap styling, HTML5 date/time inputs and optional fieldsets for every CRM form."""

    fieldsets = None

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            w = field.widget
            if isinstance(field, forms.DateTimeField):
                field.widget = forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"},
                                                   format="%Y-%m-%dT%H:%M")
                field.input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]
            elif isinstance(field, forms.DateField):
                field.widget = forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d")
            elif isinstance(field, forms.TimeField):
                field.widget = forms.TimeInput(attrs={"type": "time", "class": "form-control"}, format="%H:%M")
            elif isinstance(w, forms.CheckboxInput):
                w.attrs.setdefault("class", "form-check-input")
            elif isinstance(w, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                pass
            elif isinstance(w, (forms.Select, forms.SelectMultiple)):
                w.attrs.setdefault("class", "form-select")
            else:
                w.attrs.setdefault("class", "form-control")
            if isinstance(w, forms.Textarea):
                w.attrs.setdefault("rows", 3)
            if isinstance(field, forms.DecimalField):
                w.attrs.setdefault("step", "0.01")

    def get_fieldsets(self):
        if not self.fieldsets:
            return [(None, [self[name] for name in self.fields])]
        used, out = set(), []
        for title, names in self.fieldsets:
            fields = [self[n] for n in names if n in self.fields]
            used.update(n for n in names)
            if fields:
                out.append((title, fields))
        rest = [self[n] for n in self.fields if n not in used]
        if rest:
            out.append(("Other", rest))
        return out


def lookup_field(category, label=None, required=False, current=None):
    """A drop-down of active values from Settings > Drop-down lists (a hidden value stays valid if already used)."""
    from .models import LookupValue

    qs = LookupValue.objects.filter(category=category)
    qs = qs.filter(Q(is_active=True) | Q(pk=current)) if current else qs.filter(is_active=True)
    return forms.ModelChoiceField(queryset=qs, required=required, label=label)


def restrict_lookups(form, mapping):
    """Limit lookup FK fields to active values (+ the record's current value). mapping = {field: category}."""
    from .models import LookupValue

    for name, category in mapping.items():
        if name not in form.fields:
            continue
        current = getattr(form.instance, f"{name}_id", None) if getattr(form, "instance", None) else None
        cond = Q(is_active=True)
        if current:
            cond |= Q(pk=current)
        form.fields[name].queryset = LookupValue.objects.filter(category=category).filter(cond)


def limit_assignees(form, field_names, role_codes_by_field, *, can_assign):
    """
    Restrict 'assigned to' drop-downs to active employees of the right roles.
    Users without the assign capability can only choose themselves.
    """
    for name in field_names:
        if name not in form.fields:
            continue
        current_id = getattr(form.instance, f"{name}_id", None) if getattr(form, "instance", None) else None
        roles = role_codes_by_field.get(name)
        qs = active_employees(roles)
        if not can_assign:
            ids = {form.user.pk} if form.user else set()
            if current_id:
                ids.add(current_id)
            qs = User.objects.filter(pk__in=ids)
        elif current_id:
            qs = (qs | User.objects.filter(pk=current_id)).distinct()
        form.fields[name].queryset = qs
        form.fields[name].__class__ = EmployeeChoiceField


# ====================================================================== views
class ScopedMixin:
    """Restricts a model's records to those the user may see (role data scope)."""

    owner_fields = ("created_by",)

    def scope(self, qs):
        return scope_queryset(qs, self.request.user, self.owner_fields) if self.owner_fields else qs


class CrmListView(CapabilityRequiredMixin, ScopedMixin, TemplateView):
    template_name = "crud/list.html"
    model = None
    title = ""
    subtitle = ""
    icon = "list"
    columns = []
    filters = []
    search_fields = ()
    search_placeholder = "Search"
    sort_options = {}            # key -> (label, [order_by...])
    default_sort = None
    paginate_by = 25
    archive_field = "is_archived"  # None if the model cannot be archived
    create_url = None            # url name
    create_capability = None
    create_label = "Add"
    export_name = None
    view_tabs = None             # [(label, url_name, icon)] e.g. list / kanban / calendar
    current_tab = None
    summary = None               # callable(qs) -> list of (label, value) shown above the table

    def base_queryset(self):
        return self.model.objects.all()

    def get_filters(self):
        return self.filters

    def filtered_queryset(self):
        params = self.request.GET
        qs = self.scope(self.base_queryset())
        if self.archive_field:
            if params.get("archived") == "1":
                qs = qs.filter(**{self.archive_field: True})
            else:
                qs = qs.filter(**{self.archive_field: False})
        q = params.get("q", "").strip()
        if q and self.search_fields:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        for flt in self.get_filters():
            qs = flt.apply(qs, params, self)
        sort = get_choice(params, "sort", list(self.sort_options), self.default_sort)
        if sort and sort in self.sort_options:
            qs = qs.order_by(*self.sort_options[sort][1])
        return qs.distinct() if q else qs

    def get(self, request, *args, **kwargs):
        export = request.GET.get("export")
        if export in ("csv", "xlsx"):
            if not has_capability(request.user, "data.export"):
                raise PermissionDenied("You do not have permission to export data.")
            return self.export(export)
        return super().get(request, *args, **kwargs)

    def export(self, fmt):
        qs = self.filtered_queryset()
        cols = [c for c in self.columns if c.export]
        headers = [c.label for c in cols]
        rows = [[c.text(obj) for c in cols] for obj in qs]
        name = self.export_name or self.title.lower().replace(" ", "_")
        log_action("export", message=f"{self.title} exported to {fmt.upper()} ({len(rows)} rows)")
        if fmt == "csv":
            return csv_response(name, headers, rows)
        return xlsx_response(name, headers, rows, title=f"{self.title}",
                             subtitle=f"Exported {timezone.localtime():%d-%b-%Y %H:%M}")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = self.filtered_queryset()
        page = Paginator(qs, self.paginate_by).get_page(self.request.GET.get("page"))
        rows = [{"obj": o, "cells": [{"html": c.html(o), "align": c.align, "css": c.css} for c in self.columns]}
                for o in page.object_list]
        user = self.request.user
        ctx.update({
            "title": self.title, "subtitle": self.subtitle, "icon": self.icon,
            "columns": self.columns, "rows": rows, "page": page,
            "filters": [f.context(self.request.GET, self) for f in self.get_filters()],
            "search_enabled": bool(self.search_fields), "search_placeholder": self.search_placeholder,
            "q": self.request.GET.get("q", ""),
            "sort_options": [(k, v[0]) for k, v in self.sort_options.items()],
            "sort": get_choice(self.request.GET, "sort", list(self.sort_options), self.default_sort),
            "archivable": bool(self.archive_field), "show_archived": self.request.GET.get("archived") == "1",
            "can_create": bool(self.create_url) and (
                not self.create_capability or has_capability(user, self.create_capability)),
            "create_url": reverse(self.create_url) if self.create_url else None,
            "create_label": self.create_label,
            "can_export": has_capability(user, "data.export"),
            "view_tabs": [(label, reverse(url), icon, url == self.current_tab)
                          for label, url, icon in (self.view_tabs or [])],
            "summary": self.summary(qs) if self.summary else None,
        })
        return ctx


class ScopedObjectMixin(ScopedMixin):
    """Detail / edit pages: a record outside the user's scope returns 404, exactly like a missing one."""

    def get_queryset(self):
        return self.scope(self.model.objects.all())


class CrmCreateView(CapabilityRequiredMixin, CreateView):
    template_name = "crud/form.html"
    title = ""
    success_message = "Saved."
    cancel_url = None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        for key, value in self.request.GET.items():
            if key in getattr(self.get_form_class(), "prefill_fields", ()):
                initial[key] = value
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message.format(obj=self.object))
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = self.title
        ctx["cancel_url"] = self.request.GET.get("next") if _safe_next(self.request.GET.get("next")) else (
            reverse(self.cancel_url) if self.cancel_url else None)
        return ctx

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        return nxt if _safe_next(nxt) else self.object.get_absolute_url()


class CrmUpdateView(CapabilityRequiredMixin, ScopedObjectMixin, UpdateView):
    template_name = "crud/form.html"
    title = ""
    success_message = "Changes saved."

    def can_edit(self, obj):
        return True

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not self.can_edit(obj):
            raise PermissionDenied(getattr(self, "locked_message", "This record cannot be edited."))
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message.format(obj=self.object))
        return response

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["title"] = self.title.format(obj=self.object) if self.title else f"Edit {self.object}"
        ctx["cancel_url"] = self.object.get_absolute_url()
        return ctx


class CrmDeleteView(CapabilityRequiredMixin, ScopedObjectMixin, DeleteView):
    template_name = "crud/confirm_delete.html"
    success_url_name = None

    def can_delete(self, obj):
        return True

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not self.can_delete(obj):
            raise PermissionDenied("This record cannot be deleted.")
        return obj

    def form_valid(self, form):
        obj = self.get_object()
        label = str(obj)
        try:
            obj.delete()
        except ProtectedError:
            messages.error(self.request, f"{label} is linked to other records and cannot be deleted. "
                                         "Archive it instead.")
            return redirect(obj.get_absolute_url())
        messages.success(self.request, f"{label} deleted.")
        return redirect(reverse(self.success_url_name))


def _safe_next(url):
    return bool(url) and url.startswith("/") and not url.startswith("//")


def safe_next(request, fallback):
    nxt = request.POST.get("next") or request.GET.get("next")
    return nxt if _safe_next(nxt) else fallback


def get_scoped_or_404(model, user, pk, owner_fields):
    obj = scope_queryset(model.objects.all(), user, owner_fields).filter(pk=pk).first()
    if obj is None:
        raise Http404
    return obj
