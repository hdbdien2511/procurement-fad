"""Bộ máy luồng duyệt: chọn quy tắc, khởi tạo hồ sơ, xử lý bước (spec 7.1).

Quy tắc thứ tự trong transaction (tránh deadlock): `audit.record()` giữ advisory lock toàn cục, nên
KHÔNG được lấy khoá dòng nào sau khi đã gọi nó trong cùng transaction. Vì vậy `start()` và `act()`
luôn đi theo thứ tự:

1. `select_for_update` instance rồi task (luôn instance trước task);
2. kiểm tra hợp lệ;
3. cập nhật trạng thái task, mở seq kế;
4. nếu hồ sơ kết thúc → gọi `subject.on_workflow_finished(status)` (callback có thể khoá dòng
   ngân sách và tự ghi audit của nó ở cuối);
5. SAU CÙNG mới ghi các bản audit `workflow.*` đã gom lại.

Sau khi khởi tạo, engine chỉ đi theo `instance.snapshot` và các task đã sinh, không đọc lại
chính sách live.
"""

from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.audit import service as audit
from apps.core.services import get_setting
from apps.documents.models import DOC_TYPES, MEETING_MINUTES, Document

from . import resolver
from .models import (
    APPROVE,
    APPROVED,
    BUDGET_CHANGE,
    COMMENTED,
    MEETING,
    PENDING,
    PROPOSE,
    REJECTED,
    RETURNED,
    RUNNING,
    SKIPPED,
    WAITING,
    ApprovalPolicy,
    PolicyRule,
    WorkflowInstance,
    WorkflowTask,
)

DECISIONS = ("APPROVE", "REJECT", "RETURN", "COMMENT")
_FINAL_STATUS = {"APPROVE": APPROVED, "REJECT": REJECTED, "RETURN": RETURNED, "COMMENT": COMMENTED}
_DONE = (APPROVED, SKIPPED)

PROPOSE_SKIP_COMMENT = "Người lập có vai trò đề xuất"
ADVISORY_EXPIRED_COMMENT = "Hết lượt góp ý"


class WorkflowError(Exception):
    pass


class NoPolicy(WorkflowError):
    pass


class NoMatchingRule(WorkflowError):
    pass


class NotAllowed(WorkflowError):
    pass


class AlreadyProcessed(WorkflowError):
    pass


# --- chọn chính sách / quy tắc ----------------------------------------------------------------------

def active_policy(subject_kind: str) -> ApprovalPolicy:
    policy = (
        ApprovalPolicy.objects.filter(
            subject_kind=subject_kind, is_active=True, effective_from__lte=timezone.localdate()
        )
        .order_by("-effective_from", "-version")
        .first()
    )
    if policy is None:
        raise NoPolicy("Chưa có chính sách duyệt hiệu lực cho loại hồ sơ này")
    return policy


def select_rule(policy, ctx: dict, cumulative_after: Decimal | None) -> PolicyRule:
    """Rule đầu tiên (theo `priority` tăng dần) thoả cả ba điều kiện.

    Khi `cumulative_after` là None (hồ sơ không tính luỹ kế) các hạn mức luỹ kế không áp dụng.
    """
    amount = Decimal(ctx["amount_vnd"])
    fixed_cost = None
    for rule in policy.rules.order_by("priority", "pk"):
        if rule.max_amount is not None and amount > rule.max_amount:
            continue
        if cumulative_after is not None:
            if rule.cumulative_cap is not None and not cumulative_after < rule.cumulative_cap:
                continue
            if rule.cumulative_cap_pct is not None:
                if fixed_cost is None:
                    fixed_cost = Decimal(str(get_setting("annual_fixed_cost_vnd") or 0))
                if not cumulative_after < rule.cumulative_cap_pct * fixed_cost / 100:
                    continue
        return rule
    raise NoMatchingRule("Không có quy tắc duyệt phù hợp với hồ sơ")


# --- snapshot -------------------------------------------------------------------------------------

def _dec(value):
    return None if value is None else str(value)


def _normalize_context(raw: dict) -> dict:
    return {
        "amount_vnd": Decimal(raw["amount_vnd"]),
        "budget_unit_ids": [int(i) for i in raw.get("budget_unit_ids") or []],
        "consult_unit_ids": [int(i) for i in raw.get("consult_unit_ids") or []],
        "requester_unit_id": raw.get("requester_unit_id"),
        "created_by_id": raw.get("created_by_id"),
    }


