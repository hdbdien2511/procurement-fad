from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.audit.models import AuditEvent
from apps.budget.ledger import InsufficientBudget, balance, post, reserve
from apps.budget.models import ADJUST, RELEASE, RESERVE, BudgetEntry
from apps.documents.models import QUOTE, Document
from apps.notifications.models import Notification
from apps.requisitions.models import Requisition
from apps.requisitions.services import (
    RequisitionError,
    cancel,
    copy_as_new,
    retry_reserve,
    revise,
    submit,
)
from apps.workflow import resolver
from apps.workflow.engine import act
from apps.workflow.models import CANCELLED, SKIPPED
from tests.factories import UserFactory
from tests.requisitions.conftest import approve_all, make_requisition, pending_task
from tests.testapp.models import Dummy


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
    instance = submitted_req.workflow_instances().get()
    owner_task = instance.tasks.get(kind="BUDGET_OWNER")
    assert submitted_req.visible_to(org.requester)
    assert submitted_req.visible_to(org.dept_head)          # cùng phòng
    assert submitted_req.visible_to(org.owner_itd)          # đơn vị quản lý ngân sách / người xử lý
    assert submitted_req.visible_to(org.fad)                # FAD
    assert submitted_req.visible_to(budget.admin)
    assert not submitted_req.visible_to(org.owner_adm)
    assert not submitted_req.visible_to(org.consultant)
    outsider = UserFactory(username="outsider", org_unit=org.itd)  # thuộc đơn vị quản lý ngân sách
    assert submitted_req.visible_to(outsider)
    assert owner_task.status == "PENDING"


def test_requisition_number_unique_per_version(db, submitted_req):
    from django.db import IntegrityError, transaction

    with transaction.atomic(), pytest.raises(IntegrityError):
        Requisition.objects.create(
            number=submitted_req.number, version=1, title="x", requester=submitted_req.requester,
            requester_unit=submitted_req.requester_unit, procurement_type="BAU", service_start=date(2026, 1, 1),
            created_by=submitted_req.requester,
        )
