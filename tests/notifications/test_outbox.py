from datetime import timedelta

import pytest
from apps.accounts.roles import SYS_ADMIN, assign
from apps.audit.models import AuditEvent
from apps.core.crypto import decrypt
from apps.notifications import mailer, outbox
from apps.notifications.models import EmailSettings, EmailTemplate, Notification, Outbox
from django.core import mail
from django.core.management import call_command
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from tests.factories import UserFactory
from tests.notifications.jobs import CALLS

PASSWORD = "S3cr3t-smtp-pw!"


@pytest.fixture
def admin_user(db):
    u = UserFactory(username="admin1")
    assign(u, SYS_ADMIN)
    return u


def _login(client, user):
    client.force_login(user)
    s = client.session
    s["auth_method"] = "oidc"  # bỏ qua bước OTP trong kiểm thử view
    s.save()


def _smtp_down(monkeypatch, message="Connection refused"):
    def boom(*a, **kw):
        raise OSError(message)

    monkeypatch.setattr(mailer, "send_now", boom)


# ---------- mẫu email ----------


def test_six_templates_seeded(db):
    codes = set(EmailTemplate.objects.values_list("code", flat=True))
    assert codes == {"OFFICIAL", "CONSULT", "REMINDER", "OVERDUE", "ESCALATION", "RESULT"}
    assert "cần duyệt" in EmailTemplate.objects.get(code="OFFICIAL").subject


def test_render_escapes_html_in_body(db):
    subject, body = mailer.render("OFFICIAL", {"ho_so": "<script>alert(1)</script>", "nguoi_nhan": "An"})
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "cần duyệt" in subject


def test_subject_has_no_newlines(db):
    subject, _ = mailer.render("OFFICIAL", {"ho_so": "A\r\nBcc: x@evil.test", "nguoi_nhan": "An"})
    assert "\n" not in subject and "\r" not in subject


# ---------- cấu hình SMTP ----------


def test_email_settings_singleton(db):
    a = EmailSettings.load()
    b = EmailSettings.load()
    assert a.pk == b.pk == 1
    assert EmailSettings.objects.count() == 1
    assert (a.port, a.use_tls, a.use_ssl, a.timeout_seconds) == (587, True, False, 10)
    EmailSettings(host="x", use_tls=True).save()
    assert EmailSettings.objects.count() == 1


def test_password_stored_encrypted(db):
    s = EmailSettings.load()
    s.set_password(PASSWORD)
    s.save()
    raw = EmailSettings.objects.values_list("password_encrypted", flat=True).get()
    assert raw and raw != PASSWORD and PASSWORD not in raw
    assert decrypt(raw) == PASSWORD


@override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
def test_get_connection_builds_smtp_backend_from_settings(db):
    s = EmailSettings.load()
    s.host, s.port, s.username, s.timeout_seconds = "smtp.test", 2525, "u", 7
    s.set_password(PASSWORD)
    s.save()
    conn = mailer.get_connection()
    assert (conn.host, conn.port, conn.username, conn.password) == ("smtp.test", 2525, "u", PASSWORD)
    assert conn.use_tls is True and conn.use_ssl is False and conn.timeout == 7


def test_get_connection_uses_configured_backend_when_not_smtp(db):
    from django.core.mail.backends.locmem import EmailBackend

    assert isinstance(mailer.get_connection(), EmailBackend)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
def test_smtp_not_configured_raises(db):
    with pytest.raises(mailer.MailerNotConfigured):
        mailer.get_connection()


# ---------- outbox ----------


def test_process_due_sends_and_marks_sent(db):
    ob = outbox.enqueue_email(["a@x.test"], "OFFICIAL", {"ho_so": "HS-1", "nguoi_nhan": "An"})
    assert ob.status == "PENDING" and ob.kind == "EMAIL"
    now = timezone.now()
    assert outbox.process_due(now) == 1
    ob.refresh_from_db()
    assert ob.status == "SENT" and ob.sent_at == now
    assert len(mail.outbox) == 1 and mail.outbox[0].to == ["a@x.test"]
    assert "HS-1" in mail.outbox[0].body
    assert outbox.process_due(now) == 0  # không gửi lại


