import threading
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.utils import timezone

from apps.accounts import roles as R
from apps.audit.models import AuditEvent
from apps.audit.service import verify_chain
from apps.documents.models import MEETING_MINUTES, Document
from apps.workflow.engine import (
    AlreadyProcessed,
    Misconfigured,
    NoApprover,
    NotAllowed,
    WorkflowError,
    act,
    candidates,
    start,
)
from apps.workflow.models import (
    ApprovalPolicy,
    PolicyRule,
    RuleStep,
    WorkflowInstance,
    WorkflowTask,
)
from tests.factories import UserFactory
from tests.workflow.conftest import first_task, grant, task_of


def statuses(instance, kind):
    return sorted(instance.tasks.filter(kind=kind).values_list("status", flat=True))


def subject_actions(subject):
    ct = ContentType.objects.get_for_model(subject)
    return list(
        AuditEvent.objects.filter(object_type=ct.app_label + "." + ct.model, object_id=str(subject.pk))
        .order_by("id").values_list("action", flat=True)
    )


def approve_budget_owners(instance, org):
    act(task_of(instance, "BUDGET_OWNER", org_unit=org.itd), org.owner_itd, "APPROVE")
    act(task_of(instance, "BUDGET_OWNER", org_unit=org.adm), org.owner_adm, "APPROVE")


def attach_minutes(subject, user):
    return Document.objects.create(
        content_type=ContentType.objects.get_for_model(subject), object_id=str(subject.pk),
        doc_type=MEETING_MINUTES, original_name="bien-ban.pdf", stored_path="x/bien-ban.pdf",
        size=1, mime="application/pdf", sha256="0" * 64, uploaded_by=user,
    )


# --- khởi tạo -----------------------------------------------------------------------------------

def test_parallel_budget_owner_branches(db, req_two_units, requester):
    inst = start(req_two_units, "requisition", requester)
    owner_tasks = inst.tasks.filter(kind="BUDGET_OWNER")
    assert owner_tasks.count() == 2 and set(owner_tasks.values_list("status", flat=True)) == {"PENDING"}


def test_start_resolves_scopes_and_waits_later_seqs(db, running_instance, org):
    inst = running_instance
    assert inst.status == "RUNNING" and inst.rule.label == "<200tr"
    assert set(inst.tasks.filter(kind="BUDGET_OWNER").values_list("org_unit", flat=True)) == {org.itd.pk, org.adm.pk}
    consult = task_of(inst, "CONSULT")
    assert consult.org_unit == org.dti and consult.mandatory is False and consult.status == "WAITING"
    assert task_of(inst, "FAD_PRECHECK").org_unit is None
    assert task_of(inst, "APPROVE").org_unit == org.req_unit
    assert set(inst.tasks.filter(seq__gt=1).values_list("status", flat=True)) == {"WAITING"}


def test_snapshot_contents(db, running_instance, org):
    snap = running_instance.snapshot
    assert snap["policy"] == {"code": "TRONG_NGAN_SACH", "version": 1}
    assert snap["rule"]["label"] == "<200tr" and snap["rule"]["max_amount"] == "199999999"
    assert [s["kind"] for s in snap["steps"]] == ["BUDGET_OWNER", "CONSULT", "FAD_PRECHECK", "APPROVE"]
    assert snap["steps"][3] == {
        "seq": 4, "kind": "APPROVE", "role_code": R.DEPT_HEAD, "scope": "REQUESTER_UNIT",
        "fixed_org_unit_id": None, "mandatory": True, "sla_hours": 48, "escalate_role_code": None,
        "requires_doc_type": None,
    }
    assert snap["context"] == {
        "amount_vnd": "100000000", "budget_unit_ids": [org.bu_itd.pk, org.bu_adm.pk],
        "consult_unit_ids": [org.dti.pk], "requester_unit_id": org.req_unit.pk,
        "created_by_id": org.requester.pk, "cumulative_after_vnd": None,
    }


def test_empty_consult_list_skips_step(db, in_budget_policy, make_req, requester):
    inst = start(make_req(100_000_000, consult=False), "requisition", requester)
    assert not inst.tasks.filter(kind="CONSULT").exists()
    assert inst.snapshot["skipped_steps"] == [{"seq": 2, "kind": "CONSULT", "reason": "Không có đơn vị áp dụng"}]


