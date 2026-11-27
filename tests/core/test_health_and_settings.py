import importlib
import sys

import pytest
from cryptography.fernet import Fernet
from django.db import connection


@pytest.mark.django_db
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok", "db": "ok"}


def test_healthz_db_failure(client, monkeypatch):
    def boom():
        raise Exception("db down")

    monkeypatch.setattr(connection, "ensure_connection", boom)
    r = client.get("/healthz")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "db": "error"}


PROD_ENV = {
    "SECRET_KEY": "x" * 60,
    "ALLOWED_HOSTS": "procurement.example.vn",
    "DATABASE_URL": "postgres://u:p@localhost:5432/d",
    "APP_ENCRYPTION_KEY": Fernet.generate_key().decode(),
}


def _load_prod(monkeypatch):
    for k, v in PROD_ENV.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("config.settings.prod", None)
    return importlib.import_module("config.settings.prod")


def test_prod_security_flags(monkeypatch):
    prod = _load_prod(monkeypatch)
    assert prod.DEBUG is False
    assert prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE
    assert prod.SESSION_COOKIE_AGE == 1800 and prod.SESSION_SAVE_EVERY_REQUEST
    assert prod.SECURE_HSTS_SECONDS >= 31536000
    assert prod.X_FRAME_OPTIONS == "DENY"
    assert prod.LANGUAGE_CODE == "vi" and prod.TIME_ZONE == "Asia/Ho_Chi_Minh"


@pytest.mark.parametrize("missing", list(PROD_ENV))
def test_prod_requires_env(monkeypatch, missing):
    from django.core.exceptions import ImproperlyConfigured

    for k, v in PROD_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(missing)
    sys.modules.pop("config.settings.prod", None)
    with pytest.raises(ImproperlyConfigured):
        importlib.import_module("config.settings.prod")


def test_password_min_length_12(settings):
    opts = [v for v in settings.AUTH_PASSWORD_VALIDATORS if v["NAME"].endswith("MinimumLengthValidator")]
    assert opts and opts[0]["OPTIONS"]["min_length"] == 12
    assert settings.AUTH_USER_MODEL == "accounts.User"


def test_prod_rejects_invalid_encryption_key(monkeypatch):
    from django.core.exceptions import ImproperlyConfigured

    for k, v in PROD_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("APP_ENCRYPTION_KEY", "k" * 44)
    sys.modules.pop("config.settings.prod", None)
    with pytest.raises(ImproperlyConfigured):
        importlib.import_module("config.settings.prod")