def test_enqueue_rolls_back_with_business_transaction(db):
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            outbox.enqueue_email(["a@x.test"], "OFFICIAL", {"ho_so": "HS-1"})
            raise RuntimeError("nghiệp vụ lỗi")
    assert Outbox.objects.count() == 0
    assert outbox.process_due(timezone.now()) == 0
    assert mail.outbox == []


def test_not_yet_due_is_skipped(db):
    now = timezone.now()
    ob = outbox.enqueue_email(["a@x.test"], "OFFICIAL", {"ho_so": "HS-1"})
    Outbox.objects.filter(pk=ob.pk).update(next_attempt_at=now + timedelta(minutes=5))
    assert outbox.process_due(now) == 0
    assert mail.outbox == []


def test_failure_backs_off_exponentially_then_fails(db, monkeypatch):
    _smtp_down(monkeypatch)
    ob = outbox.enqueue_email(["a@x.test"], "OFFICIAL", {"ho_so": "HS-1"})
    now = timezone.now()
    for attempt in range(1, 6):
        assert outbox.process_due(now) == 0
        ob.refresh_from_db()
        assert ob.status == "PENDING" and ob.attempts == attempt
        assert ob.next_attempt_at == now + timedelta(minutes=2**attempt)
        assert "Connection refused" in ob.last_error
        now = ob.next_attempt_at
    assert outbox.process_due(now) == 0
    ob.refresh_from_db()
    assert ob.status == "FAILED" and ob.attempts == 6
    assert outbox.process_due(now + timedelta(days=1)) == 0  # FAILED không được thử lại
    ob.refresh_from_db()
    assert ob.attempts == 6


def test_last_error_never_contains_password(db, monkeypatch):
    s = EmailSettings.load()
    s.host = "smtp.test"
    s.set_password(PASSWORD)
    s.save()
    _smtp_down(monkeypatch, message=f"auth failed for password {PASSWORD}")
    ob = outbox.enqueue_email(["a@x.test"], "OFFICIAL", {"ho_so": "HS-1"})
    outbox.process_due(timezone.now())
    ob.refresh_from_db()
    assert PASSWORD not in ob.last_error and ob.last_error


def test_unknown_template_counts_as_failure(db):
    ob = outbox.enqueue_email(["a@x.test"], "NOPE", {})
    assert outbox.process_due(timezone.now()) == 0
    ob.refresh_from_db()
    assert ob.attempts == 1 and ob.status == "PENDING"


# ---------- notify ----------


def test_notify_creates_notification_and_enqueues_email(db):
    u = UserFactory(email="u@x.test")
    outbox.notify(u, "Có hồ sơ cần duyệt", "/ho-so/1/", email_template="OFFICIAL", context={"ho_so": "HS-1"})
    n = Notification.objects.get(user=u)
    assert n.title == "Có hồ sơ cần duyệt" and n.url == "/ho-so/1/" and n.read_at is None
    ob = Outbox.objects.get()
    assert ob.payload["to"] == ["u@x.test"] and ob.payload["template_code"] == "OFFICIAL"
    assert ob.payload["context"]["ho_so"] == "HS-1" and ob.payload["context"]["duong_dan"] == "/ho-so/1/"


def test_notify_skips_email_without_address_or_template(db):
    no_mail = UserFactory(email="")
    outbox.notify(no_mail, "t", "/x/", email_template="OFFICIAL", context={"ho_so": "H"})
    outbox.notify(UserFactory(email="u@x.test"), "t", "/x/")
    assert Notification.objects.count() == 2 and Outbox.objects.count() == 0


def test_mark_read(db):
    u = UserFactory()
    outbox.notify(u, "t", "/x/")
    n = Notification.objects.get()
    outbox.mark_read(n, u)
    n.refresh_from_db()
    assert n.read_at is not None
    first = n.read_at
    outbox.mark_read(n, u)
    n.refresh_from_db()
    assert n.read_at == first
    with pytest.raises(PermissionError):
        outbox.mark_read(n, UserFactory())


