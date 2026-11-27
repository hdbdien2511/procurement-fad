"""Báo cáo làm sạch dùng chung cho các bộ nhập Excel (ngân sách, nhà cung cấp)."""

from dataclasses import dataclass, field
from decimal import Decimal


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
