"""Lỗi nghiệp vụ của bộ máy luồng duyệt (thông báo tiếng Việt, hiển thị được cho người dùng)."""


class WorkflowError(Exception):
    pass


class NoPolicy(WorkflowError):
    pass


class NoMatchingRule(WorkflowError):
    pass


class NoApprover(WorkflowError):
    """Sau khi phân giải, không còn bước bắt buộc nào cần người duyệt."""


class Misconfigured(WorkflowError):
    """Cấu hình bước hoặc dữ liệu hồ sơ không đủ để xác định đơn vị xử lý."""


class NotAllowed(WorkflowError):
    pass


class AlreadyProcessed(WorkflowError):
    pass