def test_fixed_unit_scope(db, past, make_req, org):
    policy = ApprovalPolicy.objects.create(code="F", subject_kind="requisition", version=1, effective_from=past)
    rule = PolicyRule.objects.create(policy=policy, priority=1, label="fixed")
    RuleStep.objects.create(rule=rule, seq=1, kind="CONSULT", role_code=R.CONSULTANT, scope="FIXED_UNIT",
                            fixed_org_unit=org.dti, mandatory=True, sla_hours=8)
    inst = start(make_req(1), "requisition", org.requester)
    assert first_task(inst).org_unit == org.dti
    assert list(candidates(first_task(inst))) == [org.consultant]


def test_start_records_audit_on_subject(db, running_instance, req_two_units):
    assert subject_actions(req_two_units) == ["workflow.started"]
    assert verify_chain() == []


def test_budget_change_uses_cumulative(db, out_budget_policy, settings_fixed_cost_100ty, make_req, org):
    inst = start(make_req(10_000_000, cumulative=205_000_000), "budget_change", org.requester)
    assert inst.rule.label == "B"
    assert inst.snapshot["context"]["cumulative_after_vnd"] == "205000000"


# --- phân tách nhiệm vụ / quyền ------------------------------------------------------------------

def test_requester_cannot_approve_own(db, running_instance, requester):
    with pytest.raises(NotAllowed, match="chính mình lập"):
        act(first_task(running_instance), requester, "APPROVE")


def test_creator_cannot_approve_even_with_role(db, in_budget_policy, make_req, org):
    creator = grant(UserFactory(org_unit=org.itd), R.BUDGET_OWNER, org.itd)
    inst = start(make_req(100_000_000, created_by=creator), "requisition", org.requester)
    task = task_of(inst, "BUDGET_OWNER", org_unit=org.itd)
    assert creator not in candidates(task)
    with pytest.raises(NotAllowed, match="Không được duyệt hồ sơ do chính mình lập"):
        act(task, creator, "APPROVE")


def test_sys_admin_without_step_role_not_allowed(db, running_instance, org):
    with pytest.raises(NotAllowed, match="Quản trị hệ thống không được duyệt nghiệp vụ"):
        act(first_task(running_instance), org.sysadmin, "APPROVE")


def test_user_without_step_role_not_allowed(db, running_instance, org):
    with pytest.raises(NotAllowed, match="Bạn không có quyền xử lý bước này"):
        act(first_task(running_instance), org.gddh, "APPROVE")


@pytest.mark.parametrize("scoped", [False, True])
def test_sys_admin_with_business_role_not_allowed(db, in_budget_policy, make_req, org, scoped):
    admin = grant(UserFactory(username="admin_gddh"), R.GDDH)
    grant(admin, R.SYS_ADMIN, org.itd if scoped else None)
    inst = start(make_req(3_000_000_000), "requisition", org.requester)
    propose = task_of(inst, "PROPOSE")  # PROPOSE/GDDH/COMPANY
    assert admin not in candidates(propose) and org.gddh in candidates(propose)
    with pytest.raises(NotAllowed, match="Quản trị hệ thống không được duyệt nghiệp vụ"):
        act(propose, admin, "APPROVE")
    assert task_of(inst, "PROPOSE").status == "PENDING"


def test_propose_not_auto_skipped_for_sys_admin_submitter(db, in_budget_policy, make_req, org):
    admin = grant(UserFactory(username="admin_tp", org_unit=org.req_unit), R.DEPT_HEAD, org.req_unit)
    grant(admin, R.SYS_ADMIN)
    inst = start(make_req(500_000_000), "requisition", admin)
    assert task_of(inst, "PROPOSE").status == "PENDING"
    assert statuses(inst, "BUDGET_OWNER") == ["WAITING", "WAITING"]


def test_wrong_unit_owner_not_allowed(db, running_instance, org):
    with pytest.raises(NotAllowed, match="không có quyền"):
        act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd), org.owner_adm, "APPROVE")


def test_company_wide_assignment_satisfies_scoped_step(db, running_instance, org):
    global_owner = grant(UserFactory(), R.BUDGET_OWNER)
    act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd), global_owner, "APPROVE")
    assert task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd).acted_by == global_owner


def test_candidates_evaluated_at_act_time(db, running_instance, org):
    newcomer = UserFactory(org_unit=org.itd)
    task = task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd)
    with pytest.raises(NotAllowed):
        act(task, newcomer, "APPROVE")
    grant(newcomer, R.BUDGET_OWNER, org.itd)
    assert act(task, newcomer, "APPROVE").status == "APPROVED"


