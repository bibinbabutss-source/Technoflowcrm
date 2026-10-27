from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.CrmLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),  # POST only
    path("password/change/", views.CrmPasswordChangeView.as_view(), name="password_change"),
    path("password/reset/", auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset.html",
        email_template_name="accounts/email/password_reset.txt",
        subject_template_name="accounts/email/password_reset_subject.txt",
        success_url=reverse_lazy("accounts:password_reset_done"),
    ), name="password_reset"),
    path("password/reset/sent/", auth_views.PasswordResetDoneView.as_view(
        template_name="accounts/password_reset_done.html"), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.CrmPasswordResetConfirmView.as_view(),
         name="password_reset_confirm"),
    path("password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(
        template_name="accounts/password_reset_complete.html"), name="password_reset_complete"),
    path("profile/", views.my_profile, name="my_profile"),
    path("login/verify/", views.mfa_verify, name="mfa_verify"),
    path("profile/two-step/", views.mfa_setup, name="mfa_setup"),
    path("users/<int:pk>/reset-two-step/", views.user_mfa_reset, name="user_mfa_reset"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/login-history/", views.login_history, name="login_history"),
    path("users/<int:pk>/", views.user_detail, name="user_detail"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/toggle-active/", views.user_toggle_active, name="user_toggle_active"),
    path("users/<int:pk>/unlock/", views.user_unlock, name="user_unlock"),
    path("users/<int:pk>/reset-password/", views.user_reset_password, name="user_reset_password"),
    path("roles/", views.role_list, name="role_list"),
    path("roles/<int:pk>/", views.role_edit, name="role_edit"),
]
