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
from apps.core.services import get_setting
from apps.notifications.outbox import notify
from apps.requisitions import models as requisitions
from apps.workflow import engine, subject
from apps.workflow.exceptions import NoMatchingRule
from apps.workflow.models import APPROVED as WF_APPROVED
from apps.workflow.models import BUDGET_CHANGE, PolicyRule, WorkflowInstance
from apps.workflow.models import REJECTED as WF_REJECTED
from apps.workflow.models import RETURNED as WF_RETURNED

from .models import (
    APPROVED,
    BLOCKED,
    CANCELLED,
    CUMULATIVE_STATUSES,
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
REROUTE_NOTE = "Luỹ kế ngoài ngân sách đã vượt mức của cấp đã duyệt; cần trình lại cấp cao hơn"
NOT_IN_APPROVAL = "Đề nghị không ở trạng thái đang duyệt"
# Trạng thái của đề nghị đã tồn tại cho cùng (tờ trình, dòng ngân sách): dùng lại, không tạo bản trùng.
LIVE_STATUSES = (DRAFT, RETURNED, *CUMULATIVE_STATUSES)
# Tờ trình đang bị chặn vì thiếu ngân sách (chưa nộp được, hoặc đã duyệt mà chưa giữ chỗ được).
PREFILL_REQ_STATUSES = (requisitions.DRAFT, requisitions.RETURNED, requisitions.BUDGET_BLOCKED)


class BudgetChangeError(Exception):
    """Thao tác không hợp lệ trên đề nghị ngân sách; `str(e)` là thông báo tiếng Việt."""


class _Rerouted(BudgetChangeError):
    """Luỹ kế đã vượt mức của cấp đã duyệt — chỉ dùng nội bộ giữa `_apply` và người gọi."""


class SubmitBlocked(BudgetChangeError):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


# --- tiện ích ---------------------------------------------------------------------------------------

_SYNC_FIELDS = ("number", "status", "start", "requester_unit_id", "submitted_at")


def _lock(bcr) -> BudgetChangeRequest:
    return subject.lock(bcr)


def _sync(target, source) -> None:
    subject.sync(target, source, _SYNC_FIELDS)


def _is_owner(bcr, user) -> bool:
    return subject.is_owner(bcr, user)


def _running_instances(bcr):
    return subject.running_instances(bcr)


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
    locked.submitted_at = timezone.now()  # thứ tự nộp quyết định luỹ kế (xem `cumulative_amount_vnd`)
    locked.save(update_fields=["number", "status", "requester_unit", "submitted_at"])

    instance = engine.start(locked, BUDGET_CHANGE, user)
    audit.record("budget_change.submitted", locked, actor=user, changes={
        "number": locked.number, "kind": locked.kind, "amount_vnd": locked.amount_vnd,
        "from_line": locked.from_line_id, "to_line": locked.to_line_id, "instance": instance.pk,
    })
    _sync(bcr, locked)
    return instance


# --- kết thúc luồng duyệt / ghi ngân sách -------------------------------------------------------------

def _rerouted(locked) -> bool:
    """Luỹ kế tại thời điểm ghi có vượt mức của cấp đã duyệt hay không.

    Tính lại luỹ kế và chọn lại quy tắc trên ĐÚNG phiên bản chính sách đã dùng khi nộp (lấy từ snapshot
    của hồ sơ duyệt). Quy tắc mới có `priority` lớn hơn (cấp cao hơn) nghĩa là hồ sơ đã được duyệt ở cấp
    thấp hơn mức cần thiết → không ghi ngân sách, phải trình lại. Gọi SAU khi đã khoá các dòng ngân sách
    liên quan để hai hồ sơ cùng dòng không cùng lúc vượt mức.
    """
    instance = locked.workflow_instances().order_by("-pk").first()
    if instance is None:
        raise BudgetChangeError("Đề nghị chưa có hồ sơ duyệt")
    approved_rule = PolicyRule.objects.filter(pk=instance.snapshot["rule"]["id"]).first()
    cumulative = Decimal(locked.cumulative_amount_vnd(get_setting("cumulative_scope")))
    try:
        rule = engine.select_rule(instance.policy, {"amount_vnd": locked.amount_vnd}, cumulative)
    except NoMatchingRule:
        return True
    return approved_rule is None or rule.priority > approved_rule.priority


def _apply(locked, user) -> list:
    """Ghi bút toán của đề nghị đã duyệt.

    Dòng nguồn thiếu → `InsufficientBudget`; luỹ kế vượt cấp đã duyệt → `_Rerouted`; đã có bút toán của
    hồ sơ này → `ValueError` (chống ghi trùng). Mọi trường hợp đều không ghi gì.
    """
    kind = TRANSFER_ENTRY if locked.kind == TRANSFER else ADJUST
    ledger.lock_lines([line.pk for line, _ in locked.legs()])  # tuần tự hoá việc kiểm tra luỹ kế
    if _rerouted(locked):
        raise _Rerouted(REROUTE_NOTE)
    return ledger.post_allocated(locked.legs(), kind, start=locked.start, months=locked.months,
                                 source=locked, user=user)


def _notify_blocked(bcr, reason: str) -> None:
    title = f"Đề nghị {bcr} đã được duyệt nhưng chưa ghi được ngân sách"
    recipients = {bcr.requester_id: bcr.requester}
    for u in users_with_role(FAD_BUDGET_ADMIN).order_by("pk"):
        recipients.setdefault(u.pk, u)
    for user in recipients.values():
        notify(user, title, "/", email_template="RESULT",
               context={"ho_so": str(bcr), "ket_qua": f"Chưa ghi được ngân sách — {reason}"})


def on_workflow_finished(bcr, status: str) -> None:
    """Callback của engine (trong transaction của `engine.act`, instance đã được khoá).

    Chỉ chạy một lần cho mỗi đề nghị: hồ sơ phải đang ở trạng thái "Đang duyệt" (chống ghi trùng khi
    callback bị gọi lại).
    """
    locked = _lock(bcr)
    if locked.status != IN_APPROVAL:
        raise BudgetChangeError(NOT_IN_APPROVAL)
    note, entries = "", 0
    if status == WF_APPROVED:
        try:
            entries = len(_apply(locked, None))  # thao tác hệ thống khi hồ sơ được duyệt xong
        except (InsufficientBudget, _Rerouted) as e:
            note = REROUTE_NOTE if isinstance(e, _Rerouted) else BLOCKED_NOTE
            locked.status = BLOCKED
            _notify_blocked(locked, note)
        else:
            locked.status = APPROVED
    elif status == WF_REJECTED:
        locked.status = REJECTED
    elif status == WF_RETURNED:
        locked.status = RETURNED
    else:
        raise ValueError(f"Kết quả luồng duyệt không hợp lệ: {status}")
    locked.save(update_fields=["status"])
    _status_changed(locked, IN_APPROVAL, None, workflow_status=status, entries=entries, note=note)
    _sync(bcr, locked)


@transaction.atomic
def retry_apply(bcr, user) -> None:
    """FAD quản trị ngân sách ghi lại đề nghị bị chặn.

    Dòng nguồn vẫn thiếu → `InsufficientBudget`; luỹ kế đã vượt cấp đã duyệt → `BudgetChangeError`
    (phải trình lại cấp cao hơn, FAD không ghi thay được).
    """
    if not has_role(user, FAD_BUDGET_ADMIN):
        raise BudgetChangeError("Chỉ FAD quản trị ngân sách được ghi lại đề nghị ngân sách")
    locked = _lock(bcr)
    if locked.status != BLOCKED:
        raise BudgetChangeError("Đề nghị không ở trạng thái chờ ghi ngân sách")
    try:
        entries = _apply(locked, user)
    except _Rerouted as e:
        raise BudgetChangeError(str(e)) from e
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


def _requested_lines(req, shortfalls) -> list:
    """Các dòng ngân sách người gọi xin bổ sung, phải thuộc phân bổ của tờ trình (bỏ trùng, theo pk)."""
    funded = set(req.fundings.values_list("budget_line_id", flat=True))
    lines, seen = [], set()
    for line, _ in shortfalls:
        if line.pk not in funded:
            raise BudgetChangeError(f"Dòng ngân sách {line} không thuộc phân bổ của tờ trình")
        if line.pk not in seen:
            seen.add(line.pk)
            lines.append(line)
    return lines


@transaction.atomic
def prefill_from_shortfall(req, shortfalls, user) -> list[BudgetChangeRequest]:
    """Tạo sẵn đề nghị bổ sung nháp cho các dòng ngân sách thiếu của tờ trình `req` (spec 4.1).

    `shortfalls`: `[(dòng ngân sách, số thiếu)]` như `InsufficientBudget.shortfalls` — chỉ dùng để biết
    người gọi xin bổ sung những dòng nào; mỗi dòng phải thuộc phân bổ của tờ trình và **số tiền được
    tính lại** từ ngân sách hiện tại (`ledger.check_reserve`), không tin số của người gọi.

    Chỉ người lập / người đề nghị tờ trình gọi được, và chỉ khi tờ trình đang bị chặn vì thiếu ngân sách
    (nháp, trả lại, hoặc đã duyệt mà chưa giữ chỗ được). Kỳ bắt đầu / số tháng lấy từ tờ trình (giới hạn
    trong năm). Mỗi (tờ trình, dòng ngân sách) chỉ có một đề nghị còn sống: bản nháp được cập nhật số
    tiền, bản đã nộp/đã duyệt được dùng lại nguyên trạng (không tạo bản trùng).
    """
    if not _is_owner(req, user):
        raise BudgetChangeError("Chỉ người lập hoặc người đề nghị tờ trình được tạo đề nghị bổ sung")
    if req.status not in PREFILL_REQ_STATUSES:
        raise BudgetChangeError("Tờ trình không ở trạng thái thiếu ngân sách")
    lines = _requested_lines(req, shortfalls)
    req = requisitions.Requisition.objects.select_for_update().get(pk=req.pk)  # tuần tự hoá các lần tạo sẵn
    recomputed, _ = ledger.check_reserve(req.budget_allocations(), start=req.reserve_start, months=req.months)
    if not recomputed:
        raise BudgetChangeError("Tờ trình không thiếu ngân sách")
    needed = {line.pk: amount for line, amount in recomputed}

    start = req.reserve_start
    months = _within_year_months(start, req.months)
    reason = f"Bổ sung ngân sách cho tờ trình {req.number or f'nháp #{req.pk}'}"
    results, events = [], []
    for line in lines:
        amount = Decimal(needed.get(line.pk, 0)).quantize(Decimal("1"), rounding=ROUND_CEILING)
        if amount <= 0:
            continue
        existing = (
            BudgetChangeRequest.objects.select_for_update()
            .filter(requisition=req, to_line=line, kind=SUPPLEMENT, status__in=LIVE_STATUSES)
            .order_by("pk").first()
        )
        if existing is None:
            bcr = BudgetChangeRequest.objects.create(
                kind=SUPPLEMENT, to_line=line, amount_vnd=amount, start=start, months=months, reason=reason,
                requisition=req, requester_id=req.requester_id, created_by=user,
            )
            events.append(("budget_change.prefilled", bcr, {"requisition": req.pk, "amount_vnd": amount}))
        elif existing.status == DRAFT:
            bcr, old_amount = existing, existing.amount_vnd
            bcr.amount_vnd, bcr.start, bcr.months = amount, start, months
            bcr.save(update_fields=["amount_vnd", "start", "months"])
            if old_amount != amount:
                events.append(("budget_change.prefill_updated", bcr,
                               {"requisition": req.pk, "amount_vnd": [old_amount, amount]}))
        else:
            bcr = existing  # đã nộp / đã duyệt: dùng lại, không sửa và không tạo bản trùng
        results.append(bcr)
    for action, bcr, changes in events:  # audit sau cùng (sau mọi khoá/ghi)
        audit.record(action, bcr, actor=user, changes=changes)
    return results
