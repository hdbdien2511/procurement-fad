import pytest
from apps.accounts.auth import EntraOIDCBackend
from apps.audit.models import AuditEvent
from django.test import override_settings
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from tests.factories import UserFactory


def _token(device):
    return f"{totp(device.bin_key, device.step, device.t0, device.digits):06d}"


def test_home_requires_login(client, db):
    r = client.get("/")
    assert r.status_code == 302 and r["Location"].startswith("/dang-nhap/")


@override_settings(AXES_ENABLED=True)
def test_lockout_after_5_failures(client, pw_user, password):
    for _ in range(5):
        client.post("/dang-nhap/", {"username": pw_user.username, "password": "sai"})
    r = client.post("/dang-nhap/", {"username": pw_user.username, "password": password})
    assert "tạm khoá" in r.content.decode()
    assert "_auth_user_id" not in client.session


def test_local_login_requires_totp(client, user_with_totp, password):
    r = client.post("/dang-nhap/", {"username": "bob", "password": password})
    assert r.status_code == 302 and r["Location"].startswith("/xac-thuc-otp/")
    r = client.get("/")
    assert r.status_code == 302 and r["Location"].startswith("/xac-thuc-otp/")
    assert client.get("/admin/").status_code == 302


def test_totp_verification_grants_access(client, user_with_totp, password):
    client.post("/dang-nhap/", {"username": "bob", "password": password})
    device = TOTPDevice.objects.get(user=user_with_totp)
    r = client.post("/xac-thuc-otp/", {"token": _token(device), "next": "/"})
    assert r.status_code == 302 and r["Location"] == "/"
    assert client.get("/").status_code == 200


def test_wrong_totp_rejected(client, user_with_totp, password):
    client.post("/dang-nhap/", {"username": "bob", "password": password})
    r = client.post("/xac-thuc-otp/", {"token": "000000", "next": "/"})
    assert r.status_code == 200 and "không đúng" in r.content.decode()
    assert client.get("/").status_code == 302


def test_otp_next_open_redirect_blocked(client, user_with_totp, password):
    client.post("/dang-nhap/", {"username": "bob", "password": password})
    device = TOTPDevice.objects.get(user=user_with_totp)
    r = client.post("/xac-thuc-otp/", {"token": _token(device), "next": "https://evil.test/"})
    assert r["Location"] == "/"


def test_user_without_device_sees_enroll_notice(client, pw_user, password):
    client.post("/dang-nhap/", {"username": "bob", "password": password})
    r = client.get("/xac-thuc-otp/")
    assert r["Location"] == "/chua-dang-ky-otp/"
    assert "quản trị viên" in client.get("/chua-dang-ky-otp/").content.decode()
    assert client.get("/").status_code == 302


def test_oidc_session_skips_totp(client, pw_user):
    client.force_login(pw_user)
    session = client.session
    session["auth_method"] = "oidc"
    session.save()
    assert client.get("/").status_code == 200


def test_auth_audit_events(client, user_with_totp, password):
    client.post("/dang-nhap/", {"username": "bob", "password": "sai"})
    client.post("/dang-nhap/", {"username": "bob", "password": password})
    device = TOTPDevice.objects.get(user=user_with_totp)
    client.post("/xac-thuc-otp/", {"token": _token(device), "next": "/"})
    client.post("/dang-xuat/")
    actions = list(AuditEvent.objects.order_by("id").values_list("action", flat=True))
    assert actions == ["auth.login_failed", "auth.login", "auth.otp_verified", "auth.logout"]
    failed = AuditEvent.objects.get(action="auth.login_failed")
    assert failed.changes == {"username": "bob"} and "sai" not in str(failed.changes)


def test_enroll_totp_command(db, pw_user, capsys):
    from django.core.management import call_command

    call_command("enroll_totp", "bob")
    assert capsys.readouterr().out.startswith("otpauth://totp/")
    assert TOTPDevice.objects.filter(user=pw_user, confirmed=True).count() == 1


@pytest.fixture
def oidc_settings(settings):
    settings.OIDC_RP_CLIENT_ID = "id"
    settings.OIDC_RP_CLIENT_SECRET = "secret"
    settings.OIDC_OP_AUTHORIZATION_ENDPOINT = "https://op.test/authorize"
    settings.OIDC_OP_TOKEN_ENDPOINT = "https://op.test/token"
    settings.OIDC_OP_USER_ENDPOINT = "https://op.test/userinfo"
    settings.OIDC_OP_JWKS_ENDPOINT = "https://op.test/jwks"
    settings.OIDC_RP_SIGN_ALGO = "RS256"


@pytest.fixture
def backend(oidc_settings):
    return EntraOIDCBackend()


class TestEntraBackend:

    def test_matches_active_user_by_oid(self, db, backend):
        u = UserFactory(entra_oid="oid-1")
        assert list(backend.filter_users_by_claims({"oid": "oid-1"})) == [u]

    def test_unknown_missing_or_inactive_oid(self, db, backend):
        UserFactory(entra_oid="oid-2", is_active=False)
        for claims in ({"oid": "nope"}, {}, {"oid": "oid-2"}, {"oid": ""}):
            assert not backend.filter_users_by_claims(claims).exists()

    def test_never_creates_user(self, db, backend):
        assert backend.create_user({"oid": "x", "email": "a@b.c"}) is None
