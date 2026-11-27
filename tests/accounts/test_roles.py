from datetime import date

from apps.accounts.roles import DEPT_HEAD, GDDH, assign, has_role, users_with_role
from apps.accounts.models import Role
from apps.audit.models import AuditEvent


def test_roles_seeded(db):
    assert Role.objects.count() == 13


def test_role_scope_and_validity(db, user, unit_adm, unit_itd):
    assign(user, DEPT_HEAD, unit_adm, valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30))
    assert has_role(user, DEPT_HEAD, unit_adm, on=date(2026, 3, 1))
    assert not has_role(user, DEPT_HEAD, unit_itd, on=date(2026, 3, 1))
    assert not has_role(user, DEPT_HEAD, unit_adm, on=date(2026, 7, 1))
    assert not has_role(user, DEPT_HEAD, unit_adm, on=date(2025, 12, 31))


def test_valid_to_is_inclusive(db, user, unit_adm):
    assign(user, DEPT_HEAD, unit_adm, valid_from=date(2026, 1, 1), valid_to=date(2026, 6, 30))
    assert has_role(user, DEPT_HEAD, unit_adm, on=date(2026, 6, 30))
    assert has_role(user, DEPT_HEAD, unit_adm, on=date(2026, 1, 1))


def test_scoped_assignment_does_not_satisfy_company_wide(db, user, unit_adm):
    assign(user, DEPT_HEAD, unit_adm, valid_from=date(2026, 1, 1))
    assert not has_role(user, DEPT_HEAD, on=date(2026, 3, 1))
    assert not users_with_role(DEPT_HEAD, on=date(2026, 3, 1)).exists()


def test_company_wide_satisfies_any_scope(db, user, unit_adm, unit_itd):
    assign(user, GDDH, None, valid_from=date(2026, 1, 1))
    on = date(2026, 3, 1)
    assert has_role(user, GDDH, on=on)
    assert has_role(user, GDDH, unit_adm, on=on)
    assert has_role(user, GDDH, unit_itd, on=on)
    assert list(users_with_role(GDDH, unit_itd, on=on)) == [user]


def test_users_with_role_scoped_and_inactive_excluded(db, user, unit_adm, unit_itd):
    assign(user, DEPT_HEAD, unit_adm, valid_from=date(2026, 1, 1))
    on = date(2026, 3, 1)
    assert list(users_with_role(DEPT_HEAD, unit_adm, on=on)) == [user]
    assert not users_with_role(DEPT_HEAD, unit_itd, on=on).exists()
    user.is_active = False
    user.save()
    assert not has_role(user, DEPT_HEAD, unit_adm, on=on)
    assert not users_with_role(DEPT_HEAD, unit_adm, on=on).exists()


def test_assign_is_audited(db, user, unit_adm):
    assign(user, DEPT_HEAD, unit_adm, valid_from=date(2026, 1, 1))
    assert AuditEvent.objects.filter(action="role.assigned").count() == 1
