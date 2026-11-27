"""Vòng đời đề nghị bổ sung/điều chuyển ngân sách: kiểm tra, nộp, kết thúc duyệt, ghi lại, mở lại, huỷ,
tạo sẵn từ tờ trình bị chặn vì thiếu ngân sách.

Thứ tự khoá trong transaction (tránh deadlock, xem `apps.workflow.engine` và `apps.requisitions.services`):
- luôn khoá `WorkflowInstance` TRƯỚC dòng đề nghị, rồi mới tới dòng ngân sách (`ledger`, theo pk);
- `audit.record()` giữ advisory lock toàn cục nên chỉ gọi ở cuối; sau đó chỉ được ghi vào các dòng
  đã khoá từ trước (dòng đề nghị), không lấy khoá mới. Không bao giờ ghi audit trước khi ghi bút toán.
"""

from decimal import ROUND_CEILING, Decimal

from django.db import transaction
from django.utils import timezone

from apps.accounts.roles import FAD_BUDGET_ADMIN, has_role, users_with_role
from apps.audit import service as audit
from apps.budget import ledger
from apps.budget.ledger import InsufficientBudget
from apps.budget.models import ADJUST
from apps.budget.models import TRANSFER as TRANSFER_ENTRY
from apps.core.numbering import next_number
from apps.notifications.outbox import notify
from apps.requisitions.models import Requisition
from apps.workflow import engine
from apps.workflow.models import APPROVED as WF_APPROVED
from apps.workflow.models import BUDGET_CHANGE
from apps.workflow.models import REJECTED as WF_REJECTED
from apps.workflow.models import RETURNED as WF_RETURNED
from apps.workflow.models import RUNNING, WorkflowInstance

from .models import (
    APPROVED,
    BLOCKED,
    CANCELLED,
    DRAFT,
    IN_APPROVAL,
    REJECTED,
    RETURNED,
    SUPPLEMENT,
    TRANSFER,
    WHOLE_DONG_MESSAGE,
    BudgetChangeRequest,
)

NUMBER_PREFIX = "NS"
BLOCKED_NOTE = "Dòng ngân sách nguồn không đủ số khả dụng — chưa ghi điều chuyển"


class BudgetChangeError(Exception):
    """Thao tác không hợp lệ trên đề nghị ngân sách; `str(e)` là thông báo tiếng Việt."""


class SubmitBlocked(BudgetChangeError):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# --- tiện ích ---------------------------------------------------------------------------------------

def _lock(bcr) -> BudgetChangeRequest:
    return BudgetChangeRequest.objects.select_for_update().get(pk=bcr.pk)


def _sync(target, source) -> None:
    """Cập nhật đối tượng người gọi đang giữ theo bản đã ghi."""
    for name in ("number", "status", "start", "requester_unit_id"):
        setattr(target, name, getattr(source, name))


def _is_owner(bcr, user) -> bool:
    return user.pk in (bcr.requester_id, bcr.created_by_id)


def _running_instances(bcr):
    return bcr.workflow_instances().filter(status=RUNNING)


def _status_changed(locked, old, actor, **changes) -> None:
    audit.record("budget_change.status_changed", locked, actor=actor,
                 changes={"status": [old, locked.status], **changes})


# --- kiểm tra trước khi nộp ---------------------------------------------------------------------------

def validate_for_submit(bcr) -> list[str]:
    """Danh sách lỗi (tiếng Việt) chặn việc nộp; rỗng = hợp lệ."""
    errors = []
    if bcr.status != DRAFT:
        errors.append("Chỉ nộp được đề nghị ở trạng thái nháp")
    if bcr.requester.org_unit_id is None:
        errors.append("Người đề nghị chưa thuộc đơn vị nào")
    amount = bcr.amount_vnd
    if amount is None or amount <= 0:
        errors.append("Số tiền đề nghị phải lớn hơn 0")
    elif amount != amount.to_integral_value():
        errors.append(WHOLE_DONG_MESSAGE)
    if bcr.months is None or bcr.months < 1:
        errors.append("Số tháng phân bổ phải từ 1 trở lên")
    if bcr.start.year != bcr.to_line.year:
        errors.append("Kỳ bắt đầu phải thuộc năm của dòng ngân sách nhận")
    if not (bcr.reason or "").strip():
        errors.append("Vui lòng nhập lý do đề nghị")
    if bcr.kind == SUPPLEMENT:
        if bcr.from_line_id is not None:
            errors.append("Đề nghị bổ sung không có dòng ngân sách nguồn")
    elif bcr.kind == TRANSFER:
        if bcr.from_line_id is None:
            errors.append("Điều chuyển cần chọn dòng ngân sách nguồn")
        elif bcr.from_line_id == bcr.to_line_id:
            errors.append("Dòng ngân sách nguồn và nhận phải khác nhau")
        elif bcr.from_line.year != bcr.to_line.year:
            errors.append("Dòng ngân sách nguồn và nhận phải cùng năm")
    else:
        errors.append("Loại đề nghị không hợp lệ")
    return errors


