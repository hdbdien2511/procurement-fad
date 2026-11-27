"""Thời hạn xử lý, nhắc hạn, quá hạn, chuyển cấp và thông báo khi mở bước / kết thúc hồ sơ."""

import threading
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts import roles as R
from apps.audit.models import AuditEvent
from apps.notifications.models import Notification, Outbox
from apps.workflow import delegation as D
from apps.workflow.engine import act, start
from apps.workflow.models import ApprovalPolicy, PolicyRule, RuleStep, WorkflowTask
from apps.workflow.sla import SlaReport, process_sla
from tests.factories import UserFactory
from tests.workflow.conftest import grant, task_of


def emails(template, to=None):
    rows = Outbox.objects.filter(payload__template_code=template).order_by("id")
    if to is not None:
        rows = [r for r in rows if r.payload["to"] == [to.email]]
    return list(rows)


def recipients(template):
    return sorted(r.payload["to"][0] for r in emails(template))


def local_fmt(dt):
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M")


@pytest.fixture
def escalation_policy(db, past):
    """Một bước duyệt Trưởng đơn vị, SLA 30 giờ, quá hạn chuyển cấp GDĐH."""
    policy = ApprovalPolicy.objects.create(code="SLA", subject_kind="requisition", version=1, effective_from=past)
    rule = PolicyRule.objects.create(policy=policy, priority=1, label="mọi hồ sơ")
    RuleStep.objects.create(rule=rule, seq=1, kind="APPROVE", role_code=R.DEPT_HEAD, scope="REQUESTER_UNIT",
                            sla_hours=30, escalate_role_code=R.GDDH)
    return policy


# --- hạn xử lý và thông báo khi mở bước --------------------------------------------------------------

def test_due_at_set_from_snapshot_sla(db, running_instance, org):
    for task in running_instance.tasks.filter(status="PENDING"):
        assert task.due_at == task.opened_at + timedelta(hours=48)
    assert task_of(running_instance, "FAD_PRECHECK").due_at is None


def test_zero_sla_means_no_due_at(db, past, make_req, org):
    policy = ApprovalPolicy.objects.create(code="NOSLA", subject_kind="requisition", version=1, effective_from=past)
    rule = PolicyRule.objects.create(policy=policy, priority=1, label="mọi hồ sơ")
    RuleStep.objects.create(rule=rule, seq=1, kind="APPROVE", role_code=R.DEPT_HEAD, scope="REQUESTER_UNIT",
                            sla_hours=0)
    inst = start(make_req(1_000_000), "requisition", org.requester)
    task = task_of(inst, "APPROVE")
    assert task.status == "PENDING" and task.due_at is None
    assert emails("OFFICIAL")[0].payload["context"]["han_xu_ly"] == ""


def test_open_notifies_candidates_with_official(db, running_instance, req_two_units, org):
    assert recipients("OFFICIAL") == sorted([org.owner_itd.email, org.owner_adm.email])
    assert emails("CONSULT") == []  # tham vấn chưa đến lượt
    itd = task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd)
    mail = emails("OFFICIAL", org.owner_itd)[0]
    ctx = mail.payload["context"]
    assert ctx["ho_so"] == str(req_two_units)
    assert ctx["han_xu_ly"] == local_fmt(itd.due_at)
    assert ctx["duong_dan"].endswith(f"/viec/{itd.pk}/")
    assert ctx["nguoi_nhan"] == org.owner_itd.get_username()
    assert Notification.objects.filter(user=org.owner_itd, url=f"/viec/{itd.pk}/").count() == 1
    assert not Notification.objects.filter(user=org.fad).exists()


def test_advisory_task_sends_consult_and_finish_sends_result(db, running_instance, org):
    act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd), org.owner_itd, "APPROVE")
    act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.adm), org.owner_adm, "APPROVE")
    assert recipients("CONSULT") == [org.consultant.email]
    assert len(emails("OFFICIAL", org.fad)) == 1
    act(task_of(running_instance, "FAD_PRECHECK"), org.fad, "APPROVE")
    assert emails("RESULT") == []
    act(task_of(running_instance, "APPROVE"), org.dept_head, "APPROVE")
    result = emails("RESULT")
    assert [r.payload["to"] for r in result] == [[org.requester.email]]
    assert result[0].payload["context"]["ket_qua"] == "Đã duyệt"


def test_return_sends_result(db, running_instance, org):
    act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd), org.owner_itd, "RETURN", "Bổ sung báo giá")
    assert emails("RESULT")[0].payload["context"]["ket_qua"] == "Trả lại bổ sung"


def test_open_notifies_valid_delegates(db, in_budget_policy, make_req, org):
    today = timezone.localdate()
    deputy = UserFactory(username="deputy")
    other = UserFactory(username="other")
    D.create_delegation(org.owner_itd, deputy, start_date=today, end_date=today)
    D.create_delegation(org.owner_itd, other, start_date=today, end_date=today, max_amount_vnd=Decimal(1))
    start(make_req(100_000_000), "requisition", org.requester)
    assert recipients("OFFICIAL") == sorted([org.owner_itd.email, org.owner_adm.email, deputy.email])


