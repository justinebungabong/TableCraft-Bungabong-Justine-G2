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

# Uploaded profile photos are served by Django only while DEBUG is on; static()
# returns an empty list otherwise, so this cannot leak media in production.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