# --- nộp ------------------------------------------------------------------------------------------

@transaction.atomic
def submit(bcr, user) -> WorkflowInstance:
    """Nộp đề nghị: kiểm tra, (điều chuyển) kiểm tra số khả dụng dòng nguồn, cấp số, khởi tạo luồng duyệt
    "Ngoài ngân sách". Lỗi kiểm tra → `SubmitBlocked`; dòng nguồn không đủ → `InsufficientBudget`; lỗi cấu
    hình luồng duyệt → `WorkflowError`. Mọi lỗi đều không để lại thay đổi nào (kể cả số đề nghị)."""
    locked = _lock(bcr)
    if not _is_owner(locked, user):
        raise SubmitBlocked(["Chỉ người lập hoặc người đề nghị được nộp đề nghị"])
    if _running_instances(locked).exists():
        raise SubmitBlocked(["Đề nghị đang được duyệt"])
    errors = validate_for_submit(locked)
    if errors:
        raise SubmitBlocked(errors)
    if locked.kind == TRANSFER:
        shortfalls = ledger.check_allocated(locked.legs(), start=locked.start, months=locked.months)
        if shortfalls:
            raise InsufficientBudget(shortfalls)

    if not locked.number:
        locked.number = next_number(NUMBER_PREFIX, timezone.localdate().year)
    locked.status = IN_APPROVAL
    locked.requester_unit_id = locked.requester.org_unit_id  # đơn vị người đề nghị tại ngày nộp
    locked.save(update_fields=["number", "status", "requester_unit"])

    instance = engine.start(locked, BUDGET_CHANGE, user)
    audit.record("budget_change.submitted", locked, actor=user, changes={
        "number": locked.number, "kind": locked.kind, "amount_vnd": locked.amount_vnd,
        "from_line": locked.from_line_id, "to_line": locked.to_line_id, "instance": instance.pk,
    })
    _sync(bcr, locked)
    return instance


# --- kết thúc luồng duyệt / ghi ngân sách -------------------------------------------------------------

def _apply(locked, user) -> list:
    """Ghi bút toán của đề nghị đã duyệt; dòng nguồn thiếu thì raise `InsufficientBudget` (không ghi gì)."""
    kind = TRANSFER_ENTRY if locked.kind == TRANSFER else ADJUST
    return ledger.post_allocated(locked.legs(), kind, start=locked.start, months=locked.months,
                                 source=locked, user=user)


def _notify_blocked(bcr) -> None:
    title = f"Đề nghị {bcr} đã được duyệt nhưng chưa ghi được ngân sách"
    recipients = {bcr.requester_id: bcr.requester}
    for u in users_with_role(FAD_BUDGET_ADMIN).order_by("pk"):
        recipients.setdefault(u.pk, u)
    for user in recipients.values():
        notify(user, title, "/", email_template="RESULT",
               context={"ho_so": str(bcr), "ket_qua": "Chưa ghi được ngân sách — dòng nguồn không đủ số khả dụng"})


def on_workflow_finished(bcr, status: str) -> None:
    """Callback của engine (trong transaction của `engine.act`, instance đã được khoá)."""
    locked = _lock(bcr)
    old = locked.status
    note, entries = "", 0
    if status == WF_APPROVED:
        try:
            entries = len(_apply(locked, None))  # thao tác hệ thống khi hồ sơ được duyệt xong
        except InsufficientBudget:
            locked.status, note = BLOCKED, BLOCKED_NOTE
            _notify_blocked(locked)
        else:
            locked.status = APPROVED
    elif status == WF_REJECTED:
        locked.status = REJECTED
    elif status == WF_RETURNED:
        locked.status = RETURNED
    else:
        raise ValueError(f"Kết quả luồng duyệt không hợp lệ: {status}")
    locked.save(update_fields=["status"])
    _status_changed(locked, old, None, workflow_status=status, entries=entries, note=note)
    _sync(bcr, locked)


@transaction.atomic
def retry_apply(bcr, user) -> None:
    """FAD quản trị ngân sách ghi lại điều chuyển bị chặn; dòng nguồn vẫn thiếu thì raise `InsufficientBudget`."""
    if not has_role(user, FAD_BUDGET_ADMIN):
        raise BudgetChangeError("Chỉ FAD quản trị ngân sách được ghi lại đề nghị ngân sách")
    locked = _lock(bcr)
    if locked.status != BLOCKED:
        raise BudgetChangeError("Đề nghị không ở trạng thái chờ ghi ngân sách")
    entries = _apply(locked, user)
    locked.status = APPROVED
    locked.save(update_fields=["status"])
    _status_changed(locked, BLOCKED, user, entries=len(entries))
    _sync(bcr, locked)


# --- mở lại / huỷ -----------------------------------------------------------------------------------