def test_on_behalf_of_without_delegation_not_allowed(db, running_instance, org):
    with pytest.raises(NotAllowed):
        act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd), org.owner_itd, "APPROVE",
            on_behalf_of=org.owner_adm)


def test_waiting_task_cannot_be_acted(db, running_instance, org):
    with pytest.raises(NotAllowed, match="chưa đến lượt"):
        act(task_of(running_instance, "FAD_PRECHECK"), org.fad, "APPROVE")


# --- tiến trình ----------------------------------------------------------------------------------

def test_branches_must_all_approve_before_next_seq(db, running_instance, org):
    act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd), org.owner_itd, "APPROVE")
    assert task_of(running_instance, "FAD_PRECHECK").status == "WAITING"
    act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.adm), org.owner_adm, "APPROVE")
    assert task_of(running_instance, "FAD_PRECHECK").status == "PENDING"


def test_advisory_consult_does_not_block(db, running_instance, org):
    inst = running_instance
    approve_budget_owners(inst, org)
    # seq tham vấn (chỉ cho ý kiến) mở cùng lúc với seq kế
    assert task_of(inst, "CONSULT").status == "PENDING"
    assert task_of(inst, "FAD_PRECHECK").status == "PENDING"
    act(task_of(inst, "FAD_PRECHECK"), org.fad, "APPROVE")
    consult = task_of(inst, "CONSULT")
    assert consult.status == "SKIPPED" and consult.comment == "Hết lượt góp ý"
    assert task_of(inst, "APPROVE").status == "PENDING"


def test_advisory_accepts_only_comment(db, running_instance, org):
    inst = running_instance
    approve_budget_owners(inst, org)
    consult = task_of(inst, "CONSULT")
    for decision in ("APPROVE", "REJECT", "RETURN"):
        with pytest.raises(NotAllowed):
            act(consult, org.consultant, decision, "ý kiến")
    done = act(consult, org.consultant, "COMMENT", "Đồng ý về kỹ thuật")
    assert done.status == "COMMENTED" and done.comment == "Đồng ý về kỹ thuật"
    assert done.acted_by == org.consultant and done.acted_at is not None
    assert task_of(inst, "FAD_PRECHECK").status == "PENDING"


def test_mandatory_task_rejects_comment_only(db, running_instance, org):
    with pytest.raises(NotAllowed):
        act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd), org.owner_itd, "COMMENT", "x")


def test_full_approval_finishes_and_calls_back(db, running_instance, req_two_units, org):
    inst = running_instance
    approve_budget_owners(inst, org)
    act(task_of(inst, "FAD_PRECHECK"), org.fad, "APPROVE")
    act(task_of(inst, "APPROVE"), org.dept_head, "APPROVE", "OK")
    inst.refresh_from_db()
    req_two_units.refresh_from_db()
    assert inst.status == "APPROVED" and inst.finished_at is not None
    assert req_two_units.finished_status == "APPROVED"
    actions = subject_actions(req_two_units)
    assert actions[0] == "workflow.started" and actions[-1] == "workflow.approved"
    assert actions.count("workflow.task_acted") == 4
    acted = AuditEvent.objects.filter(action="workflow.task_acted").order_by("-id").first()
    assert acted.changes["decision"] == "APPROVE" and acted.changes["comment"] == "OK"
    assert acted.changes["task"] == task_of(inst, "APPROVE").pk
    assert acted.actor == org.dept_head
    assert verify_chain() == []


def test_propose_auto_skipped_when_submitter_has_role(db, in_budget_policy, make_req, org):
    grant(org.requester, R.DEPT_HEAD, org.req_unit)
    inst = start(make_req(500_000_000), "requisition", org.requester)
    propose = task_of(inst, "PROPOSE")
    assert propose.status == "SKIPPED" and propose.comment == "Người lập có vai trò đề xuất"
    assert statuses(inst, "BUDGET_OWNER") == ["PENDING", "PENDING"]
    assert "workflow.task_skipped" in subject_actions(inst.subject)


def test_propose_pending_when_submitter_lacks_role(db, in_budget_policy, make_req, org):
    inst = start(make_req(500_000_000), "requisition", org.requester)
    assert task_of(inst, "PROPOSE").status == "PENDING"
    assert statuses(inst, "BUDGET_OWNER") == ["WAITING", "WAITING"]
    act(task_of(inst, "PROPOSE"), org.dept_head, "APPROVE")
    assert statuses(inst, "BUDGET_OWNER") == ["PENDING", "PENDING"]


