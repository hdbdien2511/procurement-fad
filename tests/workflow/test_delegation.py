"""Uỷ quyền duyệt thay (spec 7.2)."""

import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts import roles as R
from apps.audit.models import AuditEvent
from apps.audit.service import verify_chain
from apps.documents.models import DELEGATION_LETTER, QUOTE, Document
from apps.workflow import delegation as D
from apps.workflow.engine import NotAllowed, act, start
from apps.workflow.models import Delegation
from tests.factories import UserFactory
from tests.workflow.conftest import grant, task_of


@pytest.fixture
def today():
    return timezone.localdate()


@pytest.fixture
def deputy(org):
    return UserFactory(username="deputy", first_name="Phó", last_name="Phòng", org_unit=org.itd)


@pytest.fixture
def itd_task(running_instance, org):
    return task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd)


def delegate(delegator, to, today, **kw):
    kw.setdefault("start_date", today - timedelta(days=1))
    kw.setdefault("end_date", today + timedelta(days=1))
    return D.create_delegation(delegator, to, **kw)


def letter(user, doc_type=DELEGATION_LETTER):
    return Document.objects.create(
        content_type=ContentType.objects.get_for_model(user), object_id=str(user.pk), doc_type=doc_type,
        original_name="uy-quyen.pdf", stored_path="x/uy-quyen.pdf", size=1, mime="application/pdf",
        sha256="0" * 64, uploaded_by=user,
    )


# --- duyệt thay hợp lệ ----------------------------------------------------------------------------

def test_delegate_acts_within_period(db, itd_task, org, deputy, today):
    d = delegate(org.owner_itd, deputy, today)
    task = act(itd_task, deputy, "APPROVE")
    assert task.status == "APPROVED" and task.acted_by == deputy and task.on_behalf_of == org.owner_itd
    event = AuditEvent.objects.filter(action="workflow.task_acted").order_by("-id").first()
    assert event.actor == deputy
    assert event.changes["on_behalf_of"] == "owner_itd" and event.changes["delegation_id"] == d.pk
    assert "deputy duyệt thay owner_itd theo uỷ quyền số" in event.changes["note"]
    assert verify_chain() == []


def test_explicit_on_behalf_of_validated(db, itd_task, org, deputy, today):
    delegate(org.owner_itd, deputy, today)
    with pytest.raises(NotAllowed):
        act(itd_task, deputy, "APPROVE", on_behalf_of=org.owner_adm)
    assert act(itd_task, deputy, "APPROVE", on_behalf_of=org.owner_itd).on_behalf_of == org.owner_itd


def test_on_behalf_of_without_delegation_not_allowed(db, itd_task, org):
    with pytest.raises(NotAllowed):
        act(itd_task, org.owner_itd, "APPROVE", on_behalf_of=org.owner_adm)


def test_direct_candidate_wins_over_delegation(db, itd_task, org, today):
    second_owner = grant(UserFactory(org_unit=org.itd), R.BUDGET_OWNER, org.itd)
    delegate(org.owner_itd, second_owner, today)
    task = act(itd_task, second_owner, "APPROVE")
    assert task.acted_by == second_owner and task.on_behalf_of is None


def test_first_delegator_by_pk_when_several(db, itd_task, org, deputy, today):
    second_owner = grant(UserFactory(org_unit=org.itd), R.BUDGET_OWNER, org.itd)
    delegate(second_owner, deputy, today)
    delegate(org.owner_itd, deputy, today)
    expected = min((org.owner_itd, second_owner), key=lambda u: u.pk)
    assert D.can_act_on_behalf(deputy, itd_task) == expected
    assert act(itd_task, deputy, "APPROVE").on_behalf_of == expected


# --- ngoài phạm vi uỷ quyền -----------------------------------------------------------------------

@pytest.mark.parametrize("start_offset,end_offset", [(1, 5), (-5, -1)])
def test_outside_period_not_allowed(db, itd_task, org, deputy, today, start_offset, end_offset):
    delegate(org.owner_itd, deputy, today, start_date=today + timedelta(days=start_offset),
             end_date=today + timedelta(days=end_offset))
    assert D.can_act_on_behalf(deputy, itd_task) is None
    with pytest.raises(NotAllowed):
        act(itd_task, deputy, "APPROVE")


def test_single_day_period_inclusive(db, itd_task, org, deputy, today):
    delegate(org.owner_itd, deputy, today, start_date=today, end_date=today)
    assert D.can_act_on_behalf(deputy, itd_task) == org.owner_itd


