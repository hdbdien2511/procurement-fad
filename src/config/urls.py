from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from apps.core.views import healthz, home

urlpatterns = [
    path("", home, name="home"),
    path("healthz", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("", include("apps.accounts.urls")),
]

if settings.OIDC_ENABLED:
    urlpatterns.append(path("oidc/", include("mozilla_django_oidc.urls")))