def _single_step_policy(past, **step):
    policy = ApprovalPolicy.objects.create(code="S", subject_kind="requisition", version=1, effective_from=past)
    rule = PolicyRule.objects.create(policy=policy, priority=1, label="một bước")
    RuleStep.objects.create(rule=rule, seq=1, sla_hours=8, **step)
    return policy


def test_all_mandatory_steps_skipped_refuses_to_auto_approve(db, past, make_req, org):
    _single_step_policy(past, kind="PROPOSE", role_code=R.REQUESTER, scope="REQUESTER_UNIT", mandatory=True)
    subject = make_req(1)
    with pytest.raises(NoApprover, match="không còn bước duyệt bắt buộc"):
        start(subject, "requisition", org.requester)
    subject.refresh_from_db()
    assert subject.finished_status == "" and not WorkflowInstance.objects.exists()
    assert subject_actions(subject) == []


def test_only_empty_mandatory_steps_refuses(db, past, make_req, org):
    _single_step_policy(past, kind="BUDGET_OWNER", role_code=R.BUDGET_OWNER, scope="BUDGET_UNIT", mandatory=True)
    with pytest.raises(NoApprover):
        start(make_req(1, budget_units=[]), "requisition", org.requester)


@pytest.mark.parametrize("step,make_kwargs,match", [
    ({"kind": "CONSULT", "role_code": R.CONSULTANT, "scope": "FIXED_UNIT"}, {}, "đơn vị cố định"),
    ({"kind": "BUDGET_OWNER", "role_code": R.BUDGET_OWNER, "scope": "BUDGET_UNIT"}, {"bad_bu": True},
     "Không tìm thấy đơn vị quản lý ngân sách"),
    ({"kind": "APPROVE", "role_code": R.DEPT_HEAD, "scope": "REQUESTER_UNIT"}, {"no_unit": True}, "chưa có đơn vị lập"),
], ids=["fixed_unit_missing", "unknown_budget_unit", "no_requester_unit"])
def test_misconfiguration_raises_workflow_error(db, past, make_req, org, step, make_kwargs, match):
    _single_step_policy(past, mandatory=True, **step)
    subject = make_req(1)
    if make_kwargs.get("bad_bu"):
        subject.budget_unit_ids = [999_999]
    if make_kwargs.get("no_unit"):
        subject.unit = None
    subject.save()
    with pytest.raises(Misconfigured, match=match) as exc:
        start(subject, "requisition", org.requester)
    assert isinstance(exc.value, WorkflowError)


def test_opened_at_set_when_task_becomes_pending(db, running_instance, org):
    assert all(t.opened_at is not None for t in running_instance.tasks.filter(status="PENDING"))
    assert task_of(running_instance, "FAD_PRECHECK").opened_at is None
    approve_budget_owners(running_instance, org)
    fad = task_of(running_instance, "FAD_PRECHECK")
    assert fad.opened_at is not None and fad.opened_at >= running_instance.started_at


def test_double_act_sequential(db, running_instance, org):
    task = task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd)
    act(task, org.owner_itd, "APPROVE")
    with pytest.raises(AlreadyProcessed, match="Bước này đã được xử lý"):
        act(task, org.owner_itd, "APPROVE")


@pytest.mark.django_db(transaction=True)
def test_double_act_rejected(running_instance, org):
    task = task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd)
    second_owner = grant(UserFactory(org_unit=org.itd), R.BUDGET_OWNER, org.itd)
    barrier = threading.Barrier(2)
    results = []

    def worker(user):
        try:
            barrier.wait()
            act(WorkflowTask.objects.get(pk=task.pk), user, "APPROVE")
            results.append("ok")
        except AlreadyProcessed:
            results.append("already")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(u,)) for u in (org.owner_itd, second_owner)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["already", "ok"]
    assert AuditEvent.objects.filter(action="workflow.task_acted").count() == 1


@pytest.mark.django_db(transaction=True)
def test_parallel_last_branches_advance_once(running_instance, org):
    """Hai nhánh cuối duyệt đồng thời: khoá instance tuần tự hoá → seq kế vẫn được mở."""
    barrier = threading.Barrier(2)
    pairs = [(task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd), org.owner_itd),
             (task_of(running_instance, "BUDGET_OWNER", org_unit=org.adm), org.owner_adm)]

    def worker(task, user):
        try:
            barrier.wait()
            act(task, user, "APPROVE")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=p) for p in pairs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert task_of(running_instance, "FAD_PRECHECK").status == "PENDING"


