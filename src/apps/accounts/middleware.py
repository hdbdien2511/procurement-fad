from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from .auth import AUTH_METHOD_KEY, AUTH_OIDC

EXEMPT_PREFIXES = ("/dang-nhap/", "/dang-xuat/", "/xac-thuc-otp/", "/chua-dang-ky-otp/", "/oidc/", "/healthz", "/static/")


class RequireMfaMiddleware:
    """Đăng nhập bằng mật khẩu phải xác thực TOTP; đăng nhập OIDC (Entra) bỏ qua."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and not request.path.startswith(EXEMPT_PREFIXES)
            and request.session.get(AUTH_METHOD_KEY) != AUTH_OIDC
            and not user.is_verified()
        ):
            url = reverse("otp_verify")
            return redirect(f"{url}?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)
