from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env


def _required(name):
    value = env(name)
    if not value:
        raise ImproperlyConfigured(f"Thiếu biến môi trường bắt buộc: {name}")
    return value


SECRET_KEY = _required("SECRET_KEY")
ALLOWED_HOSTS = [h.strip() for h in _required("ALLOWED_HOSTS").split(",") if h.strip()]
APP_ENCRYPTION_KEY = _required("APP_ENCRYPTION_KEY")
try:
    Fernet(APP_ENCRYPTION_KEY)
except (ValueError, TypeError) as exc:
    raise ImproperlyConfigured("APP_ENCRYPTION_KEY không phải khoá Fernet hợp lệ.") from exc
_required("DATABASE_URL")  # base.py đọc giá trị này

DEBUG = False

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", "1") == "1"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
