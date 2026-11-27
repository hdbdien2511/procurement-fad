from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection

from apps.accounts import roles as R
from apps.audit.models import AuditEvent
from apps.budget.ledger import InsufficientBudget, balance, post, reserve
from apps.budget.models import ADJUST, RELEASE, RESERVE, BudgetEntry
from apps.documents.models import QUOTE, Document
from apps.notifications.models import Notification
from apps.requisitions.models import Requisition, RequisitionFunding
from apps.requisitions.services import (
    RequisitionError,
    cancel,
    copy_as_new,
    retry_reserve,
    revise,
    submit,
)
from apps.workflow import resolver
from apps.workflow.engine import NotAllowed, act
from apps.workflow.models import CANCELLED, SKIPPED
from tests.factories import UserFactory
from tests.requisitions.conftest import approve_all, make_requisition, pending_task
from tests.testapp.models import Dummy
from tests.workflow.conftest import grant


def reserved_entries(req):
    return list(
        BudgetEntry.objects.filter(source_type="requisitions.requisition", source_id=str(req.pk), kind=RESERVE)
        .order_by("period")
        .values_list("period", "amount")
    )


@pytest.fixture
def approved_req_12_months(org, budget, in_budget_policy, requester):
    req = make_requisition(org, budget.line, 120_000_000, months=12)
    instance = submit(req, requester)
    approve_all(instance)
    req.refresh_from_db()
    return req


def test_approval_reserves_by_allocation(db, approved_req_12_months):
    # 120tr, 12 tháng từ 2026-01 → 12 bút toán RESERVE 10tr
    assert approved_req_12_months.status == "APPROVED"
    assert reserved_entries(approved_req_12_months) == [
        (date(2026, m, 1), Decimal("10000000")) for m in range(1, 13)
    ]
    events = AuditEvent.objects.filter(object_type="requisitions.requisition").order_by("-id")
    actions = list(events.values_list("action", flat=True)[:4])
    # callback: giữ chỗ rồi audit tờ trình; engine ghi audit workflow.* sau cùng
    assert actions == ["workflow.approved", "workflow.task_acted", "requisition.status_changed", "budget.reserved"]


def test_budget_used_up_during_approval_blocks_then_retry(db, submitted_req, budget, org):
    other = Dummy.objects.create(owner=budget.admin)
    reserve([(budget.line, Decimal("180000000"))], start=date(2026, 1, 1), months=1, source=other, user=budget.admin)

    approve_all(submitted_req.workflow_instances().get())
    submitted_req.refresh_from_db()
    assert submitted_req.status == "BUDGET_BLOCKED"
    assert reserved_entries(submitted_req) == []
    notified = set(Notification.objects.filter(title__contains="chưa giữ chỗ").values_list("user__username", flat=True))
    assert {"requester", "fad"} <= notified

    with pytest.raises(RequisitionError):
        retry_reserve(submitted_req, org.requester)
    with pytest.raises(InsufficientBudget):
        retry_reserve(submitted_req, org.fad)

    post(budget.line, date(2026, 1, 1), ADJUST, Decimal("30000000"), source=None, user=budget.admin)
    retry_reserve(submitted_req, budget.admin)
    submitted_req.refresh_from_db()
    assert submitted_req.status == "APPROVED"
    assert reserved_entries(submitted_req) == [(date(2026, 1, 1), Decimal("50000000"))]


def test_returned_status(db, returned_req):
    assert returned_req.status == "RETURNED"


def test_rejected_status(db, submitted_req):
    task = pending_task(submitted_req.workflow_instances().get())
    act(task, resolver.candidates(task).first(), "REJECT", "Không cần thiết")
    submitted_req.refresh_from_db()
    assert submitted_req.status == "REJECTED"


def test_cancel_releases(db, approved_req, requester, budget):
    assert balance(budget.line).reserved == Decimal("50000000")
    with pytest.raises(RequisitionError):
        cancel(approved_req, requester, "Không mua nữa")  # tờ trình đã duyệt: chỉ FAD quản trị ngân sách
    cancel(approved_req, budget.admin, "Không mua nữa")
    approved_req.refresh_from_db()
    assert approved_req.status == "CANCELLED"
    assert balance(budget.line).reserved == 0
    assert BudgetEntry.objects.filter(kind=RELEASE, source_id=str(approved_req.pk)).count() == 1


def test_cancel_requires_reason(db, ready_req, requester):
    with pytest.raises(RequisitionError):
        cancel(ready_req, requester, "  ")
    cancel(ready_req, requester, "Nhập nhầm")
    ready_req.refresh_from_db()
    assert ready_req.status == "CANCELLED"