@transaction.atomic
def reopen(bcr, user) -> None:
    """Đưa đề nghị bị trả lại về nháp để sửa và nộp lại (giữ nguyên số đề nghị)."""
    locked = _lock(bcr)
    if locked.status != RETURNED:
        raise BudgetChangeError("Chỉ mở lại được đề nghị bị trả lại")
    if not _is_owner(locked, user):
        raise BudgetChangeError("Chỉ người lập hoặc người đề nghị được mở lại đề nghị")
    locked.status = DRAFT
    locked.save(update_fields=["status"])
    _status_changed(locked, RETURNED, user)
    _sync(bcr, locked)


@transaction.atomic
def cancel(bcr, user, reason: str) -> None:
    """Huỷ đề nghị (bắt buộc lý do).

    - Nháp / Trả lại / Đang duyệt: người lập hoặc người đề nghị; luồng duyệt đang chạy bị huỷ.
    - Chưa ghi được ngân sách: người lập, người đề nghị hoặc FAD quản trị ngân sách (chưa có bút toán).
    - Đã duyệt: không huỷ được — lập đề nghị ngược chiều.
    """
    reason = (reason or "").strip()
    if not reason:
        raise BudgetChangeError("Vui lòng nhập lý do huỷ")
    # Khoá luồng duyệt trước đề nghị (cùng thứ tự với engine.act → on_workflow_finished).
    running = list(_running_instances(bcr).select_for_update().order_by("pk"))
    locked = _lock(bcr)
    old = locked.status
    if old in (DRAFT, RETURNED, IN_APPROVAL):
        allowed = _is_owner(locked, user)
    elif old == BLOCKED:
        allowed = _is_owner(locked, user) or has_role(user, FAD_BUDGET_ADMIN)
    elif old == APPROVED:
        raise BudgetChangeError("Đề nghị đã duyệt và đã ghi ngân sách — lập đề nghị ngược chiều thay vì huỷ")
    else:
        raise BudgetChangeError("Không thể huỷ đề nghị ở trạng thái này")
    if not allowed:
        raise BudgetChangeError("Bạn không có quyền huỷ đề nghị này")

    for instance in running:
        engine.cancel(instance, user, reason)
    locked.status = CANCELLED
    locked.save(update_fields=["status"])
    audit.record("budget_change.cancelled", locked, actor=user, changes={
        "status": [old, CANCELLED], "reason": reason,
    })
    _sync(bcr, locked)


# --- tạo sẵn từ tờ trình bị chặn ----------------------------------------------------------------------

def _within_year_months(start, months: int) -> int:
    """Số tháng phân bổ không vượt quá tháng 12 của năm bắt đầu.

    Phần thiếu của tờ trình chỉ tính trên các kỳ thuộc năm của dòng (`ledger`), nên toàn bộ số bổ sung
    phải rơi vào năm đó mới bù đủ.
    """
    return min(months, 13 - start.month)


@transaction.atomic
def prefill_from_shortfall(req, shortfalls, user) -> list[BudgetChangeRequest]:
    """Tạo (hoặc cập nhật) đề nghị bổ sung nháp cho từng dòng ngân sách thiếu của tờ trình `req`.

    `shortfalls`: `[(dòng ngân sách, số thiếu)]` như `InsufficientBudget.shortfalls`. Số tiền làm tròn lên
    đồng; kỳ bắt đầu / số tháng lấy từ tờ trình (giới hạn trong năm). Đã có đề nghị nháp cho cùng
    (tờ trình, dòng) thì cập nhật thay vì tạo trùng.
    """
    if not req.visible_to(user):
        raise BudgetChangeError("Bạn không có quyền xem tờ trình này")
    req = Requisition.objects.select_for_update().get(pk=req.pk)  # tuần tự hoá các lần tạo sẵn
    start = req.reserve_start
    months = _within_year_months(start, req.months)
    label = req.number or f"nháp #{req.pk}"
    reason = f"Bổ sung ngân sách cho tờ trình {label}"
    results, events = [], []
    for line, shortfall in shortfalls:
        amount = Decimal(shortfall).quantize(Decimal("1"), rounding=ROUND_CEILING)
        if amount <= 0:
            continue
        existing = (
            BudgetChangeRequest.objects.select_for_update()
            .filter(requisition=req, to_line=line, kind=SUPPLEMENT, status=DRAFT)
            .order_by("pk").first()
        )
        if existing is None:
            bcr = BudgetChangeRequest.objects.create(
                kind=SUPPLEMENT, to_line=line, amount_vnd=amount, start=start, months=months, reason=reason,
                requisition=req, requester_id=req.requester_id, created_by=user,
            )
            events.append(("budget_change.prefilled", bcr, {"requisition": req.pk, "amount_vnd": amount}))
        else:
            bcr, old_amount = existing, existing.amount_vnd
            bcr.amount_vnd, bcr.start, bcr.months = amount, start, months
            bcr.save(update_fields=["amount_vnd", "start", "months"])
            events.append(("budget_change.prefill_updated", bcr,
                           {"requisition": req.pk, "amount_vnd": [old_amount, amount]}))
        results.append(bcr)
    for action, bcr, changes in events:  # audit sau cùng (sau mọi khoá/ghi)
        audit.record(action, bcr, actor=user, changes=changes)
    return results
