import re

from django.core.exceptions import ValidationError

_ORG_RE = re.compile(r"^\d{10}(-\d{3})?$")
_CCCD_RE = re.compile(r"^\d{12}$")
_BANK_RE = re.compile(r"^\d{6,20}$")


def normalize_tax_code(value) -> str:
    """Bỏ mọi khoảng trắng; giữ hậu tố chi nhánh '-NNN'. Chỉ nhận chuỗi (số Excel đã mất số 0 đầu)."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("Mã số thuế phải là chuỗi")
    return re.sub(r"\s+", "", value)


def validate_tax_code(value: str, kind: str = "ORG") -> None:
    ok = bool(_ORG_RE.match(value)) or (kind == "INDIVIDUAL" and bool(_CCCD_RE.match(value)))
    if not ok:
        raise ValidationError("Mã số thuế không hợp lệ")


def validate_bank_account(value: str) -> None:
    if not _BANK_RE.match(value):
        raise ValidationError("Số tài khoản ngân hàng không hợp lệ")
