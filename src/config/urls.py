"""Route tiếng Việt của toàn hệ thống (xem các `urls.py` của từng app)."""

from django.conf import settings
from django.urls import include, path

from apps.core.views import healthz
from apps.workflow.admin import site as policy_admin_site

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("quan-tri/", policy_admin_site.urls),
    path("", include("apps.accounts.urls")),
    path("", include("apps.core.urls")),
    path("", include("apps.workflow.urls")),
    path("", include("apps.requisitions.urls")),
    path("", include("apps.budget.urls")),
    path("", include("apps.budget_changes.urls")),
    path("", include("apps.vendors.urls")),
    path("", include("apps.documents.urls")),
    path("", include("apps.notifications.urls")),
    path("", include("apps.audit.urls")),
]

if settings.OIDC_ENABLED:
    urlpatterns.append(path("oidc/", include("mozilla_django_oidc.urls")))