def test_cancel_in_approval_cancels_workflow(db, submitted_req, requester):
    cancel(submitted_req, requester, "Đổi phương án")
    submitted_req.refresh_from_db()
    instance = submitted_req.workflow_instances().get()
    assert (submitted_req.status, instance.status) == ("CANCELLED", CANCELLED)
    assert set(instance.tasks.values_list("status", flat=True)) == {SKIPPED}
    actions = list(AuditEvent.objects.order_by("-id").values_list("action", flat=True)[:2])
    assert actions == ["requisition.cancelled", "workflow.cancelled"]


def _attach_quote(req, user):
    return Document.objects.create(
        content_type=ContentType.objects.get_for_model(req), object_id=str(req.pk), doc_type=QUOTE,
        original_name="bao-gia.pdf", stored_path="2026/11/abc.pdf", size=10, mime="application/pdf",
        sha256="a" * 64, uploaded_by=user,
    )


def test_revise_creates_new_version_keeps_history(db, returned_req, requester, org):
    returned_req.consult_units.add(org.dti)
    doc = _attach_quote(returned_req, requester)

    new = revise(returned_req, requester)

    assert (new.version, new.previous_id, new.number, new.status) == (2, returned_req.pk, returned_req.number, "DRAFT")
    assert [(f.budget_line_id, f.amount_vnd) for f in new.fundings.all()] == [
        (f.budget_line_id, f.amount_vnd) for f in returned_req.fundings.all()
    ]
    assert new.lines.get().amount == returned_req.lines.get().amount
    assert list(new.consult_units.all()) == [org.dti]
    copied = Document.objects.get(object_id=str(new.pk))
    assert (copied.stored_path, copied.sha256, copied.doc_type) == (doc.stored_path, doc.sha256, QUOTE)
    returned_req.refresh_from_db()
    assert returned_req.status == "RETURNED" and returned_req.lines.count() == 1  # bản cũ giữ nguyên

    with pytest.raises(RequisitionError):
        revise(returned_req, requester)  # đã có phiên bản mới

    submit(new, requester)
    new.refresh_from_db()
    assert (new.number, new.status) == (returned_req.number, "IN_APPROVAL")


def test_copy_as_new(db, returned_req, requester):
    _attach_quote(returned_req, requester)
    copy = copy_as_new(returned_req, requester)
    assert (copy.status, copy.version, copy.number, copy.previous_id) == ("DRAFT", 1, None, None)
    assert copy.lines.count() == 1 and copy.fundings.count() == 1
    assert not Document.objects.filter(object_id=str(copy.pk)).exists()


def test_visible_to(db, submitted_req, org, budget):
    assert submitted_req.visible_to(org.requester)
    assert submitted_req.visible_to(org.dept_head)          # cùng phòng
    assert submitted_req.visible_to(org.owner_itd)          # người xử lý bước BUDGET_OWNER
    assert submitted_req.visible_to(org.fad)                # FAD
    assert submitted_req.visible_to(budget.admin)
    assert not submitted_req.visible_to(org.owner_adm)
    assert not submitted_req.visible_to(org.consultant)
    outsider = UserFactory(username="outsider", org_unit=org.itd)  # thành viên đơn vị quản lý, không có vai trò
    assert not submitted_req.visible_to(outsider)


def test_budget_owner_sees_draft_but_plain_member_does_not(db, ready_req, org):
    member = UserFactory(username="itd_member", org_unit=org.itd)
    assert ready_req.visible_to(org.owner_itd)              # BUDGET_OWNER của đơn vị quản lý (chưa có luồng)
    assert not ready_req.visible_to(member)
    assert not ready_req.visible_to(org.owner_adm)


def test_visible_queryset_matches_object_check(db, submitted_req, ready_req, org, budget):
    users = [org.requester, org.dept_head, org.owner_itd, org.owner_adm, org.consultant, org.fad, org.gddh,
             org.sysadmin, budget.admin, UserFactory(username="itd_member", org_unit=org.itd)]
    for user in users:
        listed = set(Requisition.objects.visible_to(user).values_list("pk", flat=True))
        assert listed == {r.pk for r in (submitted_req, ready_req) if r.visible_to(user)}, user.username
    assert set(Requisition.objects.visible_to(org.owner_itd).values_list("pk", flat=True)) == {
        submitted_req.pk, ready_req.pk
    }
    assert not Requisition.objects.visible_to(org.owner_adm).exists()


def test_delegate_sees_pending_requisition(db, submitted_req, org):
    from apps.workflow.delegation import create_delegation

    deputy = UserFactory(username="deputy")
    assert not submitted_req.visible_to(deputy)
    create_delegation(org.owner_itd, deputy, start_date=date(2026, 11, 1), end_date=date(2026, 12, 31))
    assert submitted_req.visible_to(deputy)


