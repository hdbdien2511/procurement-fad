"""Đưa lỗi nghiệp vụ (thông báo tiếng Việt của tầng service) ra `django.contrib.messages`.

Mọi view hành động bọc lời gọi service trong `domain_errors(request, success=...)`: lỗi nghiệp vụ
thành một thông báo đỏ, không bao giờ thành lỗi 500. Không có quy tắc nghiệp vụ nào ở đây.
"""

from contextlib import contextmanager

from django.contrib import messages
from django.core.exceptions import ValidationError

from apps.budget.ledger import InsufficientBudget
from apps.budget_changes.services import BudgetChangeError
from apps.core.fx import MissingRate
from apps.documents.storage import InvalidUpload
from apps.requisitions.services import RequisitionError
from apps.workflow.exceptions import WorkflowError

# `PermissionError` / `ValueError`: model và sổ ngân sách dùng chúng cho các vi phạm nghiệp vụ
# (hồ sơ đã nộp không được sửa, chính sách đã dùng, kỳ không thuộc năm của dòng...) — thông báo
# của chúng đều là tiếng Việt, hiển thị được cho người dùng.
DOMAIN_ERRORS = (
    WorkflowError,
    InsufficientBudget,
    RequisitionError,
    BudgetChangeError,
    InvalidUpload,
    MissingRate,
    ValidationError,
    PermissionError,
    ValueError,
)


def error_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return " ".join(exc.messages)
    return str(exc) or exc.__class__.__name__


@contextmanager
def domain_errors(request, *, success: str | None = None):
    """Bắt lỗi nghiệp vụ và hiển thị; không lỗi thì hiện `success` (nếu có)."""
    try:
        yield
    except DOMAIN_ERRORS as exc:  # noqa: BLE001  (chỉ các lỗi nghiệp vụ đã liệt kê)
        messages.error(request, error_message(exc))
    else:
        if success:
            messages.success(request, success)
