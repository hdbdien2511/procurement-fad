"""Báo cáo làm sạch và mở tệp dùng chung cho các bộ nhập Excel (ngân sách, nhà cung cấp)."""

import zipfile
from dataclasses import dataclass, field
from decimal import Decimal

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.documents.storage import InvalidUpload

NOT_XLSX = "Tệp không phải định dạng Excel (.xlsx) hợp lệ."


def open_workbook(source):
    """Mở sổ tính để đọc; tệp không phải .xlsx hoặc đã hỏng thì raise `InvalidUpload` (thông báo tiếng Việt)."""
    try:
        return load_workbook(source, read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise InvalidUpload(NOT_XLSX) from exc


@dataclass
class ImportIssue:
    sheet: str
    row: int
    column: str
    message: str


@dataclass
class ImportReport:
    issues: list[ImportIssue] = field(default_factory=list)
    created: dict[str, int] = field(default_factory=dict)
    skipped_other_year: int = 0
    totals: dict[str, Decimal] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.issues