# ---------- giao diện cài đặt ----------

URL = "/cai-dat/email/"
TEST_URL = "/cai-dat/email/gui-thu/"
FORM = {"host": "smtp.test", "port": "587", "use_tls": "on", "username": "u", "password": "",
        "from_address": "no-reply@x.test", "timeout_seconds": "10"}


def test_settings_view_forbidden_for_non_admin(client, db):
    _login(client, UserFactory())
    assert client.get(URL).status_code == 403
    assert client.post(URL, FORM).status_code == 403
    assert client.post(TEST_URL).status_code == 403
    assert EmailSettings.objects.count() == 0


def test_settings_view_requires_login(client, db):
    assert client.get(URL).status_code == 302


def test_settings_save_audits_without_password(client, admin_user):
    _login(client, admin_user)
    r = client.post(URL, {**FORM, "password": PASSWORD})
    assert r.status_code == 302
    s = EmailSettings.load()
    assert s.host == "smtp.test" and decrypt(s.password_encrypted) == PASSWORD
    ev = AuditEvent.objects.filter(action="settings.email_changed").latest("id")
    assert ev.changes["host"] == ["", "smtp.test"]
    assert ev.changes["password"] == ["***", "***"]
    assert PASSWORD not in str(ev.changes) and s.password_encrypted not in str(ev.changes)


def test_blank_password_keeps_current_and_not_rendered(client, admin_user):
    _login(client, admin_user)
    client.post(URL, {**FORM, "password": PASSWORD})
    enc_before = EmailSettings.load().password_encrypted
    r = client.post(URL, {**FORM, "host": "smtp2.test", "password": ""})
    assert r.status_code == 302
    s = EmailSettings.load()
    assert s.host == "smtp2.test" and s.password_encrypted == enc_before
    ev = AuditEvent.objects.filter(action="settings.email_changed").latest("id")
    assert "password" not in ev.changes
    page = client.get(URL).content.decode()
    assert PASSWORD not in page and enc_before not in page


def test_tls_and_ssl_together_rejected(client, admin_user):
    _login(client, admin_user)
    r = client.post(URL, {**FORM, "use_ssl": "on"})
    assert r.status_code == 200
    assert EmailSettings.objects.filter(host="smtp.test").count() == 0


def test_send_test_mail_uses_backend_and_current_user_email(client, admin_user):
    _login(client, admin_user)
    r = client.post(TEST_URL)
    assert r.status_code == 302
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [admin_user.email]


def test_send_test_mail_error_hides_password(client, admin_user, monkeypatch):
    s = EmailSettings.load()
    s.host = "smtp.test"
    s.set_password(PASSWORD)
    s.save()
    _smtp_down(monkeypatch, message=f"535 bad login {PASSWORD}")
    _login(client, admin_user)
    r = client.post(TEST_URL, follow=True)
    text = r.content.decode()
    assert PASSWORD not in text
    assert "Gửi thử không thành công" in text


def test_send_test_mail_get_not_allowed(client, admin_user):
    _login(client, admin_user)
    assert client.get(TEST_URL).status_code == 405


# ---------- worker ----------

def test_worker_once_runs_outbox_and_survives_failing_job(db):
    CALLS.clear()
    outbox.enqueue_email(["a@x.test"], "OFFICIAL", {"ho_so": "HS-1"})
    jobs = [
        ("tests.notifications.jobs.bad_job", 30),
        ("apps.notifications.outbox.process_due", 30),
        ("tests.notifications.jobs.good_job", 30),
    ]
    with override_settings(WORKER_PERIODIC_JOBS=jobs):
        call_command("run_worker", "--once")
    assert len(mail.outbox) == 1 and len(CALLS) == 1


def test_default_periodic_jobs_include_outbox(settings):
    assert ("apps.notifications.outbox.process_due", 30) in settings.WORKER_PERIODIC_JOBS