def _snapshot(policy, rule, ctx, cumulative_after) -> dict:
    return {
        "policy": {"code": policy.code, "version": policy.version},
        "rule": {
            "id": rule.pk,
            "label": rule.label,
            "max_amount": _dec(rule.max_amount),
            "cumulative_cap": _dec(rule.cumulative_cap),
            "cumulative_cap_pct": _dec(rule.cumulative_cap_pct),
        },
        "steps": [
            {
                "seq": s.seq,
                "kind": s.kind,
                "role_code": s.role_code,
                "scope": s.scope,
                "fixed_org_unit_id": s.fixed_org_unit_id,
                "mandatory": s.mandatory,
                "sla_hours": s.sla_hours,
                "escalate_role_code": s.escalate_role_code,
                "requires_doc_type": s.requires_doc_type,
            }
            for s in rule.steps.order_by("seq", "pk")
        ],
        "context": {**ctx, "amount_vnd": _dec(ctx["amount_vnd"]), "cumulative_after_vnd": _dec(cumulative_after)},
        "skipped_steps": [],
    }


# --- người xử lý ----------------------------------------------------------------------------------

def candidates(task):
    """Người được xử lý bước (vai trò + phạm vi, trừ người nộp/tạo), tính tại thời điểm gọi."""
    return resolver.candidates(task)


def _resolve_actor(task, user, on_behalf_of):
    """Điểm mở rộng cho duyệt thay (Task 11): trả về người có thẩm quyền mà `user` hành động thay.

    Ở bước này chưa hỗ trợ duyệt thay.
    """
    if on_behalf_of is not None:
        raise NotAllowed("Chưa hỗ trợ duyệt thay")
    return user


# --- tiến trình -----------------------------------------------------------------------------------

class _Run:
    """Gom các thay đổi và bản audit trong một lần `start`/`act` để ghi audit sau cùng."""

    def __init__(self, instance, actor, now):
        self.instance = instance
        self.actor = actor
        self.now = now
        self.events: list[tuple[str, dict]] = []

    def event(self, action, **changes):
        self.events.append((action, {"instance": self.instance.pk, **changes}))


def _skip(task, comment, now):
    task.status = SKIPPED
    task.comment = comment
    task.acted_at = now
    task.save(update_fields=["status", "comment", "acted_at"])


def _open(task, run):
    task.status = PENDING
    task.save(update_fields=["status"])
    if task.kind == PROPOSE and resolver.role_holders(task).filter(pk=run.instance.submitted_by_id).exists():
        _skip(task, PROPOSE_SKIP_COMMENT, run.now)
        run.event("workflow.task_skipped", task=task.pk, seq=task.seq, kind=task.kind, reason=PROPOSE_SKIP_COMMENT)


def _advance(run) -> bool:
    """Mở các seq đến "cổng" (seq đầu tiên còn task bắt buộc chưa xong); trả True nếu đã hết bước.

    Seq chỉ có task tham vấn (không bắt buộc) mở cùng lúc với seq kế. Task tham vấn còn chờ của một
    seq bị bỏ qua ("Hết lượt góp ý") khi seq bắt buộc đầu tiên tính từ seq đó đã hoàn tất.
    """
    while True:
        tasks = list(run.instance.tasks.order_by("seq", "pk"))
        unfinished = [t.seq for t in tasks if t.mandatory and t.status not in _DONE]
        gate = min(unfinished) if unfinished else None
        to_open = [t for t in tasks if t.status == WAITING and (gate is None or t.seq <= gate)]
        if gate is not None and to_open:
            for t in to_open:
                _open(t, run)
            continue  # PROPOSE có thể vừa bị bỏ qua → cổng thay đổi
        mandatory_seqs = sorted({t.seq for t in tasks if t.mandatory})
        for t in tasks:
            if t.mandatory or t.status not in (PENDING, WAITING):
                continue
            closing = next((s for s in mandatory_seqs if s >= t.seq), None)
            if gate is None or (closing is not None and closing < gate):
                _skip(t, ADVISORY_EXPIRED_COMMENT, run.now)
                run.event("workflow.task_skipped", task=t.pk, seq=t.seq, kind=t.kind,
                          reason=ADVISORY_EXPIRED_COMMENT)
        return gate is None


def _finish(run, status, subject):
    instance = run.instance
    skipped = []
    for t in instance.tasks.filter(status__in=(PENDING, WAITING)):
        _skip(t, "", run.now)
        skipped.append(t.pk)
    instance.status = status
    instance.finished_at = run.now
    instance.save(update_fields=["status", "finished_at"])
    subject.on_workflow_finished(status)
    run.event(f"workflow.{status.lower()}", status=status, skipped_tasks=skipped)


def _flush_audit(run, subject):
    for action, changes in run.events:
        audit.record(action, subject, actor=run.actor, changes=changes)


# --- API ------------------------------------------------------------------------------------------

