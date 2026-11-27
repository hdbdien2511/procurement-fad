"""Nhắc hạn, báo quá hạn và chuyển cấp cho các bước đang chờ xử lý (job định kỳ của worker).

Với mỗi task PENDING có `due_at`:

- REMINDER  khi còn ≤ 24 giờ và chưa quá hạn (`now ≤ due_at`), `reminded_at` trống;
- OVERDUE   khi `now > due_at`, `overdue_notified_at` trống;
- ESCALATION khi `now > due_at + sla_hours` (của bước trong snapshot) và bước có
  `escalate_role_code`, `escalated_at` trống — gửi cho `users_with_role(escalate_role_code)` toàn
  công ty và ghi audit `workflow.task_escalated`.

Mỗi loại chỉ gửi một lần cho mỗi task (đánh dấu thời điểm trên task). Mỗi task xử lý trong một
transaction ngắn riêng với `select_for_update(skip_locked=True)`: task đang bị người duyệt khoá thì
để lượt sau. Thứ tự trong transaction: khoá task → chèn thông báo → đánh dấu → audit (sau cùng).
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.roles import ROLE_NAMES, users_with_role
from apps.audit import service as audit
from apps.notifications.outbox import notify

from .engine import format_due, task_recipients, task_url
from .models import PENDING, WorkflowTask

REMIND_BEFORE = timedelta(hours=24)


@dataclass(frozen=True)
class SlaReport:
    reminded: int = 0
    overdue: int = 0
    escalated: int = 0


def _step(task):
    return task.instance.snapshot["steps"][task.step_index]


def _context(task, subject, **extra):
    return {"ho_so": str(subject), "han_xu_ly": format_due(task.due_at), **extra}


def _remind(task, subject, now):
    ho_so = str(subject)
    for user in task_recipients(task):
        notify(user, f"Hồ sơ {ho_so} sắp đến hạn xử lý", task_url(task), email_template="REMINDER",
               context=_context(task, subject))
    task.reminded_at = now
    task.save(update_fields=["reminded_at"])


def _overdue(task, subject, now):
    ho_so = str(subject)
    for user in task_recipients(task):
        notify(user, f"Hồ sơ {ho_so} đã quá hạn xử lý", task_url(task), email_template="OVERDUE",
               context=_context(task, subject))
    task.overdue_notified_at = now
    task.save(update_fields=["overdue_notified_at"])


def _escalate(task, subject, now):
    role = _step(task)["escalate_role_code"]
    cap_moi = ROLE_NAMES.get(role, role)
    ho_so = str(subject)
    recipients = list(users_with_role(role).order_by("pk"))
    for user in recipients:
        notify(user, f"Hồ sơ {ho_so} được chuyển cấp xử lý", task_url(task), email_template="ESCALATION",
               context=_context(task, subject, cap_moi=cap_moi))
    task.escalated_at = now
    task.save(update_fields=["escalated_at"])
    audit.record("workflow.task_escalated", subject, actor=None, changes={
        "instance": task.instance_id, "task": task.pk, "seq": task.seq, "kind": task.kind,
        "escalate_role": role, "recipients": [u.get_username() for u in recipients],
    })


def _due_escalation(task, now) -> bool:
    step = _step(task)
    return bool(step.get("escalate_role_code")) and now > task.due_at + timedelta(hours=step["sla_hours"])


# (tên trường đánh dấu, điều kiện SQL, điều kiện bổ sung theo snapshot, hành động)
def _rules(now):
    return [
        ("reminded", "reminded_at", {"due_at__gte": now, "due_at__lte": now + REMIND_BEFORE}, None, _remind),
        ("overdue", "overdue_notified_at", {"due_at__lt": now}, None, _overdue),
        ("escalated", "escalated_at", {"due_at__lt": now}, _due_escalation, _escalate),
    ]


def _process_one(pk, mark_field, filters, extra_check, action, now) -> bool:
    with transaction.atomic():
        task = (
            WorkflowTask.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("instance")
            .filter(pk=pk, status=PENDING, **{f"{mark_field}__isnull": True}, **filters)
            .first()
        )
        if task is None or (extra_check is not None and not extra_check(task, now)):
            return False
        action(task, task.instance.subject, now)
        return True


def process_sla(now=None) -> SlaReport:
    now = now or timezone.now()
    counts = {}
    for name, mark_field, filters, extra_check, action in _rules(now):
        ids = list(
            WorkflowTask.objects.filter(status=PENDING, due_at__isnull=False, **{f"{mark_field}__isnull": True},
                                        **filters)
            .order_by("due_at", "pk").values_list("pk", flat=True)
        )
        counts[name] = sum(_process_one(pk, mark_field, filters, extra_check, action, now) for pk in ids)
    return SlaReport(**counts)
