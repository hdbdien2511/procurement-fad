from datetime import date
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.accounts import roles as R
from apps.budget.ledger import post
from apps.budget.models import ORIGINAL, BudgetLine, CostCode, Location, Project
from apps.workflow import resolver
from apps.workflow.engine import act
from tests.factories import UserFactory
from tests.workflow.conftest import grant, in_budget_policy, org, past, requester  # noqa: F401  (fixtures)

QUOTE_REASON = "Chỉ có một nhà cung cấp độc quyền"
TODAY = "2026-11-27 10:00:00+07:00"  # số tờ trình theo năm, tỷ giá theo ngày nộp


@pytest.fixture(autouse=True)
def frozen_today():
    with freeze_time(TODAY, tick=True):
        yield


@pytest.fixture
def budget(org):
    """Dòng ngân sách 2026 do ITD quản lý, ngân sách gốc 200tr (tháng 1)."""
    cc = CostCode.objects.create(code="IT_1.1", name="Thiết bị CNTT", budget_unit=org.bu_itd)
    pj = Project.objects.create(code="BAU_ITD", name="BAU ITD", begin_year=2026, budget_unit=org.bu_itd)
    loc = Location.objects.create(code="HSC", name="TP.HCM")
    line = BudgetLine.objects.create(year=2026, budget_unit=org.bu_itd, cost_code=cc, project=pj, location=loc)
    fad_admin = grant(UserFactory(username="fad_admin"), R.FAD_BUDGET_ADMIN)
    post(line, date(2026, 1, 1), ORIGINAL, Decimal("200000000"), source=None, user=fad_admin)
    b = type("Budget", (), {})()
    b.line, b.admin, b.cost_code = line, fad_admin, cc
    return b


def make_requisition(org, line, amount, *, currency="VND", quote_reason=QUOTE_REASON, funding=None,
                     service_start=date(2026, 1, 1), months=1, requester=None, created_by=None, **extra):
    """Tờ trình nháp một dòng hàng `amount` (đã gồm VAT 0%), phân bổ toàn bộ vào `line`."""
    from apps.requisitions.models import Requisition, RequisitionFunding, RequisitionLine

    req = Requisition.objects.create(
        title="Mua máy tính", requester=requester or org.requester,
        procurement_type="BAU", necessity="Thay thế máy hỏng", currency=currency,
        service_start=service_start, months=months, quote_exception_reason=quote_reason,
        created_by=created_by or requester or org.requester, **extra,
    )
    RequisitionLine.objects.create(
        requisition=req, description="Máy tính", quantity=Decimal("1"), unit_price=Decimal(amount),
        vat_rate=Decimal("0"),
    )
    if line is not None:
        RequisitionFunding.objects.create(
            requisition=req, budget_line=line, amount_vnd=Decimal(funding if funding is not None else amount)
        )
    return req


def approve_all(instance):
    """Chấp thuận lần lượt mọi bước bắt buộc đang chờ bằng một người xử lý hợp lệ."""
    while True:
        task = instance.tasks.filter(status="PENDING", mandatory=True).order_by("seq", "pk").first()
        if task is None:
            break
        task.instance = instance
        act(task, resolver.candidates(task).order_by("pk").first(), "APPROVE")
        instance.refresh_from_db()
    return instance


def pending_task(instance):
    task = instance.tasks.filter(status="PENDING", mandatory=True).order_by("seq", "pk").first()
    task.instance = instance
    return task


@pytest.fixture
def draft_req(org, budget, in_budget_policy):
    return make_requisition(org, budget.line, 50_000_000, quote_reason="")


@pytest.fixture
def ready_req(org, budget, in_budget_policy):
    return make_requisition(org, budget.line, 50_000_000)


@pytest.fixture
def submitted_req(ready_req, requester):
    from apps.requisitions.services import submit

    submit(ready_req, requester)
    ready_req.refresh_from_db()
    return ready_req


@pytest.fixture
def approved_req(submitted_req):
    approve_all(submitted_req.workflow_instances().get())
    submitted_req.refresh_from_db()
    return submitted_req


@pytest.fixture
def returned_req(submitted_req):
    instance = submitted_req.workflow_instances().get()
    act(pending_task(instance), resolver.candidates(pending_task(instance)).first(), "RETURN", "Bổ sung báo giá")
    submitted_req.refresh_from_db()
    return submitted_req
