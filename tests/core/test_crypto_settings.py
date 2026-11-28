import pytest
from cryptography.fernet import Fernet

from apps.audit.models import AuditEvent
from apps.core import crypto
from apps.core.models import Setting
from apps.core.services import DEFAULTS, get_setting, set_setting
from tests.factories import UserFactory


def test_encrypt_roundtrip(settings):
    token = crypto.encrypt("mat-khau-smtp")
    assert token != "mat-khau-smtp" and "mat-khau" not in token
    assert crypto.decrypt(token) == "mat-khau-smtp"


def test_decrypt_tampered_raises(settings):
    token = crypto.encrypt("abc")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(token[:-4] + "AAAA")
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt("not-a-token")


def test_decrypt_wrong_key(settings):
    token = crypto.encrypt("abc")
    settings.APP_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(token)


def test_defaults():
    assert DEFAULTS == {
        "split_window_days": 30,
        "annual_fixed_cost_vnd": 0,
        "cumulative_scope": "COMPANY",
        "max_upload_mb": 25,
    }


def test_get_setting_default_and_stored(db):
    assert get_setting("split_window_days") == 30
    assert get_setting("unknown", "x") == "x"
    assert get_setting("unknown") is None
    Setting.objects.create(key="max_upload_mb", value=50)
    assert get_setting("max_upload_mb") == 50
    assert get_setting("max_upload_mb", 1) == 50


def test_set_setting_writes_and_audits(db):
    actor = UserFactory()
    set_setting("split_window_days", 45, actor)
    assert Setting.objects.get(key="split_window_days").value == 45
    ev = AuditEvent.objects.get(action="setting.changed")
    assert ev.actor_id == actor.pk
    assert ev.changes == {"split_window_days": [30, 45]}
    set_setting("split_window_days", 60, actor)
    ev = AuditEvent.objects.filter(action="setting.changed").order_by("-id").first()
    assert ev.changes == {"split_window_days": [45, 60]}
    assert Setting.objects.filter(key="split_window_days").count() == 1


def test_set_setting_rolls_back_with_audit(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("audit fail")

    monkeypatch.setattr("apps.core.services.record", boom)
    with pytest.raises(RuntimeError):
        set_setting("max_upload_mb", 10, UserFactory())
    assert not Setting.objects.filter(key="max_upload_mb").exists()
