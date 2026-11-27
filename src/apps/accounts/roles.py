from datetime import date

from django.db import transaction
from django.db.models import Q

from apps.audit.service import record

from .models import Role, RoleAssignment, User

REQUESTER = "REQUESTER"
DEPT_HEAD = "DEPT_HEAD"
GDNV = "GDNV"
GDDH = "GDDH"
CEO = "CEO"
BMS_SECRETARY = "BMS_SECRETARY"
BOARD_SECRETARY = "BOARD_SECRETARY"
FAD_PRECHECK = "FAD_PRECHECK"
FAD_BUDGET_ADMIN = "FAD_BUDGET_ADMIN"
BUDGET_OWNER = "BUDGET_OWNER"
CONSULTANT = "CONSULTANT"
SYS_ADMIN = "SYS_ADMIN"
AUDITOR = "AUDITOR"

ROLE_NAMES = {
    REQUESTER: "Người đề nghị",
    DEPT_HEAD: "Trưởng đơn vị",
    GDNV: "Giám đốc nghiệp vụ",
    GDDH: "Giám đốc điều hành",
    CEO: "Tổng giám đốc",
    BMS_SECRETARY: "Thư ký BMS",
    BOARD_SECRETARY: "Thư ký HĐQT",
    FAD_PRECHECK: "FAD kiểm tra sơ bộ",
    FAD_BUDGET_ADMIN: "FAD quản trị ngân sách",
    BUDGET_OWNER: "Đơn vị chủ quản ngân sách",
    CONSULTANT: "Tư vấn",
    SYS_ADMIN: "Quản trị hệ thống",
    AUDITOR: "Kiểm toán",
}


def _active_assignments(role_code, org_unit, on):
    """Phân công hiệu lực tại ngày `on` (mặc định hôm nay; `valid_to` tính cả ngày cuối).

    - `org_unit=None`: chỉ phân công toàn công ty (org_unit null) thoả mãn.
    - `org_unit` cụ thể: phân công đúng đơn vị đó HOẶC phân công toàn công ty thoả mãn.
    Phân công theo đơn vị KHÔNG thoả mãn kiểm tra toàn công ty.
    """
    on = on or date.today()
    scope = Q(org_unit__isnull=True)
    if org_unit is not None:
        scope |= Q(org_unit=org_unit)
    return RoleAssignment.objects.filter(
        scope,
        Q(valid_to__isnull=True) | Q(valid_to__gte=on),
        role__code=role_code,
        valid_from__lte=on,
    )


def has_role(user, role_code, org_unit=None, on=None) -> bool:
    """Người dùng có vai trò tại thời điểm `on` hay không.

    `org_unit=None` nghĩa là vai trò toàn công ty: phân công theo đơn vị không thoả mãn.
    Ngược lại, phân công toàn công ty thoả mãn mọi kiểm tra theo đơn vị.
    """
    if not user.is_active:
        return False
    return _active_assignments(role_code, org_unit, on).filter(user=user).exists()


def users_with_role(role_code, org_unit=None, on=None):
    """Người dùng đang hoạt động có vai trò (cùng quy tắc phạm vi như `has_role`)."""
    ids = _active_assignments(role_code, org_unit, on).values("user_id")
    return User.objects.filter(pk__in=ids, is_active=True)


@transaction.atomic
def assign(user, role_code, org_unit=None, valid_from=None, valid_to=None, actor=None):
    assignment = RoleAssignment.objects.create(
        user=user,
        role=Role.objects.get(code=role_code),
        org_unit=org_unit,
        valid_from=valid_from or date.today(),
        valid_to=valid_to,
    )
    record(
        "role.assigned",
        assignment,
        actor=actor,
        changes={
            "user": user.username,
            "role": role_code,
            "org_unit": org_unit.code if org_unit else None,
            "valid_from": assignment.valid_from,
            "valid_to": valid_to,
        },
    )
    return assignment
