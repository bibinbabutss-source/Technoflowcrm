from django import template

register = template.Library()


@register.inclusion_tag("documents/_panel_inner.html", takes_context=True)
def documents_panel(context, target):
    from documents.views import panel_context

    request = context.get("request")
    ctx = panel_context(request.user, target) if request and target is not None else None
    return {"panel": ctx, "request": request, "csrf_token": context.get("csrf_token")}
