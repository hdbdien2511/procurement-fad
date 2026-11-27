from dataclasses import dataclass

from django.contrib.sessions.models import Session
from django.db import transaction

from apps.audit.service import diff, record

from .models import OrgUnit, User


@dataclass
class SyncReport:
    created: int = 0
    updated: int = 0
    deactivated: int = 0


def _snapshot(obj, fields):
    return {f: getattr(obj, f) for f in fields}


def _sync_org_units(client, report):
    rows = client.fetch_org_units()
    fields = ["name", "kind", "is_active"]
    units = {}
    for row in rows:
        unit = OrgUnit.objects.filter(code=row["code"]).first()
        values = {"name": row["name"], "kind": row["kind"], "is_active": True}
        if unit is None:
            unit = OrgUnit.objects.create(code=row["code"], **values)
            record("org_unit.created", unit, changes={"code": row["code"], **values})
            report.created += 1
        else:
            before = _snapshot(unit, fields)
            for k, v in values.items():
                setattr(unit, k, v)
            changes = diff(before, _snapshot(unit, fields))
            if changes:
                unit.save()
                record("org_unit.updated", unit, changes=changes)
                report.updated += 1
        units[row["code"]] = unit
    # cha/con: hai lượt để không phụ thuộc thứ tự dòng
    for row in rows:
        unit = units[row["code"]]
        parent = units.get(row.get("parent_code")) if row.get("parent_code") else None
        if unit.parent_id != (parent.pk if parent else None):
            before = {"parent": unit.parent.code if unit.parent else None}
            unit.parent = parent
            unit.save(update_fields=["parent"])
            record(
                "org_unit.updated",
                unit,
                changes=diff(before, {"parent": parent.code if parent else None}),
            )
    return units


def _drop_sessions(user):
    for session in Session.objects.iterator():
        if session.get_decoded().get("_auth_user_id") == str(user.pk):
            session.delete()


def _deactivate(user, report):
    user.is_active = False
    user.save(update_fields=["is_active"])
    record("user.deactivated", user, changes={"is_active": [True, False]})
    _drop_sessions(user)
    report.deactivated += 1


@transaction.atomic
def sync_hris(client) -> SyncReport:
    """Đồng bộ đơn vị và nhân viên từ HRIS: upsert theo mã, vô hiệu hoá nhân viên không còn."""
    report = SyncReport()
    units = _sync_org_units(client, report)
    fields = ["username", "email", "first_name", "title", "org_unit", "entra_oid", "is_active"]
    seen = set()
    for row in client.fetch_employees():
        code = row["employee_code"]
        seen.add(code)
        values = {
            "username": row["username"],
            "email": row.get("email", ""),
            "first_name": row.get("full_name", ""),
            "title": row.get("title", ""),
            "org_unit": units.get(row.get("org_unit_code")),
            "entra_oid": row.get("entra_oid") or None,
            "is_active": bool(row.get("active", True)),
        }
        user = User.objects.filter(employee_code=code).first()
        if user is None:
            user = User(employee_code=code, **values)
            user.set_unusable_password()
            user.save()
            record(
                "user.created",
                user,
                changes={
                    k: (v.code if k == "org_unit" and v else v) for k, v in values.items()
                },
            )
            report.created += 1
            continue
        was_active = user.is_active
        before = _snapshot(user, fields)
        for k, v in values.items():
            setattr(user, k, v)
        after = _snapshot(user, fields)
        for snap in (before, after):
            snap["org_unit"] = snap["org_unit"].code if snap["org_unit"] else None
        changes = diff(before, after)
        if not changes:
            continue
        user.save()
        if was_active and not user.is_active:
            record("user.deactivated", user, changes={"is_active": [True, False]})
            _drop_sessions(user)
            report.deactivated += 1
        else:
            record("user.updated", user, changes=changes)
            report.updated += 1
    for user in User.objects.filter(employee_code__isnull=False, is_active=True).exclude(
        employee_code__in=seen
    ):
        _deactivate(user, report)
    return report