def test_notifications_rolled_back_with_failed_start(db, past, make_req, org):
    from apps.workflow.engine import NoApprover

    policy = ApprovalPolicy.objects.create(code="EMPTY", subject_kind="requisition", version=1, effective_from=past)
    rule = PolicyRule.objects.create(policy=policy, priority=1, label="mọi hồ sơ")
    RuleStep.objects.create(rule=rule, seq=1, kind="BUDGET_OWNER", role_code=R.BUDGET_OWNER, scope="BUDGET_UNIT",
                            sla_hours=8)
    with pytest.raises(NoApprover):
        start(make_req(1_000_000, budget_units=[]), "requisition", org.requester)
    assert Outbox.objects.count() == 0 and Notification.objects.count() == 0


# --- process_sla --------------------------------------------------------------------------------

@pytest.fixture
def frozen():
    with freeze_time(timezone.now()) as f:
        yield f


@pytest.fixture
def sla_task(escalation_policy, make_req, org, frozen):
    """Bước duyệt mở lúc T0 (đồng hồ đóng băng), hạn T0 + 30 giờ."""
    inst = start(make_req(1_000_000), "requisition", org.requester)
    return task_of(inst, "APPROVE")


def run_sla(frozen, hours):
    frozen.tick(timedelta(hours=hours))
    return process_sla(timezone.now())


def test_reminder_overdue_escalation_each_sent_once(db, sla_task, org, frozen):
    gddh2 = grant(UserFactory(username="gddh2"), R.GDDH)
    assert sla_task.due_at == timezone.now() + timedelta(hours=30)
    assert process_sla(timezone.now()) == SlaReport(0, 0, 0)  # còn 30 giờ
    assert run_sla(frozen, 5) == SlaReport(0, 0, 0)  # còn 25 giờ

    assert run_sla(frozen, 2) == SlaReport(reminded=1, overdue=0, escalated=0)  # còn 23 giờ
    assert run_sla(frozen, 0) == SlaReport(0, 0, 0)
    assert recipients("REMINDER") == [org.dept_head.email]

    assert run_sla(frozen, 24) == SlaReport(0, overdue=1, escalated=0)  # quá hạn 1 giờ
    assert run_sla(frozen, 1) == SlaReport(0, 0, 0)
    assert recipients("OVERDUE") == [org.dept_head.email]

    assert run_sla(frozen, 28) == SlaReport(0, 0, 0)  # đúng hạn + 30 giờ: chưa chuyển cấp
    assert run_sla(frozen, 1) == SlaReport(0, 0, escalated=1)
    assert run_sla(frozen, 0) == SlaReport(0, 0, 0)
    assert recipients("ESCALATION") == sorted([org.gddh.email, gddh2.email])
    ctx = emails("ESCALATION")[0].payload["context"]
    assert ctx["cap_moi"] == R.ROLE_NAMES[R.GDDH] and ctx["han_xu_ly"] == local_fmt(sla_task.due_at)

    assert len(emails("REMINDER")) == len(emails("OVERDUE")) == 1
    sla_task.refresh_from_db()
    assert sla_task.reminded_at and sla_task.overdue_notified_at and sla_task.escalated_at
    assert AuditEvent.objects.filter(action="workflow.task_escalated").count() == 1


def test_overdue_task_gets_no_late_reminder(db, sla_task, org, frozen):
    assert run_sla(frozen, 31) == SlaReport(reminded=0, overdue=1, escalated=0)
    assert emails("REMINDER") == []


def test_reminder_and_overdue_include_delegates(db, sla_task, org, frozen):
    deputy = UserFactory(username="deputy")
    today = timezone.localdate()
    D.create_delegation(org.dept_head, deputy, start_date=today, end_date=today + timedelta(days=5))
    run_sla(frozen, 7)
    assert recipients("REMINDER") == sorted([org.dept_head.email, deputy.email])


def test_no_escalation_without_escalate_role(db, running_instance, frozen):
    assert run_sla(frozen, 48 * 2 + 1) == SlaReport(reminded=0, overdue=2, escalated=0)
    assert run_sla(frozen, 1) == SlaReport(0, 0, 0)
    assert emails("ESCALATION") == []


def test_processed_tasks_ignored(db, sla_task, org, frozen):
    act(sla_task, org.dept_head, "APPROVE")
    assert run_sla(frozen, 100) == SlaReport(0, 0, 0)


@pytest.mark.django_db(transaction=True)
def test_locked_task_skipped_until_free(escalation_policy, make_req, org):
    inst = start(make_req(1_000_000), "requisition", org.requester)
    task = task_of(inst, "APPROVE")
    later = task.due_at + timedelta(hours=1)
    locked, release = threading.Event(), threading.Event()

    def holder():
        try:
            with transaction.atomic():
                WorkflowTask.objects.select_for_update().get(pk=task.pk)
                locked.set()
                release.wait(10)
        finally:
            connection.close()

    t = threading.Thread(target=holder)
    t.start()
    locked.wait(10)
    try:
        assert process_sla(later) == SlaReport(0, 0, 0)
    finally:
        release.set()
        t.join()
    assert process_sla(later) == SlaReport(reminded=0, overdue=1, escalated=0)


def test_registered_as_worker_job(settings):
    assert ("apps.workflow.sla.process_sla", 300) in settings.WORKER_PERIODIC_JOBS