@transaction.atomic
def start(subject, subject_kind: str, submitted_by) -> WorkflowInstance:
    policy = active_policy(subject_kind)
    ctx = _normalize_context(subject.workflow_context())
    cumulative_after = None
    if subject_kind == BUDGET_CHANGE:
        cumulative_after = Decimal(subject.cumulative_amount_vnd(get_setting("cumulative_scope")))
    rule = select_rule(policy, ctx, cumulative_after)
    snapshot = _snapshot(policy, rule, ctx, cumulative_after)
    now = timezone.now()

    instance = WorkflowInstance.objects.create(
        content_type=ContentType.objects.get_for_model(subject), object_id=str(subject.pk),
        policy=policy, rule=rule, snapshot=snapshot, submitted_by=submitted_by, started_at=now,
    )
    tasks = []
    for index, step in enumerate(snapshot["steps"]):
        branches = resolver.expand_step(step, snapshot["context"])
        if not branches:
            snapshot["skipped_steps"].append(
                {"seq": step["seq"], "kind": step["kind"], "reason": "Không có đơn vị áp dụng"}
            )
        for branch_key, org_unit_id in branches:
            tasks.append(WorkflowTask(
                instance=instance, seq=step["seq"], step_index=index, branch_key=branch_key,
                kind=step["kind"], role_code=step["role_code"], org_unit_id=org_unit_id,
                mandatory=step["mandatory"], status=WAITING,
            ))
    WorkflowTask.objects.bulk_create(tasks)
    if snapshot["skipped_steps"]:
        instance.save(update_fields=["snapshot"])

    run = _Run(instance, submitted_by, now)
    run.event("workflow.started", policy=policy.code, version=policy.version, rule=rule.label,
              amount_vnd=snapshot["context"]["amount_vnd"])
    if _advance(run):
        _finish(run, APPROVED, subject)
    _flush_audit(run, subject)
    return instance


def _check_required_document(instance, task):
    step = instance.snapshot["steps"][task.step_index]
    doc_type = step.get("requires_doc_type") or (MEETING_MINUTES if task.kind == MEETING else None)
    if doc_type is None:
        return
    exists = Document.objects.filter(
        content_type_id=instance.content_type_id, object_id=instance.object_id, doc_type=doc_type
    ).exists()
    if not exists:
        label = dict(DOC_TYPES).get(doc_type, doc_type)
        raise NotAllowed(f"Cần đính kèm {label[0].lower()}{label[1:]}")


def _validate_decision(instance, task, decision, comment):
    if decision not in DECISIONS:
        raise NotAllowed("Thao tác không hợp lệ")
    if not task.mandatory:
        if decision != "COMMENT":
            raise NotAllowed("Bước tham vấn chỉ nhận ý kiến")
        if not comment:
            raise NotAllowed("Vui lòng nhập ý kiến")
        return
    if decision == "COMMENT":
        raise NotAllowed("Bước bắt buộc cần chấp thuận, từ chối hoặc trả lại")
    if decision in ("REJECT", "RETURN") and not comment:
        raise NotAllowed("Vui lòng nhập lý do")
    if decision == APPROVE:
        _check_required_document(instance, task)


@transaction.atomic
def act(task, user, decision: str, comment: str = "", *, on_behalf_of=None) -> WorkflowTask:
    instance = WorkflowInstance.objects.select_for_update().get(pk=task.instance_id)
    task = WorkflowTask.objects.select_for_update().get(pk=task.pk)
    task.instance = instance
    if instance.status != RUNNING or task.status not in (PENDING, WAITING):
        raise AlreadyProcessed("Bước này đã được xử lý")
    if task.status == WAITING:
        raise NotAllowed("Bước này chưa đến lượt xử lý")

    principal = _resolve_actor(task, user, on_behalf_of)
    if user.pk in resolver.barred_user_ids(instance):
        raise NotAllowed("Không được duyệt hồ sơ do chính mình lập")
    if not candidates(task).filter(pk=principal.pk).exists():
        raise NotAllowed("Bạn không có quyền xử lý bước này")
    comment = (comment or "").strip()
    _validate_decision(instance, task, decision, comment)

    now = timezone.now()
    task.status = _FINAL_STATUS[decision]
    task.acted_by = user
    task.comment = comment
    task.acted_at = now
    task.save(update_fields=["status", "acted_by", "comment", "acted_at"])

    run = _Run(instance, user, now)
    run.event("workflow.task_acted", task=task.pk, seq=task.seq, kind=task.kind,
              decision=decision, comment=comment)
    subject = instance.subject
    if decision in ("REJECT", "RETURN"):
        _finish(run, task.status, subject)
    elif decision == APPROVE and _advance(run):
        _finish(run, APPROVED, subject)
    _flush_audit(run, subject)
    return task
