import json

from apps.accounts.models import OrgUnit, User
from apps.accounts.services import sync_hris
from apps.audit.models import AuditEvent
from apps.integrations.fakes import FakeHrisClient


def test_sync_creates_units_and_users(db, fake_hris):
    r = sync_hris(fake_hris)
    assert (r.created, r.updated, r.deactivated) == (4, 0, 0)
    assert OrgUnit.objects.get(code="ADM").parent.code == "KHOI-VH"
    u = User.objects.get(employee_code="E001")
    assert u.org_unit.code == "ADM" and u.entra_oid == "oid-001" and not u.has_usable_password()
    assert User.objects.get(employee_code="E002").entra_oid is None
    assert AuditEvent.objects.filter(action="user.created").count() == 2


def test_sync_is_idempotent_and_audits_updates(db, fake_hris, tmp_path):
    sync_hris(fake_hris)
    assert sync_hris(fake_hris).created == 0
    data = json.loads(fake_hris_path(fake_hris))
    data["employees"][0]["title"] = "Chuyên viên cao cấp"
    p = tmp_path / "h.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    r = sync_hris(FakeHrisClient(p))
    assert (r.created, r.updated, r.deactivated) == (0, 1, 0)
    ev = AuditEvent.objects.get(action="user.updated")
    assert ev.changes["title"] == ["Chuyên viên", "Chuyên viên cao cấp"]


def fake_hris_path(client):
    return json.dumps(client._data)


def test_sync_hris_deactivates_missing(db, fake_hris, tmp_path):
    sync_hris(fake_hris)
    data = json.loads(fake_hris_path(fake_hris))
    data["employees"] = data["employees"][:1]
    p = tmp_path / "h.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    r = sync_hris(FakeHrisClient(p))
    assert r.deactivated == 1
    assert not User.objects.get(employee_code="E002").is_active
    assert User.objects.get(employee_code="E001").is_active
    assert AuditEvent.objects.filter(action="user.deactivated").count() == 1


def test_sync_deactivates_inactive_flag_and_reactivates(db, fake_hris, tmp_path):
    sync_hris(fake_hris)
    data = json.loads(fake_hris_path(fake_hris))
    data["employees"][1]["active"] = False
    p = tmp_path / "h.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    assert sync_hris(FakeHrisClient(p)).deactivated == 1
    assert not User.objects.get(employee_code="E002").is_active
    assert sync_hris(fake_hris).updated == 1
    assert User.objects.get(employee_code="E002").is_active


def test_sync_does_not_touch_users_without_employee_code(db, user, fake_hris):
    sync_hris(fake_hris)
    user.refresh_from_db()
    assert user.is_active


def test_deactivation_deletes_sessions(db, fake_hris, tmp_path, client):
    from django.contrib.sessions.models import Session

    sync_hris(fake_hris)
    client.force_login(User.objects.get(employee_code="E002"))
    assert Session.objects.count() == 1
    data = json.loads(fake_hris_path(fake_hris))
    data["employees"] = data["employees"][:1]
    p = tmp_path / "h.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    sync_hris(FakeHrisClient(p))
    assert Session.objects.count() == 0