def test_requester_cannot_approve_when_creator_differs(db, org, budget, in_budget_policy):
    # người tạo = requester (DEMO-A), người đề nghị = trưởng phòng DEMO-A (người duyệt bước cuối)
    req = make_requisition(org, budget.line, 50_000_000, requester=org.dept_head, created_by=org.requester)
    instance = submit(req, org.requester)
    for kind in ("BUDGET_OWNER", "FAD_PRECHECK"):
        task = pending_task(instance)
        assert task.kind == kind
        act(task, resolver.candidates(task).first(), "APPROVE")
    task = pending_task(instance)
    assert task.kind == "APPROVE"
    assert not resolver.candidates(task).filter(pk=org.dept_head.pk).exists()
    with pytest.raises(NotAllowed):
        act(task, org.dept_head, "APPROVE")


def test_original_creator_cannot_approve_revised_version(db, org, budget, in_budget_policy):
    owner2 = grant(UserFactory(username="owner_itd_2", org_unit=org.itd), R.BUDGET_OWNER, org.itd)
    v1 = make_requisition(org, budget.line, 50_000_000, created_by=org.owner_itd)  # người đề nghị: requester
    instance = submit(v1, org.requester)
    task = pending_task(instance)
    act(task, owner2, "RETURN", "Bổ sung")
    v2 = revise(v1, org.requester)
    assert v2.created_by == org.requester
    instance2 = submit(v2, org.requester)
    task2 = pending_task(instance2)
    assert task2.kind == "BUDGET_OWNER"
    assert list(resolver.candidates(task2)) == [owner2]
    with pytest.raises(NotAllowed):
        act(task2, org.owner_itd, "APPROVE")


def test_lines_and_fundings_locked_after_submit(db, submitted_req):
    line, funding = submitted_req.lines.get(), submitted_req.fundings.get()
    line.unit_price = Decimal("1")
    with pytest.raises(PermissionError):
        line.save()
    with pytest.raises(PermissionError):
        funding.delete()
    with pytest.raises(PermissionError):
        submitted_req.fundings.update(amount_vnd=1)
    with pytest.raises(PermissionError):
        RequisitionFunding.objects.bulk_create(
            [RequisitionFunding(requisition=submitted_req, budget_line=funding.budget_line, amount_vnd=1)]
        )
    submitted_req.months = 12
    with pytest.raises(PermissionError):
        submitted_req.save()


def test_mismatched_funding_at_approval_blocks_without_reserve(db, submitted_req, budget):
    with connection.cursor() as cur:  # dữ liệu bị sửa ngoài ứng dụng
        cur.execute("UPDATE requisitions_requisitionfunding SET amount_vnd = 1 WHERE requisition_id = %s",
                    [submitted_req.pk])
    approve_all(submitted_req.workflow_instances().get())
    submitted_req.refresh_from_db()
    assert submitted_req.status == "BUDGET_BLOCKED"
    assert reserved_entries(submitted_req) == []
    event = AuditEvent.objects.filter(action="requisition.status_changed").order_by("-id").first()
    assert "khác tổng tờ trình" in event.changes["note"]
    with pytest.raises(RequisitionError):
        retry_reserve(submitted_req, budget.admin)


def test_requisition_number_unique_per_version(db, submitted_req):
    from django.db import IntegrityError, transaction

    with transaction.atomic(), pytest.raises(IntegrityError):
        Requisition.objects.create(
            number=submitted_req.number, version=1, title="x", requester=submitted_req.requester,
            requester_unit=submitted_req.requester_unit, procurement_type="BAU", service_start=date(2026, 1, 1),
            created_by=submitted_req.requester,
        )


# --- đính kèm chứng từ khi hồ sơ đang duyệt (biên bản họp) --------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _png(name="bien-ban.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, PNG, content_type="image/png")


def test_pending_approver_can_attach_while_in_approval(db, submitted_req, org):
    """Bước duyệt đòi chứng từ (biên bản họp) nên người đang xử lý bước phải đính kèm được."""
    from apps.documents.models import MEETING_MINUTES
    from apps.requisitions.services import attach_document

    instance = submitted_req.workflow_instances().get()
    task = instance.tasks.filter(status="PENDING", mandatory=True).order_by("seq", "pk").first()
    task.instance = instance
    approver = resolver.candidates(task).order_by("pk").first()

    doc = attach_document(submitted_req, approver, _png(), MEETING_MINUTES)
    assert doc.doc_type == MEETING_MINUTES and doc.uploaded_by == approver

    outsider = UserFactory(username="nguoi_ngoai_dinh_kem", org_unit=org.dti)
    with pytest.raises(RequisitionError, match="Chỉ người lập hoặc người đề nghị"):
        attach_document(submitted_req, outsider, _png(), MEETING_MINUTES)