def test_amount_above_cap_not_allowed(db, itd_task, org, deputy, today):
    # hồ sơ running_instance: 100.000.000 đ
    delegate(org.owner_itd, deputy, today, max_amount_vnd=Decimal(99_999_999))
    with pytest.raises(NotAllowed):
        act(itd_task, deputy, "APPROVE")


def test_amount_equal_to_cap_allowed(db, itd_task, org, deputy, today):
    delegate(org.owner_itd, deputy, today, max_amount_vnd=Decimal(100_000_000))
    assert act(itd_task, deputy, "APPROVE").on_behalf_of == org.owner_itd


def test_no_chaining(db, itd_task, org, deputy, today):
    c = UserFactory(username="c_user")
    delegate(org.owner_itd, deputy, today)  # A → B
    delegate(deputy, c, today)              # B → C (không được dùng tiếp)
    assert D.can_act_on_behalf(c, itd_task) is None
    with pytest.raises(NotAllowed):
        act(itd_task, c, "APPROVE")
    assert act(itd_task, deputy, "APPROVE").on_behalf_of == org.owner_itd


def test_delegate_who_created_subject_not_allowed(db, in_budget_policy, make_req, org, deputy, today):
    inst = start(make_req(100_000_000, created_by=deputy), "requisition", org.requester)
    task = task_of(inst, "BUDGET_OWNER", org_unit=org.itd)
    delegate(org.owner_itd, deputy, today)
    assert D.can_act_on_behalf(deputy, task) is None
    with pytest.raises(NotAllowed, match="chính mình lập"):
        act(task, deputy, "APPROVE")


def test_delegate_who_submitted_not_allowed(db, itd_task, org, today):
    delegate(org.owner_itd, org.requester, today)
    assert D.can_act_on_behalf(org.requester, itd_task) is None
    with pytest.raises(NotAllowed, match="chính mình lập"):
        act(itd_task, org.requester, "APPROVE")


def test_delegator_who_created_subject_cannot_delegate(db, in_budget_policy, make_req, org, deputy, today):
    creator = grant(UserFactory(org_unit=org.itd), R.BUDGET_OWNER, org.itd)
    inst = start(make_req(100_000_000, created_by=creator), "requisition", org.requester)
    task = task_of(inst, "BUDGET_OWNER", org_unit=org.itd)
    delegate(creator, deputy, today)
    assert D.can_act_on_behalf(deputy, task) is None
    with pytest.raises(NotAllowed):
        act(task, deputy, "APPROVE")


def test_sys_admin_delegate_not_allowed(db, itd_task, org, today):
    delegate(org.owner_itd, org.sysadmin, today)
    assert D.can_act_on_behalf(org.sysadmin, itd_task) is None
    with pytest.raises(NotAllowed, match="Quản trị hệ thống"):
        act(itd_task, org.sysadmin, "APPROVE")


def test_sys_admin_delegator_not_allowed(db, itd_task, org, deputy, today):
    grant(org.owner_itd, R.SYS_ADMIN)
    delegate(org.owner_itd, deputy, today)
    with pytest.raises(NotAllowed):
        act(itd_task, deputy, "APPROVE")


def test_delegator_without_authority_cannot_delegate(db, itd_task, org, deputy, today):
    delegate(org.owner_adm, deputy, today)  # owner_adm không có thẩm quyền ở nhánh ITD
    with pytest.raises(NotAllowed):
        act(itd_task, deputy, "APPROVE")


def test_delegator_authority_checked_at_act_time(db, itd_task, org, deputy, today):
    delegate(org.owner_itd, deputy, today)
    org.owner_itd.is_active = False
    org.owner_itd.save(update_fields=["is_active"])
    with pytest.raises(NotAllowed):
        act(itd_task, deputy, "APPROVE")


def test_subject_kind_scope(db, itd_task, org, deputy, today):
    d = delegate(org.owner_itd, deputy, today, subject_kinds=["budget_change"])
    assert D.can_act_on_behalf(deputy, itd_task) is None
    d.revoke(org.owner_itd)
    delegate(org.owner_itd, deputy, today, subject_kinds=["requisition"])
    assert D.can_act_on_behalf(deputy, itd_task) == org.owner_itd


def test_org_unit_scope(db, itd_task, org, deputy, today):
    delegate(org.owner_itd, deputy, today, org_unit=org.adm)
    assert D.can_act_on_behalf(deputy, itd_task) is None
    delegate(org.owner_itd, deputy, today, org_unit=org.itd)
    assert D.can_act_on_behalf(deputy, itd_task) == org.owner_itd


