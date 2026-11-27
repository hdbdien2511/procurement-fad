"""Sổ bút toán ngân sách: ghi bút toán, số dư, giữ chỗ / giải phóng (spec 7.3).

Quy ước audit: `post()` gọi trực tiếp ghi `budget.entry_posted` cho từng bút toán; `reserve()` và
`release()` ghi MỘT bản audit tổng hợp (`budget.reserved` / `budget.released`) liệt kê các bút toán.
`audit.record()` luôn được gọi cuối cùng trong transaction vì nó giữ advisory lock toàn cục — không
lấy khoá dòng nào sau khi đã gọi nó.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

from apps.audit import service as audit
from apps.core.money import format_vnd, round_vnd

from .allocation import allocate
from .models import (
    BUDGET_KINDS,
    ENTRY_KINDS,
    EXPENSE_KINDS,
    FORECAST,
    NEGATIVE_KINDS,
    NON_NEGATIVE_KINDS,
    RELEASE,
    RESERVE,
    RESERVED_KINDS,
    BudgetEntry,
    BudgetLine,
)

_KIND_CODES = {k for k, _ in ENTRY_KINDS}
ZERO = Decimal(0)


class InsufficientBudget(Exception):
    """Không đủ ngân sách khả dụng (luỹ kế năm) trên một hoặc nhiều dòng."""

    def __init__(self, shortfalls: list[tuple[BudgetLine, Decimal]]):
        self.shortfalls = shortfalls
        super().__init__(str(self))

    def __str__(self):
        parts = "; ".join(f"{line}: thiếu {format_vnd(amt)} đ" for line, amt in self.shortfalls)
        return f"Không đủ ngân sách khả dụng — {parts}"


@dataclass
class Balance:
    budget: Decimal
    reserved: Decimal
    expensed: Decimal
    forecast: Decimal
    available: Decimal


def _source_key(source) -> tuple[str, str]:
    if source is None:
        return "", ""
    return source._meta.label_lower, str(source.pk)


def _to_vnd(amount) -> Decimal:
    """Chuyển về Decimal; từ chối float và số lẻ dưới một đồng."""
    if isinstance(amount, float):
        raise ValueError("Số tiền phải là Decimal, không dùng float.")
    amount = Decimal(amount)
    if amount != round_vnd(amount):
        raise ValueError("Số tiền VND phải là số nguyên đồng.")
    return amount


def _validate(line: BudgetLine, period: date, kind: str, amount: Decimal) -> None:
    if kind not in _KIND_CODES:
        raise ValueError(f"Loại bút toán không hợp lệ: {kind}")
    if period.day != 1:
        raise ValueError("Kỳ ngân sách phải là ngày đầu tháng.")
    if period.year != line.year:
        raise ValueError(f"Kỳ {period:%m/%Y} không thuộc năm {line.year} của dòng ngân sách.")
    if kind in NEGATIVE_KINDS and amount > 0:
        raise ValueError(f"Bút toán {kind} phải có số tiền âm hoặc bằng 0.")
    if kind in NON_NEGATIVE_KINDS and amount < 0:
        raise ValueError(f"Bút toán {kind} phải có số tiền dương hoặc bằng 0.")


def _build(line, period, kind, amount, *, source, user, note="") -> BudgetEntry:
    amount = _to_vnd(amount)
    _validate(line, period, kind, amount)
    source_type, source_id = _source_key(source)
    return BudgetEntry(
        line=line, period=period, kind=kind, amount=amount,
        source_type=source_type, source_id=source_id, note=note, created_by=user,
    )


def _entry_summary(e: BudgetEntry) -> dict:
    return {"line": e.line_id, "period": e.period.isoformat(), "kind": e.kind, "amount": str(e.amount)}


def post(line, period, kind, amount, *, source, user, note="") -> BudgetEntry:
    """Ghi một bút toán (kiểm tra dấu theo loại, kỳ là ngày đầu tháng) và ghi audit."""
    entry = _build(line, period, kind, amount, source=source, user=user, note=note)
    with transaction.atomic():
        entry.save()
        audit.record("budget.entry_posted", entry, actor=user, changes=_entry_summary(entry))
    return entry


def _sum(kinds) -> Coalesce:
    return Coalesce(
        Sum("amount", filter=Q(kind__in=kinds)),
        Value(ZERO),
        output_field=DecimalField(max_digits=18, decimal_places=0),
    )


def balance(line: BudgetLine, *, through: date | None = None) -> Balance:
    """Số dư của dòng (cả năm của dòng, hoặc luỹ kế tới kỳ `through`)."""
    qs = BudgetEntry.objects.filter(line=line)
    if through is not None:
        qs = qs.filter(period__lte=through)
    agg = qs.aggregate(
        budget=_sum(BUDGET_KINDS),
        reserved=_sum(RESERVED_KINDS),
        expensed=_sum(EXPENSE_KINDS),
        forecast=_sum({FORECAST}),
    )
    return Balance(
        budget=agg["budget"],
        reserved=agg["reserved"],
        expensed=agg["expensed"],
        forecast=agg["forecast"],
        available=agg["budget"] - agg["reserved"] - agg["expensed"],
    )


def _lock(line_ids) -> dict[int, BudgetLine]:
    """Khoá các dòng theo thứ tự pk tăng dần (tránh deadlock).

    `of=("self",)`: chỉ khoá dòng ngân sách, không khoá các bảng danh mục được select_related.
    """
    qs = (
        BudgetLine.objects.select_for_update(of=("self",))
        .filter(pk__in=set(line_ids))
        .select_related("budget_unit", "cost_code", "project", "location")
        .order_by("pk")
    )
    return {line.pk: line for line in qs}


def _line_for_year(line: BudgetLine, year: int) -> BudgetLine:
    other, _ = BudgetLine.objects.get_or_create(
        year=year,
        budget_unit_id=line.budget_unit_id,
        cost_code_id=line.cost_code_id,
        project_id=line.project_id,
        location_id=line.location_id,
    )
    return other


def _prepare(allocations, start: date, months: int):
    """Kiểm tra đầu vào và lập kế hoạch `(dòng gốc, kỳ, số tiền)` phân bổ đều theo tháng."""
    allocations = [(line, _to_vnd(amount)) for line, amount in allocations]
    for line, amount in allocations:
        if amount <= 0:
            raise ValueError("Số tiền giữ chỗ phải lớn hơn 0.")
        if start.year < line.year:
            raise ValueError(
                f"Kỳ bắt đầu {start:%m/%Y} sớm hơn năm {line.year} của dòng ngân sách {line}."
            )
    plan: list[tuple[BudgetLine, date, Decimal]] = [
        (line, period, amt)
        for line, amount in allocations
        for period, amt in allocate(amount, start, months)
    ]
    return allocations, plan


def _shortfalls(plan, lines: dict[int, BudgetLine]) -> list[tuple[BudgetLine, Decimal]]:
    """Phần thiếu trên số khả dụng cả năm, chỉ tính các kỳ thuộc năm của dòng (gom theo dòng)."""
    required: dict[int, Decimal] = defaultdict(lambda: ZERO)
    for line, period, amt in plan:
        if period.year == line.year:
            required[line.pk] += amt
    shortfalls = []
    for pk, need in required.items():
        short = need - balance(lines[pk]).available
        if short > 0:
            shortfalls.append((lines[pk], short))
    return shortfalls


def _future_warning(year: int, label: str, amount: Decimal, done: bool) -> str:
    verb = "đã ghi" if done else "sẽ ghi"
    return (
        f"Năm {year} chưa có ngân sách cho dòng {label}: "
        f"{verb} giữ chỗ {format_vnd(amount)} đ, cần bổ sung ngân sách."
    )


def check_reserve(
    allocations: list[tuple[BudgetLine, Decimal]], *, start: date, months: int
) -> tuple[list[tuple[BudgetLine, Decimal]], list[str]]:
    """Chạy thử `reserve` (không khoá, không ghi gì): trả `(shortfalls, warnings)` như `reserve` sẽ gặp.

    Cảnh báo năm sau tính trên dòng cùng chiều của năm đó nếu đã có (chưa có = ngân sách 0).
    """
    _, plan = _prepare(allocations, start, months)
    lines = {line.pk: line for line, _, _ in plan}
    shortfalls = _shortfalls(plan, lines)
    future_amounts: dict[tuple[int, int], Decimal] = defaultdict(lambda: ZERO)
    for line, period, amt in plan:
        if period.year != line.year:
            future_amounts[(line.pk, period.year)] += amt
    warnings = []
    for (line_pk, year), amt in sorted(future_amounts.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        line = lines[line_pk]
        other = BudgetLine.objects.filter(
            year=year, budget_unit_id=line.budget_unit_id, cost_code_id=line.cost_code_id,
            project_id=line.project_id, location_id=line.location_id,
        ).first()
        available = balance(other).available if other is not None else ZERO
        if available - amt < 0:
            warnings.append(_future_warning(year, line.short_label, amt, done=False))
    return shortfalls, warnings


def reserve(
    allocations: list[tuple[BudgetLine, Decimal]], *, start: date, months: int, source, user
) -> list[str]:
    """Giữ chỗ ngân sách, phân bổ đều theo tháng.

    `start` không được sớm hơn năm của dòng. Kỳ thuộc năm của dòng: kiểm tra đủ ngân sách trên số khả dụng cả năm, thiếu thì raise
    `InsufficientBudget` (kiểm tra mọi dòng trước, không ghi gì). Kỳ thuộc năm sau: ghi vào dòng
    cùng chiều của năm đó (tự tạo nếu chưa có) và trả cảnh báo nếu năm đó chưa đủ ngân sách.
    Muốn biết trước kết quả mà không ghi gì: `check_reserve`.
    """
    if source is None:
        raise ValueError("Giữ chỗ phải gắn với hồ sơ nguồn.")
    allocations, plan = _prepare(allocations, start, months)
    with transaction.atomic():
        # 1. Tạo trước dòng năm sau (theo thứ tự pk) để khoá cùng lúc với dòng gốc.
        future: dict[tuple[int, int], BudgetLine] = {}
        for line, period, _ in sorted(plan, key=lambda r: (r[0].pk, r[1])):
            if period.year != line.year and (line.pk, period.year) not in future:
                future[(line.pk, period.year)] = _line_for_year(line, period.year)

        locked = _lock([line.pk for line, _ in allocations] + [f.pk for f in future.values()])

        # 2. Kiểm tra đủ ngân sách trong năm của dòng (luỹ kế cả năm).
        shortfalls = _shortfalls(plan, locked)
        if shortfalls:
            raise InsufficientBudget(shortfalls)

        # 3. Ghi bút toán.
        entries = []
        future_amounts: dict[int, Decimal] = defaultdict(lambda: ZERO)
        for line, period, amt in plan:
            target = locked[line.pk] if period.year == line.year else locked[future[(line.pk, period.year)].pk]
            if target.pk != line.pk:
                future_amounts[target.pk] += amt
            entries.append(_build(target, period, RESERVE, amt, source=source, user=user))
        BudgetEntry.objects.bulk_create(entries)

        # 4. Cảnh báo cho năm sau chưa đủ ngân sách.
        warnings = []
        for target_pk, amt in sorted(future_amounts.items(), key=lambda kv: locked[kv[0]].year):
            target = locked[target_pk]
            if balance(target).available < 0:
                warnings.append(_future_warning(target.year, target.short_label, amt, done=True))

        audit.record(
            "budget.reserved",
            source,
            actor=user,
            changes={"entries": [_entry_summary(e) for e in entries], "warnings": warnings},
        )
    return warnings


def release(source, user) -> None:
    """Giải phóng toàn bộ giữ chỗ còn lại của `source` (RELEASE âm theo từng kỳ). Gọi lại không ghi gì."""
    if source is None:
        raise ValueError("Giải phóng giữ chỗ phải gắn với hồ sơ nguồn.")
    source_type, source_id = _source_key(source)
    with transaction.atomic():
        mine = BudgetEntry.objects.filter(
            source_type=source_type, source_id=source_id, kind__in=RESERVED_KINDS
        )
        locked = _lock(mine.values_list("line_id", flat=True).distinct())
        rows = (
            mine.values("line_id", "period")
            .annotate(net=Sum("amount"))
            .filter(net__gt=0)
            .order_by("line_id", "period")
        )
        entries = [
            _build(locked[r["line_id"]], r["period"], RELEASE, -r["net"], source=source, user=user)
            for r in rows
        ]
        if not entries:
            return
        BudgetEntry.objects.bulk_create(entries)
        audit.record(
            "budget.released",
            source,
            actor=user,
            changes={"entries": [_entry_summary(e) for e in entries]},
        )


# --- bút toán phân bổ theo tháng (bổ sung / điều chuyển ngân sách) -------------------------------------

def _dims(line: BudgetLine) -> tuple:
    return line.year, line.budget_unit_id, line.cost_code_id, line.project_id, line.location_id


def _plan_legs(legs, start: date, months: int) -> list[tuple[BudgetLine, date, Decimal]]:
    """Kế hoạch `(dòng gốc, kỳ, số tiền có dấu)`: mỗi chân `(dòng, số tiền ≠ 0)` chia đều theo tháng."""
    legs = [(line, _to_vnd(amount)) for line, amount in legs]
    for line, amount in legs:
        if amount == 0:
            raise ValueError("Số tiền bút toán phải khác 0.")
        if start.year < line.year:
            raise ValueError(f"Kỳ bắt đầu {start:%m/%Y} sớm hơn năm {line.year} của dòng ngân sách {line}.")
    return [(line, period, amt) for line, amount in legs for period, amt in allocate(amount, start, months)]


def _existing_line_for_year(line: BudgetLine, year: int) -> BudgetLine:
    """Dòng cùng chiều của năm `year`; chưa có thì trả bản chưa lưu (số khả dụng 0)."""
    dims = {"budget_unit_id": line.budget_unit_id, "cost_code_id": line.cost_code_id,
            "project_id": line.project_id, "location_id": line.location_id}
    return BudgetLine.objects.filter(year=year, **dims).first() or BudgetLine(year=year, **dims)


def _other_year_lines(plan, *, create: bool) -> dict[tuple[int, int], BudgetLine]:
    """`(pk dòng gốc, năm)` → dòng cùng chiều của năm khác cho các kỳ ngoài năm của dòng gốc."""
    others: dict[tuple[int, int], BudgetLine] = {}
    for line, period, _ in sorted(plan, key=lambda r: (r[0].pk, r[1])):
        key = (line.pk, period.year)
        if period.year != line.year and key not in others:
            others[key] = (_line_for_year if create else _existing_line_for_year)(line, period.year)
    return others


def _target(line: BudgetLine, period: date, others) -> BudgetLine:
    return line if period.year == line.year else others[(line.pk, period.year)]


def _debit_shortfalls(rows) -> list[tuple[BudgetLine, Decimal]]:
    """Phần thiếu của các khoản ghi giảm `(dòng đích, số tiền < 0)` so với số khả dụng cả năm của dòng."""
    need: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
    targets: dict[tuple, BudgetLine] = {}
    for target, amt in rows:
        if amt < 0:
            need[_dims(target)] += -amt
            targets[_dims(target)] = target
    shortfalls = []
    for key, amount in need.items():
        target = targets[key]
        available = balance(target).available if target.pk is not None else ZERO
        if amount > available:
            shortfalls.append((target, amount - available))
    return shortfalls


def check_allocated(legs: list[tuple[BudgetLine, Decimal]], *, start: date, months: int):
    """Chạy thử `post_allocated` (không khoá, không ghi gì): trả danh sách thiếu của các chân ghi giảm."""
    plan = _plan_legs(legs, start, months)
    others = _other_year_lines(plan, create=False)
    return _debit_shortfalls([(_target(line, period, others), amt) for line, period, amt in plan])


def post_allocated(
    legs: list[tuple[BudgetLine, Decimal]], kind: str, *, start: date, months: int, source, user
) -> list[BudgetEntry]:
    """Ghi bút toán `kind` cho từng chân `(dòng, số tiền có dấu)`, chia đều theo tháng từ `start`.

    Kỳ ngoài năm của dòng ghi vào dòng cùng chiều của năm đó (tự tạo nếu chưa có), như `reserve`.
    Chân âm (ghi giảm) phải đủ số khả dụng cả năm trên dòng đích, thiếu thì raise `InsufficientBudget`
    (không ghi gì). Khoá mọi dòng theo pk trước khi kiểm tra; MỘT bản audit `budget.entries_posted`
    gắn với `source` ở cuối.
    """
    if source is None:
        raise ValueError("Bút toán phân bổ phải gắn với hồ sơ nguồn.")
    plan = _plan_legs(legs, start, months)
    with transaction.atomic():
        others = _other_year_lines(plan, create=True)
        locked = _lock([line.pk for line, _, _ in plan] + [o.pk for o in others.values()])
        rows = [(locked[_target(line, period, others).pk], period, amt) for line, period, amt in plan]
        shortfalls = _debit_shortfalls([(target, amt) for target, _, amt in rows])
        if shortfalls:
            raise InsufficientBudget(shortfalls)
        entries = [_build(target, period, kind, amt, source=source, user=user) for target, period, amt in rows]
        BudgetEntry.objects.bulk_create(entries)
        audit.record(
            "budget.entries_posted",
            source,
            actor=user,
            changes={"kind": kind, "entries": [_entry_summary(e) for e in entries]},
        )
    return entries
