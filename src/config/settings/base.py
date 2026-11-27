import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from csp.constants import NONE, SELF


def env(name, default=None):
    return os.environ.get(name, default)


BASE_DIR = Path(__file__).resolve().parent.parent.parent  # src/

SECRET_KEY = env("SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS", "").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "django_htmx",
    "axes",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "csp",
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.ui",
    "apps.documents",
    "apps.budget",
    "apps.vendors",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "apps.accounts.middleware.RequireMfaMiddleware",
    "apps.audit.middleware.AuditContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", "postgres://procurement:procurement@localhost:5432/procurement"),
        conn_max_age=60,
    )
}

AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "/dang-nhap/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/dang-nhap/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Khoá tạm sau 5 lần đăng nhập sai trong 15 phút
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/locked.html"

# Entra ID OIDC: chỉ bật khi đủ cả ba biến môi trường
OIDC_RP_CLIENT_ID = env("OIDC_RP_CLIENT_ID")
OIDC_RP_CLIENT_SECRET = env("OIDC_RP_CLIENT_SECRET")
OIDC_OP_TENANT_ID = env("OIDC_OP_TENANT_ID")
OIDC_ENABLED = bool(OIDC_RP_CLIENT_ID and OIDC_RP_CLIENT_SECRET and OIDC_OP_TENANT_ID)
if OIDC_ENABLED:
    _entra = f"https://login.microsoftonline.com/{OIDC_OP_TENANT_ID}"
    OIDC_OP_AUTHORIZATION_ENDPOINT = f"{_entra}/oauth2/v2.0/authorize"
    OIDC_OP_TOKEN_ENDPOINT = f"{_entra}/oauth2/v2.0/token"
    OIDC_OP_JWKS_ENDPOINT = f"{_entra}/discovery/v2.0/keys"
    OIDC_OP_USER_ENDPOINT = "https://graph.microsoft.com/oidc/userinfo"
    OIDC_RP_SIGN_ALGO = "RS256"
    OIDC_RP_SCOPES = "openid email profile"
    OIDC_CREATE_USER = False
    AUTHENTICATION_BACKENDS.insert(1, "apps.accounts.auth.EntraOIDCBackend")

LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR.parent / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").is_dir() else []
MEDIA_ROOT = BASE_DIR.parent / "media"

# Phiên hết hạn sau 1800 giây không thao tác
SESSION_COOKIE_AGE = 1800
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# django-csp 4.x: không script/style inline, không CDN
CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": [SELF],
        "script-src": [SELF],
        "style-src": [SELF],
        "img-src": [SELF, "data:"],
        "object-src": [NONE],
        "base-uri": [SELF],
        "form-action": [SELF],
        "frame-ancestors": [NONE],
    }
}

APP_ENCRYPTION_KEY = env("APP_ENCRYPTION_KEY")
TRUSTED_PROXY_COUNT = int(env("TRUSTED_PROXY_COUNT", "0"))