def test_revoked_not_allowed(db, itd_task, org, deputy, today):
    d = delegate(org.owner_itd, deputy, today)
    d.revoke(org.owner_itd)
    d.refresh_from_db()
    assert d.revoked_at is not None
    assert AuditEvent.objects.filter(action="delegation.revoked", object_id=str(d.pk)).count() == 1
    with pytest.raises(NotAllowed):
        act(itd_task, deputy, "APPROVE")
    with pytest.raises(ValidationError):
        d.revoke(org.owner_itd)


# --- tạo uỷ quyền ---------------------------------------------------------------------------------

def test_active_delegations_for(db, org, deputy, today):
    active = delegate(org.owner_itd, deputy, today)
    delegate(org.owner_adm, deputy, today, start_date=today + timedelta(days=1), end_date=today + timedelta(days=2))
    delegate(org.owner_itd, org.fad, today)
    revoked = delegate(org.owner_adm, deputy, today)
    revoked.revoke(org.owner_adm)
    assert list(D.active_delegations_for(deputy, today)) == [active]
    assert D.active_delegations_for(deputy, today + timedelta(days=1)).count() == 2


def test_create_records_audit(db, org, deputy, today):
    doc = letter(org.owner_itd)
    d = delegate(org.owner_itd, deputy, today, max_amount_vnd=Decimal(50_000_000), org_unit=org.itd,
                 subject_kinds=["requisition"], letter=doc)
    event = AuditEvent.objects.get(action="delegation.created")
    assert event.object_type == "workflow.delegation" and event.object_id == str(d.pk)
    assert event.changes["delegator"] == "owner_itd" and event.changes["delegate"] == "deputy"
    assert event.changes["max_amount_vnd"] == "50000000" and event.changes["org_unit"] == "ITD-DEMO"
    assert event.changes["letter"] == str(doc.pk)


def test_delegate_must_differ_from_delegator(db, org, today):
    with pytest.raises(ValidationError, match="Không thể uỷ quyền cho chính mình"):
        delegate(org.owner_itd, org.owner_itd, today)
    assert Delegation.objects.count() == 0


def test_end_before_start_rejected(db, org, deputy, today):
    with pytest.raises(ValidationError, match="Ngày kết thúc phải từ ngày bắt đầu trở đi"):
        delegate(org.owner_itd, deputy, today, start_date=today, end_date=today - timedelta(days=1))


def test_unknown_subject_kind_rejected(db, org, deputy, today):
    with pytest.raises(ValidationError):
        delegate(org.owner_itd, deputy, today, subject_kinds=["khac"])


def test_letter_must_be_delegation_letter(db, org, deputy, today):
    with pytest.raises(ValidationError, match="Giấy ủy quyền"):
        delegate(org.owner_itd, deputy, today, letter=letter(org.owner_itd, QUOTE))


# --- bất biến và khoá -----------------------------------------------------------------------------

def test_delegation_immutable_except_revoke(db, org, deputy, today):
    d = delegate(org.owner_itd, deputy, today, max_amount_vnd=Decimal(1))
    msg = "Uỷ quyền đã tạo không được sửa"
    d.max_amount_vnd = None
    with pytest.raises(PermissionError, match=msg):
        d.save()
    with pytest.raises(PermissionError, match=msg):
        d.save(update_fields=["max_amount_vnd", "revoked_at"])
    with pytest.raises(PermissionError, match=msg):
        Delegation.objects.filter(pk=d.pk).update(end_date=today + timedelta(days=365))
    d.refresh_from_db()
    assert d.max_amount_vnd == Decimal(1)
    d.revoke(org.owner_itd)
    assert Delegation.objects.get(pk=d.pk).revoked_at is not None


@pytest.mark.django_db(transaction=True)
def test_act_locks_delegation_row(running_instance, org):
    """Trong `act`, dòng uỷ quyền bị khoá tới hết transaction → thu hồi đồng thời phải chờ."""
    from django.db import OperationalError, connection, transaction

    today = timezone.localdate()
    deputy = UserFactory(username="deputy2")
    d = delegate(org.owner_itd, deputy, today)
    task = task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd)
    seen = []

    def try_lock():
        try:
            with transaction.atomic():
                Delegation.objects.select_for_update(nowait=True).get(pk=d.pk)
            seen.append("free")
        except OperationalError:
            seen.append("locked")
        finally:
            connection.close()

    with transaction.atomic():
        assert D.find_delegation(deputy, task, lock=True) == d
        t = threading.Thread(target=try_lock)
        t.start()
        t.join()
    assert seen == ["locked"]
