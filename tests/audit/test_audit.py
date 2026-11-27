import io

import django.db
import pytest
from django.core.management import call_command
from django.db import connection, transaction
from django.test import RequestFactory

from apps.audit.middleware import AuditContextMiddleware, client_ip
from apps.audit.models import AuditEvent
from apps.audit.service import diff, record, verify_chain


def test_record_chains_hashes(db, user):
    a = record("requisition.created", actor=user, changes={"x": [None, 1]})
    b = record("requisition.submitted", actor=user)
    assert b.prev_hash == a.hash and len(b.hash) == 64
    assert a.prev_hash == "0" * 64
    assert a.actor_label == "alice"
    assert verify_chain() == []


def test_system_actor_label(db):
    assert record("x").actor_label == "system"


def test_update_and_delete_blocked_by_db(db, user):
    e = record("x", actor=user)
    with pytest.raises(django.db.ProgrammingError, match="append-only"):
        with transaction.atomic():
            AuditEvent.objects.filter(pk=e.pk).update(action="y")
    with pytest.raises(django.db.ProgrammingError, match="append-only"):
        with transaction.atomic():
            AuditEvent.objects.filter(pk=e.pk).delete()


def test_model_save_delete_guard(db, user):
    e = record("x", actor=user)
    with pytest.raises(PermissionError):
        e.save()
    with pytest.raises(PermissionError):
        e.delete()


def test_verify_chain_detects_tampering(db, user):
    e = record("x", actor=user)
    record("y", actor=user)
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        c.execute("ALTER TABLE audit_auditevent DISABLE TRIGGER USER")
        c.execute("UPDATE audit_auditevent SET action='z' WHERE id=%s", [e.pk])
        c.execute("ALTER TABLE audit_auditevent ENABLE TRIGGER USER")
    assert verify_chain() == [e.pk]


def test_diff():
    assert diff({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == {"b": [2, 3], "c": [None, 4]}


def test_record_with_object(db, user):
    e = record("user.updated", user, actor=user)
    assert e.object_type == "accounts.user" and e.object_id == str(user.pk)


def test_middleware_sets_context(db, user):
    seen = {}

    def view(request):
        seen["e"] = record("ctx")
        return None

    req = RequestFactory().get("/", REMOTE_ADDR="10.1.2.3", HTTP_X_FORWARDED_FOR="9.9.9.9")
    req.user = user
    AuditContextMiddleware(view)(req)
    assert seen["e"].actor_id == user.pk and seen["e"].ip == "10.1.2.3"
    after = record("after")
    assert after.actor is None and after.ip is None


def test_audit_verify_command_clean(db, user):
    record("x", actor=user)
    out = io.StringIO()
    call_command("audit_verify", stdout=out)
    assert out.getvalue().strip() == "Số bản ghi lỗi: 0"


def test_audit_verify_command_tampered(db, user):
    e = record("x", actor=user)
    with connection.cursor() as c:
        c.execute("SET CONSTRAINTS ALL IMMEDIATE")
        c.execute("ALTER TABLE audit_auditevent DISABLE TRIGGER USER")
        c.execute("UPDATE audit_auditevent SET action='z' WHERE id=%s", [e.pk])
        c.execute("ALTER TABLE audit_auditevent ENABLE TRIGGER USER")
    out = io.StringIO()
    with pytest.raises(SystemExit) as exc:
        call_command("audit_verify", stdout=out)
    assert exc.value.code == 1
    assert "Số bản ghi lỗi: 1" in out.getvalue()
    assert str(e.pk) in out.getvalue()


@pytest.mark.parametrize(
    "xff,count,expected",
    [
        ("203.0.113.5, 10.0.0.1", 1, "10.0.0.1"),
        ("203.0.113.5, 10.0.0.1", 2, "203.0.113.5"),
        ("203.0.113.5:4567", 1, "10.1.2.3"),
        ("unknown", 1, "10.1.2.3"),
        ("203.0.113.5", 3, "10.1.2.3"),
        ("2001:db8::1", 1, "2001:db8::1"),
    ],
)
def test_client_ip_trusted_proxy(settings, xff, count, expected):
    settings.TRUSTED_PROXY_COUNT = count
    req = RequestFactory().get("/", REMOTE_ADDR="10.1.2.3", HTTP_X_FORWARDED_FOR=xff)
    assert client_ip(req) == expected


def test_client_ip_invalid_remote_addr():
    req = RequestFactory().get("/", REMOTE_ADDR="garbage")
    assert client_ip(req) is None
