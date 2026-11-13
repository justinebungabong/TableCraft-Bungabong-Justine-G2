from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

app_name = "accounts"

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("signup/", views.signup_view, name="signup"),
    path("staff/<int:pk>/edit/", views.staff_edit_view, name="staff_edit"),
    path("staff/<int:pk>/toggle-active/", views.staff_toggle_active_view, name="staff_toggle_active"),
    path("profile/", views.profile_view, name="profile"),
]