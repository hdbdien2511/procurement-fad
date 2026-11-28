from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from apps.audit.service import record

AUTH_METHOD_KEY = "auth_method"
AUTH_PASSWORD = "password"
AUTH_OIDC = "oidc"
ENTRA_BACKEND_PATH = "apps.accounts.auth.EntraOIDCBackend"


class EntraOIDCBackend(OIDCAuthenticationBackend):
    """Ánh xạ claim `oid` -> `User.entra_oid`. Không bao giờ tạo người dùng mới."""

    def filter_users_by_claims(self, claims):
        oid = claims.get("oid")
        if not oid:
            return get_user_model().objects.none()
        return get_user_model().objects.filter(entra_oid=oid, is_active=True)

    def get_user(self, user_id):
        user = super().get_user(user_id)
        if user is None or not self.user_can_authenticate(user):
            return None
        return user

    def verify_claims(self, claims):
        tenant = getattr(settings, "OIDC_OP_TENANT_ID", None)
        client_id = getattr(settings, "OIDC_RP_CLIENT_ID", None)
        if not tenant or not client_id or not claims.get("oid"):
            return False
        aud = claims.get("aud")
        aud_ok = client_id in aud if isinstance(aud, (list, tuple)) else aud == client_id
        return (
            claims.get("iss") == f"https://login.microsoftonline.com/{tenant}/v2.0"
            and aud_ok
            and claims.get("tid") == tenant
        )

    def get_userinfo(self, access_token, id_token, payload):
        # `oid` nằm trong id_token (đã xác minh), không chắc có trong userinfo của Graph
        info = super().get_userinfo(access_token, id_token, payload)
        return {**info, **payload}

    def create_user(self, claims):
        return None


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    backend = request.session.get(BACKEND_SESSION_KEY, "") if request is not None else ""
    method = AUTH_OIDC if backend == ENTRA_BACKEND_PATH else AUTH_PASSWORD
    if request is not None:
        request.session[AUTH_METHOD_KEY] = method
    record("auth.login", user, actor=user, changes={"method": method})


@receiver(user_login_failed)
def _on_login_failed(sender, credentials, request=None, **kwargs):
    record("auth.login_failed", changes={"username": (credentials or {}).get("username", "")})


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    if user is not None:
        record("auth.logout", user, actor=user)
