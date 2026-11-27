"""Tiện ích dùng chung cho hồ sơ đi qua luồng duyệt (tờ trình, đề nghị ngân sách).

Hồ sơ phải có `requester`, `created_by` và `workflow_instances()`. Thứ tự khoá: luôn khoá
`WorkflowInstance` trước dòng hồ sơ, rồi mới tới dòng ngân sách (xem `apps.workflow.engine`).
"""

from .models import RUNNING


def lock(obj):
    """Đọc lại hồ sơ với `select_for_update` (khoá dòng tới hết transaction)."""
    return type(obj)._default_manager.select_for_update().get(pk=obj.pk)


def sync(target, source, fields) -> None:
    """Cập nhật đối tượng người gọi đang giữ theo bản đã ghi."""
    for name in fields:
        setattr(target, name, getattr(source, name))


def is_owner(obj, user) -> bool:
    """Người đề nghị hoặc người lập hồ sơ."""
    return user.pk in (obj.requester_id, obj.created_by_id)


def running_instances(obj):
    return obj.workflow_instances().filter(status=RUNNING)
