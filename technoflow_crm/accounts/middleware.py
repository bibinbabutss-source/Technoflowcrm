from django.shortcuts import redirect
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Users with a temporary password must change it before using the CRM."""

    ALLOWED = ("accounts:password_change", "accounts:logout")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            profile = getattr(user, "profile", None)
            if profile is not None and profile.must_change_password:
                allowed = {reverse(name) for name in self.ALLOWED}
                if request.path not in allowed and not request.path.startswith("/static/"):
                    return redirect("accounts:password_change")
        return self.get_response(request)
