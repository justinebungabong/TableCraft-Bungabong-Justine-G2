from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

urlpatterns = [
    path("", lambda request: redirect("dashboard:index" if request.user.is_authenticated else "accounts:login"), name="home"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("pos/", include("pos.urls")),
]

# Custom error pages. Django already resolves templates/404.html and
# templates/500.html through these handlers; they are declared explicitly so the
# wiring is visible. DEBUG must be False for either page to be served.
handler404 = "django.views.defaults.page_not_found"
handler500 = "django.views.defaults.server_error"

# Uploaded profile photos are served by Django only while DEBUG is on; static()
# returns an empty list otherwise, so this cannot leak media in production.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
