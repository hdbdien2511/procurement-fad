from django.conf import settings

from .context import audit_context


def client_ip(request):
    n = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if n > 0 and xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= n:
            return parts[-n]
    return request.META.get("REMOTE_ADDR") or None


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and not user.is_authenticated:
            user = None
        token = audit_context.set({"user": user, "ip": client_ip(request)})
        try:
            return self.get_response(request)
        finally:
            audit_context.reset(token)
