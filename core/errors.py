from django.http import HttpResponseServerError
from django.shortcuts import render
from django.template import loader


def permission_denied(request, exception=None):
    return render(request, "errors/403.html", status=403)


def not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)


def server_error(request):
    # Rendered without context processors or database access,
    # so the page still shows if the database is unavailable.
    return HttpResponseServerError(loader.get_template("errors/500.html").render({}))
