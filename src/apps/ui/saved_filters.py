from .models import SavedFilter


def save_filter(user, table_key: str, name: str, params: dict) -> SavedFilter:
    """Lưu bộ lọc; trùng tên (cùng người, cùng bảng) thì cập nhật tham số."""
    obj, _ = SavedFilter.objects.update_or_create(
        user=user, table_key=table_key, name=name.strip(), defaults={"params": dict(params)}
    )
    return obj


def list_filters(user, table_key: str):
    return SavedFilter.objects.filter(user=user, table_key=table_key)


def delete_filter(user, pk: int) -> bool:
    """Chỉ xoá bộ lọc của chính người dùng; trả về True nếu đã xoá."""
    deleted, _ = SavedFilter.objects.filter(user=user, pk=pk).delete()
    return bool(deleted)