# --- trả lại / từ chối ---------------------------------------------------------------------------

def test_return_requires_comment_and_sets_status(db, running_instance, req_two_units, org):
    task = task_of(running_instance, "BUDGET_OWNER", org_unit=org.itd)
    with pytest.raises(NotAllowed, match="Vui lòng nhập lý do"):
        act(task, org.owner_itd, "RETURN", "   ")
    done = act(task, org.owner_itd, "RETURN", "Bổ sung báo giá")
    running_instance.refresh_from_db()
    req_two_units.refresh_from_db()
    assert done.status == "RETURNED" and running_instance.status == "RETURNED"
    assert running_instance.finished_at is not None
    assert set(running_instance.tasks.exclude(pk=task.pk).values_list("status", flat=True)) == {"SKIPPED"}
    assert req_two_units.finished_status == "RETURNED"
    assert subject_actions(req_two_units)[-1] == "workflow.returned"
    with pytest.raises(AlreadyProcessed):
        act(task_of(running_instance, "BUDGET_OWNER", org_unit=org.adm), org.owner_adm, "APPROVE")


def test_reject_requires_comment_and_sets_status(db, running_instance, req_two_units, org):
    task = task_of(running_instance, "BUDGET_OWNER", org_unit=org.adm)
    with pytest.raises(NotAllowed, match="Vui lòng nhập lý do"):
        act(task, org.owner_adm, "REJECT")
    act(task, org.owner_adm, "REJECT", "Không cần thiết")
    running_instance.refresh_from_db()
    req_two_units.refresh_from_db()
    assert running_instance.status == "REJECTED" and req_two_units.finished_status == "REJECTED"
    assert subject_actions(req_two_units)[-1] == "workflow.rejected"


# --- họp --------------------------------------------------------------------------------------------

def test_meeting_step_requires_minutes(db, in_budget_policy, make_req, org):
    subject = make_req(3_000_000_000, consult=False)
    inst = start(subject, "requisition", org.requester)
    act(task_of(inst, "PROPOSE"), org.gddh, "APPROVE")
    approve_budget_owners(inst, org)
    act(task_of(inst, "FAD_PRECHECK"), org.fad, "APPROVE")
    meeting = task_of(inst, "MEETING")
    with pytest.raises(NotAllowed, match="Cần đính kèm biên bản họp"):
        act(meeting, org.bms, "APPROVE")
    attach_minutes(subject, org.bms)
    act(meeting, org.bms, "APPROVE")
    inst.refresh_from_db()
    assert inst.status == "APPROVED"


def test_meeting_minutes_on_other_subject_do_not_count(db, in_budget_policy, make_req, org):
    subject = make_req(3_000_000_000, consult=False, budget_units=[])
    other = make_req(1)
    attach_minutes(other, org.bms)
    inst = start(subject, "requisition", org.requester)
    act(task_of(inst, "PROPOSE"), org.gddh, "APPROVE")
    act(task_of(inst, "FAD_PRECHECK"), org.fad, "APPROVE")
    with pytest.raises(NotAllowed, match="biên bản họp"):
        act(task_of(inst, "MEETING"), org.bms, "APPROVE")


def test_meeting_minutes_uploaded_before_start_do_not_count(db, in_budget_policy, make_req, org):
    subject = make_req(3_000_000_000, consult=False, budget_units=[])
    attach_minutes(subject, org.bms)  # biên bản cũ, trước khi nộp
    inst = start(subject, "requisition", org.requester)
    act(task_of(inst, "PROPOSE"), org.gddh, "APPROVE")
    act(task_of(inst, "FAD_PRECHECK"), org.fad, "APPROVE")
    with pytest.raises(NotAllowed, match="biên bản họp"):
        act(task_of(inst, "MEETING"), org.bms, "APPROVE")
    attach_minutes(subject, org.bms)
    act(task_of(inst, "MEETING"), org.bms, "APPROVE")


# --- phiên bản chính sách ----------------------------------------------------------------------------

