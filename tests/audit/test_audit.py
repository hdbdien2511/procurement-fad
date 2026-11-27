import io

import django.db
import pytest
from django.core.management import call_command
from django.db import connection, transaction
from django.test import RequestFactory

from apps.audit.middleware import AuditContextMiddleware
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
    with pytest.raises(django.db.ProgrammingError):
        with transaction.atomic():
            AuditEvent.objects.filter(pk=e.pk).update(action="y")
    with pytest.raises(django.db.ProgrammingError):
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


def test_audit_verify_command(db, user):
    record("x", actor=user)
    out = io.StringIO()
    call_command("audit_verify", stdout=out)
    assert "0" in out.getvalue()
