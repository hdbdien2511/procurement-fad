import unicodedata


def strip_accents(s: str) -> str:
    """Bỏ dấu tiếng Việt (đ→d), khớp với hàm unaccent phía cơ sở dữ liệu."""
    s = s.replace("đ", "d").replace("Đ", "D")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")
