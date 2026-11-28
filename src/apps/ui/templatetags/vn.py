from django import template

from apps.core.money import amount_in_words_vi, format_vnd

register = template.Library()


@register.filter
def vnd(value):
    if value in (None, ""):
        return ""
    return format_vnd(value)


@register.filter
def bang_chu(value):
    if value in (None, ""):
        return ""
    return amount_in_words_vi(value)


@register.simple_tag
def cell(row, column):
    """Giá trị ô của bảng: theo khoá cột (cho phép `a__b`), tiền định dạng VND.

    Khoá trỏ tới phương thức không tham số (ví dụ `get_kind_display`) thì gọi để lấy nhãn.
    """
    obj = row
    for part in column.key.split("__"):
        obj = getattr(obj, part, None)
        if callable(obj):
            obj = obj()
        if obj is None:
            break
    if obj is None:
        return ""
    return format_vnd(obj) if column.money else obj


@register.filter
def get_item(mapping, key):
    return mapping.get(key, "") if mapping else ""


@register.simple_tag(takes_context=True)
def qs_with(context, **overrides):
    """Query string hiện tại có thay/bỏ tham số (giá trị rỗng/None = bỏ)."""
    params = context["request"].GET.copy()
    for k, v in overrides.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    s = params.urlencode()
    return f"?{s}" if s else "?"


@register.simple_tag
def next_sort(table, key):
    """Chuỗi `sort` khi bấm tiêu đề cột: chưa sắp -> tăng; tăng -> giảm; giảm -> tăng.

    Cột đã có trong `sort` (kể cả sắp mặc định) được đảo tại chỗ; các cột khác giữ nguyên.
    """
    cur = list(table.sort)
    if key in cur:
        cur = [("-" + key) if k == key else k for k in cur]
    elif "-" + key in cur:
        cur = [key if k == "-" + key else k for k in cur]
    else:
        cur = [key] + cur
    return ",".join(cur)


@register.simple_tag
def sort_state(table, key):
    if key in table.sort:
        return "ascending"
    if "-" + key in table.sort:
        return "descending"
    return "none"
