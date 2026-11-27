"""Vòng đời tờ trình mua sắm: kiểm tra, nộp, kết thúc duyệt, giữ chỗ lại, huỷ, sửa lại, sao chép.

Thứ tự khoá trong transaction (tránh deadlock, xem `apps.workflow.engine`):
- luôn khoá `WorkflowInstance` TRƯỚC dòng tờ trình (như `engine.act` → callback), rồi mới tới dòng
  ngân sách (`ledger`);
- `audit.record()` giữ advisory lock toàn cục nên chỉ gọi ở cuối; sau đó chỉ được ghi vào các dòng
  đã khoá từ trước (dòng tờ trình), không lấy khoá mới.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.accounts.roles import FAD_BUDGET_ADMIN, FAD_PRECHECK, has_role, users_with_role
from apps.audit import service as audit
from apps.budget import ledger
from apps.budget.ledger import InsufficientBudget
from apps.budget.models import BudgetLine
from apps.core.fx import MissingRate
from apps.core.money import format_vnd
from apps.core.numbering import next_number
from apps.documents import search, storage
from apps.documents.models import QUOTE, Document
from apps.notifications.outbox import notify
from apps.workflow import delegation, engine, subject
from apps.workflow.models import APPROVED as WF_APPROVED
from apps.workflow.models import PENDING as WF_PENDING
from apps.workflow.models import REJECTED as WF_REJECTED
from apps.workflow.models import RETURNED as WF_RETURNED
from apps.workflow.models import WorkflowInstance

from .models import (
    APPROVED,
    BUDGET_BLOCKED,
    CANCELLED,
    DRAFT,
    IN_APPROVAL,
    REJECTED,
    RETURNED,
    Requisition,
    RequisitionFunding,
    RequisitionLine,
)

REQUIRED_QUOTES = 3
NUMBER_PREFIX = "TT"
_HEADER_FIELDS = (
    "title", "requester_id", "procurement_type", "necessity", "currency",
    "service_start", "months", "vendor_id", "quote_exception_reason",
)


class RequisitionError(Exception):
    """Thao tác không hợp lệ trên tờ trình; `str(e)` là thông báo tiếng Việt."""


class SubmitBlocked(RequisitionError):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass
class BudgetCheck:
    ok: bool
    shortfalls: list[tuple[BudgetLine, Decimal]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- tiện ích ---------------------------------------------------------------------------------------

_SYNC_FIELDS = ("number", "status", "total_original", "total_vnd", "fx_rate")


def _lock(req) -> Requisition:
    return subject.lock(req)


def _sync(target, source) -> None:
    subject.sync(target, source, _SYNC_FIELDS)


def _is_owner(req, user) -> bool:
    return subject.is_owner(req, user)


def _running_instances(req):
    return subject.running_instances(req)


def _quote_count(req) -> int:
    return Document.objects.filter(
        content_type=ContentType.objects.get_for_model(Requisition), object_id=str(req.pk),
        doc_type=QUOTE, superseded_by__isnull=True,
    ).count()


# --- kiểm tra trước khi nộp ---------------------------------------------------------------------------

def validate_for_submit(req) -> list[str]:
    """Danh sách lỗi (tiếng Việt) chặn việc nộp; rỗng = hợp lệ. Tổng VND tính thử theo tỷ giá hôm nay."""
    errors = []
    if req.status != DRAFT:
        errors.append("Chỉ nộp được tờ trình ở trạng thái nháp")
    if req.requester.org_unit_id is None:
        errors.append("Người đề nghị chưa thuộc đơn vị nào")
    if not req.lines.exists():
        errors.append("Cần ít nhất một dòng hàng")
    else:
        try:
            _, total_vnd, _ = req.compute_totals(timezone.localdate())
        except MissingRate as e:
            errors.append(str(e))
        else:
            funded = sum((f.amount_vnd for f in req.fundings.all()), Decimal("0"))
            if total_vnd <= 0:
                errors.append("Tổng tiền tờ trình phải lớn hơn 0")
            elif funded != total_vnd:
                errors.append(
                    f"Tổng phân bổ ngân sách ({format_vnd(funded)}) khác tổng tờ trình ({format_vnd(total_vnd)})"
                )
    if req.fundings.filter(amount_vnd__lte=0).exists():
        errors.append("Số tiền phân bổ ngân sách phải lớn hơn 0")
    if _quote_count(req) < REQUIRED_QUOTES and not req.quote_exception_reason.strip():
        errors.append("Cần đính kèm đủ 03 báo giá hoặc nêu lý do không đủ 03 báo giá")
    if req.vendor_id is not None and not req.vendor.is_selectable():
        errors.append("Nhà cung cấp không ở trạng thái được phép giao dịch")
    if req.fundings.exclude(budget_line__year=req.service_start.year).exists():
        errors.append("Dòng ngân sách phải thuộc năm của ngày bắt đầu dịch vụ")
    return errors


def check_budget(req) -> BudgetCheck:
    """Chạy thử giữ chỗ theo phân bổ ngân sách của tờ trình (không ghi gì)."""
    allocations = req.budget_allocations()
    if not allocations:
        return BudgetCheck(ok=True)
    shortfalls, warnings = ledger.check_reserve(allocations, start=req.reserve_start, months=req.months)
    return BudgetCheck(ok=not shortfalls, shortfalls=shortfalls, warnings=warnings)


# --- nộp ------------------------------------------------------------------------------------------

@transaction.atomic
def submit(req, user) -> WorkflowInstance:
    """Nộp tờ trình: kiểm tra, tính tổng theo tỷ giá ngày nộp, kiểm tra ngân sách, cấp số, khởi tạo
    luồng duyệt. Lỗi kiểm tra → `SubmitBlocked`; thiếu ngân sách → `InsufficientBudget`; lỗi cấu hình
    luồng duyệt → `WorkflowError`. Mọi lỗi đều không để lại thay đổi nào (kể cả số tờ trình)."""
    locked = _lock(req)
    if not _is_owner(locked, user):
        raise SubmitBlocked(["Chỉ người lập hoặc người đề nghị được nộp tờ trình"])
    if _running_instances(locked).exists():
        raise SubmitBlocked(["Tờ trình đang được duyệt"])
    errors = validate_for_submit(locked)
    if errors:
        raise SubmitBlocked(errors)

    today = timezone.localdate()
    locked.total_original, locked.total_vnd, locked.fx_rate = locked.compute_totals(today)
    check = check_budget(locked)
    if not check.ok:
        raise InsufficientBudget(check.shortfalls)
    if not locked.number:
        locked.number = next_number(NUMBER_PREFIX, today.year)
    locked.status = IN_APPROVAL
    locked.requester_unit_id = locked.requester.org_unit_id  # đơn vị người đề nghị tại ngày nộp
    locked.save(update_fields=["total_original", "total_vnd", "fx_rate", "number", "status", "requester_unit"])

    instance = engine.start(locked, "requisition", user)
    audit.record("requisition.submitted", locked, actor=user, changes={
        "number": locked.number, "version": locked.version, "total_vnd": locked.total_vnd,
        "currency": locked.currency, "fx_rate": locked.fx_rate, "instance": instance.pk,
        "budget_warnings": check.warnings,
    })
    _sync(req, locked)
    return instance


# --- kết thúc luồng duyệt / giữ chỗ ----------------------------------------------------------------

FUNDING_MISMATCH = "Tổng phân bổ ngân sách khác tổng tờ trình đã duyệt — không giữ chỗ ngân sách"


def _funding_matches_total(req) -> bool:
    """Giữ chỗ chỉ khi Σ phân bổ = tổng VND đã duyệt > 0 (không giữ chỗ khác số đã duyệt)."""
    funded = sum((f.amount_vnd for f in req.fundings.all()), Decimal("0"))
    return req.total_vnd > 0 and funded == req.total_vnd


def _try_reserve(req, user) -> list[str] | None:
    """Giữ chỗ theo phân bổ; trả cảnh báo, hoặc None nếu thiếu ngân sách (không ghi gì)."""
    try:
        return ledger.reserve(req.budget_allocations(), start=req.reserve_start, months=req.months,
                              source=req, user=user)
    except InsufficientBudget:
        return None


def _notify_budget_blocked(req) -> None:
    title = f"Tờ trình {req} đã được duyệt nhưng chưa giữ chỗ được ngân sách"
    recipients = {req.requester_id: req.requester}
    for u in users_with_role(FAD_PRECHECK).order_by("pk"):
        recipients.setdefault(u.pk, u)
    for user in recipients.values():
        notify(user, title, "/", email_template="RESULT",
               context={"ho_so": str(req), "ket_qua": "Chưa giữ chỗ được ngân sách — cần bổ sung ngân sách"})


def on_workflow_finished(req, status: str) -> None:
    """Callback của engine (trong transaction của `engine.act`, instance đã được khoá)."""
    locked = _lock(req)
    old = locked.status
    warnings, note = [], ""
    if status == WF_APPROVED:
        if not _funding_matches_total(locked):
            result, note = None, FUNDING_MISMATCH
        else:
            result = _try_reserve(locked, None)  # thao tác hệ thống khi hồ sơ được duyệt xong
            if result is None:
                note = "Không đủ ngân sách khả dụng — chưa giữ chỗ"
        if result is None:
            locked.status = BUDGET_BLOCKED
            _notify_budget_blocked(locked)
        else:
            locked.status, warnings = APPROVED, result
    elif status == WF_REJECTED:
        locked.status = REJECTED
    elif status == WF_RETURNED:
        locked.status = RETURNED
    else:
        raise ValueError(f"Kết quả luồng duyệt không hợp lệ: {status}")
    locked.save(update_fields=["status"])
    audit.record("requisition.status_changed", locked, changes={
        "status": [old, locked.status], "workflow_status": status, "budget_warnings": warnings, "note": note,
    })
    _sync(req, locked)


@transaction.atomic
def retry_reserve(req, user) -> list[str]:
    """FAD bấm "Giữ chỗ lại" sau khi đã bổ sung ngân sách; thiếu nữa thì raise `InsufficientBudget`."""
    if not (has_role(user, FAD_BUDGET_ADMIN) or has_role(user, FAD_PRECHECK)):
        raise RequisitionError("Chỉ FAD được giữ chỗ lại ngân sách cho tờ trình")
    locked = _lock(req)
    if locked.status != BUDGET_BLOCKED:
        raise RequisitionError("Tờ trình không ở trạng thái chờ giữ chỗ ngân sách")
    if not _funding_matches_total(locked):
        raise RequisitionError(FUNDING_MISMATCH)
    warnings = ledger.reserve(locked.budget_allocations(), start=locked.reserve_start, months=locked.months,
                              source=locked, user=user)
    locked.status = APPROVED
    locked.save(update_fields=["status"])
    audit.record("requisition.status_changed", locked, actor=user, changes={
        "status": [BUDGET_BLOCKED, APPROVED], "budget_warnings": warnings,
    })
    _sync(req, locked)
    return warnings


# --- huỷ ------------------------------------------------------------------------------------------

@transaction.atomic
def cancel(req, user, reason: str) -> None:
    """Huỷ tờ trình (bắt buộc lý do).

    - Nháp / Trả lại / Chờ giữ chỗ ngân sách: người lập hoặc người đề nghị (Chờ giữ chỗ: cả FAD quản
      trị ngân sách).
    - Đang duyệt: người lập hoặc người đề nghị; luồng duyệt đang chạy bị huỷ.
    - Đã duyệt: chỉ FAD quản trị ngân sách; giải phóng giữ chỗ.
    """
    reason = (reason or "").strip()
    if not reason:
        raise RequisitionError("Vui lòng nhập lý do huỷ")
    # Khoá luồng duyệt trước tờ trình (cùng thứ tự với engine.act → on_workflow_finished).
    running = list(_running_instances(req).select_for_update().order_by("pk"))
    locked = _lock(req)
    old = locked.status
    is_budget_admin = has_role(user, FAD_BUDGET_ADMIN)
    if old in (DRAFT, RETURNED, IN_APPROVAL):
        allowed = _is_owner(locked, user)
    elif old == BUDGET_BLOCKED:
        allowed = _is_owner(locked, user) or is_budget_admin
    elif old == APPROVED:
        allowed = is_budget_admin
    else:
        raise RequisitionError("Không thể huỷ tờ trình ở trạng thái này")
    if not allowed:
        raise RequisitionError("Bạn không có quyền huỷ tờ trình này")

    for instance in running:
        engine.cancel(instance, user, reason)
    if old == APPROVED:
        ledger.release(locked, user)
    locked.status = CANCELLED
    locked.save(update_fields=["status"])
    audit.record("requisition.cancelled", locked, actor=user, changes={
        "status": [old, CANCELLED], "reason": reason,
    })
    _sync(req, locked)


# --- chứng từ -------------------------------------------------------------------------------------

ATTACH_STATUSES = (DRAFT, RETURNED)
ATTACH_NOT_OWNER = (
    "Chỉ người lập hoặc người đề nghị được đính kèm chứng từ cho tờ trình; khi hồ sơ đang duyệt thì "
    "người đang xử lý bước duyệt cũng được đính kèm (ví dụ biên bản họp)"
)
ATTACH_WRONG_STATUS = "Chỉ đính kèm chứng từ khi tờ trình ở trạng thái nháp hoặc bị trả lại"


def handles_pending_task(req, user) -> bool:
    """`user` đang là người xử lý (trực tiếp hoặc theo uỷ quyền) của một bước đang chờ của tờ trình."""
    for instance in _running_instances(req):
        for task in instance.tasks.filter(status=WF_PENDING).order_by("seq", "pk"):
            task.instance = instance
            if engine.candidates(task).filter(pk=user.pk).exists():
                return True
            if delegation.can_act_on_behalf(user, task) is not None:
                return True
    return False


def attach_document(req, user, uploaded_file, doc_type: str) -> Document:
    """Đính kèm chứng từ vào tờ trình.

    Chứng từ lưu vĩnh viễn (không xoá được) và tham gia kiểm tra khi nộp / tiền kiểm, nên quyền ghi
    hẹp hơn quyền xem:

    - người lập hoặc người đề nghị: khi tờ trình còn nháp hoặc bị trả lại;
    - người đang xử lý một bước duyệt (kể cả duyệt thay): khi tờ trình đang duyệt — bước "Duyệt tại
      cuộc họp" đòi biên bản họp đính kèm SAU khi hồ sơ đã nộp nên không ai khác làm được việc này.
    """
    if _is_owner(req, user):
        if req.status not in ATTACH_STATUSES:
            raise RequisitionError(ATTACH_WRONG_STATUS)
    elif not (req.status == IN_APPROVAL and handles_pending_task(req, user)):
        raise RequisitionError(ATTACH_NOT_OWNER)
    return storage.store_upload(uploaded_file, attach_to=req, doc_type=doc_type, user=user)


# --- sửa lại / sao chép ----------------------------------------------------------------------------

def _copy_body(source, target) -> None:
    RequisitionLine.objects.bulk_create(
        RequisitionLine(requisition=target, description=line.description, quantity=line.quantity,
                        unit_price=line.unit_price, vat_rate=line.vat_rate)
        for line in source.lines.all()
    )
    RequisitionFunding.objects.bulk_create(
        RequisitionFunding(requisition=target, budget_line_id=f.budget_line_id, amount_vnd=f.amount_vnd)
        for f in source.fundings.all()
    )
    target.consult_units.set(source.consult_units.all())


def _new_from(source, user, **overrides) -> Requisition:
    data = {name: getattr(source, name) for name in _HEADER_FIELDS}
    data.update(overrides)
    target = Requisition.objects.create(created_by=user, **data)
    _copy_body(source, target)
    return target


def _copy_documents(source, target) -> list[str]:
    """Gắn lại chứng từ hiện hành của `source` vào `target` bằng tham chiếu tới cùng tệp đã lưu."""
    ct = ContentType.objects.get_for_model(Requisition)
    copied = []
    for doc in Document.objects.filter(content_type=ct, object_id=str(source.pk), superseded_by__isnull=True):
        new = Document.objects.create(
            content_type=ct, object_id=str(target.pk), doc_type=doc.doc_type, original_name=doc.original_name,
            stored_path=doc.stored_path, size=doc.size, mime=doc.mime, sha256=doc.sha256,
            text_content=doc.text_content, uploaded_by=doc.uploaded_by,
        )
        search.refresh_search_vector(new)
        copied.append(str(new.pk))
    return copied


@transaction.atomic
def revise(req, user) -> Requisition:
    """Từ tờ trình bị trả lại, tạo phiên bản kế tiếp (cùng số, `version+1`, `previous=req`)."""
    locked = _lock(req)
    if locked.status != RETURNED:
        raise RequisitionError("Chỉ sửa lại được tờ trình bị trả lại")
    if not _is_owner(locked, user):
        raise RequisitionError("Chỉ người lập hoặc người đề nghị được sửa lại tờ trình")
    if locked.next_versions.exists():
        raise RequisitionError("Tờ trình đã có phiên bản mới")
    new = _new_from(locked, user, number=locked.number, version=locked.version + 1, previous=locked)
    documents = _copy_documents(locked, new)
    audit.record("requisition.revised", new, actor=user, changes={
        "number": new.number, "version": new.version, "previous": locked.pk, "documents": documents,
    })
    return new


@transaction.atomic
def copy_as_new(req, user) -> Requisition:
    """Sao chép thành tờ trình nháp mới (R78): dòng hàng, phân bổ, đơn vị tham vấn; không chứng từ."""
    if not req.visible_to(user):
        raise RequisitionError("Bạn không có quyền xem tờ trình này")
    new = _new_from(req, user, requester_id=user.pk)  # đơn vị đề nghị = đơn vị của người sao chép
    audit.record("requisition.copied", new, actor=user, changes={"source": req.pk})
    return new
