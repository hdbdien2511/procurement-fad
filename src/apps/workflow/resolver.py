"""Phân giải phạm vi bước duyệt thành đơn vị cụ thể và người được xử lý.

- `expand_step`: một bước trong snapshot → danh sách nhánh `(branch_key, org_unit_id)`.
  `BUDGET_UNIT` / `SELECTED_UNITS` sinh một nhánh cho mỗi id trong ngữ cảnh (có thể rỗng).
- `role_holders` / `candidates`: luôn tính tại thời điểm gọi (không lưu đệm); chỉ dựa trên phân
  công vai trò, không bao giờ xét `is_superuser` / `is_staff`.
"""

from apps.accounts.roles import users_with_role
from apps.budget.models import BudgetUnit

from .models import BUDGET_UNIT, COMPANY, FIXED_UNIT, REQUESTER_UNIT, SELECTED_UNITS


def _unique(ids):
    return list(dict.fromkeys(int(i) for i in ids))


def expand_step(step: dict, ctx: dict) -> list[tuple[str, int | None]]:
    scope = step["scope"]
    if scope == COMPANY:
        return [("", None)]
    if scope == REQUESTER_UNIT:
        if ctx.get("requester_unit_id") is None:
            raise ValueError("Hồ sơ chưa có đơn vị lập")
        return [("", ctx["requester_unit_id"])]
    if scope == FIXED_UNIT:
        if step.get("fixed_org_unit_id") is None:
            raise ValueError("Bước phạm vi đơn vị cố định chưa chọn đơn vị")
        return [("", step["fixed_org_unit_id"])]
    if scope == BUDGET_UNIT:
        ids = _unique(ctx.get("budget_unit_ids") or [])
        managing = dict(BudgetUnit.objects.filter(pk__in=ids).values_list("pk", "managing_org_unit_id"))
        missing = [i for i in ids if i not in managing]
        if missing:
            raise ValueError(f"Không tìm thấy đơn vị quản lý ngân sách: {missing}")
        return [(f"budget_unit:{i}", managing[i]) for i in ids]
    if scope == SELECTED_UNITS:
        return [(f"org_unit:{i}", i) for i in _unique(ctx.get("consult_unit_ids") or [])]
    raise ValueError(f"Phạm vi không hợp lệ: {scope}")


def barred_user_ids(instance) -> set[int]:
    """Người nộp và người tạo hồ sơ: không được xử lý bất kỳ bước nào của hồ sơ."""
    ids = {instance.submitted_by_id, instance.snapshot["context"].get("created_by_id")}
    return {i for i in ids if i is not None}


def role_holders(task):
    """Người có đúng vai trò + phạm vi của bước (chưa loại trừ phân tách nhiệm vụ)."""
    return users_with_role(task.role_code, task.org_unit_id)


def candidates(task):
    return role_holders(task).exclude(pk__in=barred_user_ids(task.instance))
