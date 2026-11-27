"""Bối cảnh dùng chung cho kiểm thử màn hình nghiệp vụ (tái dùng fixture của workflow/requisitions)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from apps.accounts.auth import AUTH_METHOD_KEY, AUTH_OIDC
from apps.budget_changes.models import SUPPLEMENT, BudgetChangeRequest
from apps.requisitions.services import submit
from apps.workflow import delegation as delegation_service
from apps.workflow import resolver
from apps.workflow.engine import act
from apps.workflow.models import FAD_PRECHECK as FAD_STEP_KIND
from tests.requisitions.conftest import (  # noqa: F401  (fixtures)
    approved_req,
    budget,
    frozen_today,
    make_requisition,
    ready_req,
    submitted_req,
)
from tests.workflow.conftest import grant, in_budget_policy, org, past, requester  # noqa: F401  (fixtures)


def login(client, user):
    """Đăng nhập bỏ qua TOTP: `force_login` + đánh dấu phiên là phiên OIDC (xem RequireMfaMiddleware)."""
    client.force_login(user)
    session = client.session
    session[AUTH_METHOD_KEY] = AUTH_OIDC
    session.save()


def advance_to_fad(instance):
    """Chấp thuận lần lượt các bước bắt buộc cho tới khi bước FAD tiền kiểm đang chờ; trả bước đó."""
    while True:
        task = instance.tasks.filter(status="PENDING", mandatory=True).order_by("seq", "pk").first()
        if task is None or task.kind == FAD_STEP_KIND:
            if task is not None:
                task.instance = instance
            return task
        task.instance = instance
        act(task, resolver.candidates(task).order_by("pk").first(), "APPROVE")
        instance.refresh_from_db()


@pytest.fixture
def scene(org, budget, in_budget_policy, requester):
    """Một tờ trình nháp, một tờ trình đang chờ FAD tiền kiểm, một đề nghị ngân sách, một uỷ quyền."""
    s = type("Scene", (), {})()
    s.org, s.budget = org, budget
    s.draft = make_requisition(org, budget.line, 20_000_000)
    s.submitted = make_requisition(org, budget.line, 50_000_000)
    submit(s.submitted, requester)
    s.submitted.refresh_from_db()
    s.fad_task = advance_to_fad(s.submitted.workflow_instances().get())
    s.bcr = BudgetChangeRequest.objects.create(
        kind=SUPPLEMENT, to_line=budget.line, amount_vnd=Decimal("10000000"),
        start=date(2026, 1, 1), months=1, reason="Thiếu ngân sách",
        requester=requester, created_by=requester,
    )
    today = date(2026, 11, 27)
    s.delegation = delegation_service.create_delegation(
        requester, org.dept_head, start_date=today, end_date=today + timedelta(days=7)
    )
    return s