def test_snapshot_survives_policy_change(db, running_instance, in_budget_policy, make_req, org):
    v2 = in_budget_policy.clone_as_new_version(timezone.localdate())
    assert v2.version == 2 and v2.code == in_budget_policy.code
    # v2: rule "<200tr" bỏ bước FAD tiền kiểm
    RuleStep.objects.filter(rule__policy=v2, rule__label="<200tr", kind="FAD_PRECHECK").delete()
    # hồ sơ đang chạy vẫn theo snapshot v1
    approve_budget_owners(running_instance, org)
    assert task_of(running_instance, "FAD_PRECHECK").status == "PENDING"
    # hồ sơ mới theo v2
    new_inst = start(make_req(100_000_000), "requisition", org.requester)
    assert new_inst.policy == v2 and new_inst.snapshot["policy"]["version"] == 2
    assert not new_inst.tasks.filter(kind="FAD_PRECHECK").exists()


def test_snapshot_drives_engine_not_live_rule(db, running_instance, org):
    """Engine tiến trình theo snapshot: thêm lén bước vào rule live (bulk_create bỏ qua guard)
    cũng không ảnh hưởng hồ sơ đang chạy."""
    RuleStep.objects.bulk_create([RuleStep(
        rule=running_instance.rule, seq=5, kind="APPROVE", role_code=R.CEO, scope="COMPANY",
        mandatory=True, sla_hours=8)])
    approve_budget_owners(running_instance, org)
    act(task_of(running_instance, "FAD_PRECHECK"), org.fad, "APPROVE")
    act(task_of(running_instance, "APPROVE"), org.dept_head, "APPROVE")
    running_instance.refresh_from_db()
    assert running_instance.status == "APPROVED"


def test_used_policy_is_immutable(db, running_instance, in_budget_policy):
    rule = running_instance.rule
    step = rule.steps.first()
    msg = "Chính sách đã được sử dụng; hãy tạo phiên bản mới"
    in_budget_policy.is_active = False
    with pytest.raises(PermissionError, match=msg):
        in_budget_policy.save()
    with pytest.raises(PermissionError, match=msg):
        in_budget_policy.delete()
    rule.max_amount = Decimal(1)
    with pytest.raises(PermissionError, match=msg):
        rule.save()
    with pytest.raises(PermissionError, match=msg):
        PolicyRule.objects.create(policy=in_budget_policy, priority=9, label="mới")
    step.sla_hours = 1
    with pytest.raises(PermissionError, match=msg):
        step.save()
    with pytest.raises(PermissionError, match=msg):
        step.delete()
    with pytest.raises(PermissionError, match=msg):
        RuleStep.objects.filter(rule=rule).update(sla_hours=1)
    with pytest.raises(PermissionError, match=msg):
        PolicyRule.objects.filter(policy=in_budget_policy).delete()
    with pytest.raises(PermissionError, match=msg):
        ApprovalPolicy.objects.filter(pk=in_budget_policy.pk).update(is_active=False)


def test_used_policy_can_be_deactivated_only(db, running_instance, in_budget_policy):
    msg = "Chính sách đã được sử dụng; hãy tạo phiên bản mới"
    in_budget_policy.is_active = False
    in_budget_policy.save(update_fields=["is_active"])
    in_budget_policy.refresh_from_db()
    assert in_budget_policy.is_active is False
    in_budget_policy.is_active = True
    in_budget_policy.code = "DOI_MA"
    with pytest.raises(PermissionError, match=msg):
        in_budget_policy.save(update_fields=["is_active", "code"])
    with pytest.raises(PermissionError, match=msg):
        in_budget_policy.save()
    in_budget_policy.refresh_from_db()
    assert in_budget_policy.code == "TRONG_NGAN_SACH" and in_budget_policy.is_active is False


def test_unused_policy_is_editable(db, in_budget_policy):
    rule = in_budget_policy.rules.first()
    rule.label = "đổi tên"
    rule.save()
    RuleStep.objects.filter(rule=rule).update(sla_hours=24)


def test_clone_deep_copies_rules_and_steps(db, in_budget_policy):
    v2 = in_budget_policy.clone_as_new_version(timezone.localdate())
    def shape(p):
        return [
            (r.priority, r.label, r.max_amount, r.cumulative_cap, r.cumulative_cap_pct,
             [(s.seq, s.kind, s.role_code, s.scope, s.fixed_org_unit_id, s.mandatory, s.sla_hours,
               s.escalate_role_code, s.requires_doc_type) for s in r.steps.order_by("seq", "pk")])
            for r in p.rules.order_by("priority")
        ]
    assert shape(v2) == shape(in_budget_policy)
    assert not set(v2.rules.values_list("pk", flat=True)) & set(in_budget_policy.rules.values_list("pk", flat=True))
    assert in_budget_policy.clone_as_new_version(timezone.localdate()).version == 3
