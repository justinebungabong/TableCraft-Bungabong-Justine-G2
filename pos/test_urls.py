"""URLconf used only by the error-page tests.

Adds a view that always raises so the 500 handler can be exercised without
introducing a real failure path into the application.
"""

from django.urls import path

from tablecraft.urls import urlpatterns as base_urlpatterns


def boom(request):
    raise ValueError("secret-detail should never be rendered")


urlpatterns = base_urlpatterns + [path("boom/", boom)]
