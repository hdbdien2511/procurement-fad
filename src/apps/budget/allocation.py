from datetime import date
from decimal import ROUND_DOWN, Decimal

from apps.core.money import round_vnd


def add_months(d: date, n: int) -> date:
    idx = d.month - 1 + n
    return date(d.year + idx // 12, idx % 12 + 1, 1)


def allocate(amount: Decimal, start: date, months: int) -> list[tuple[date, Decimal]]:
    """Chia đều `amount` vào `months` kỳ tháng từ `start` (ngày đầu tháng).

    Tổng được làm tròn về đồng (ROUND_HALF_UP); mỗi kỳ lấy phần nguyên đồng (cắt bớt, để phần dư
    luôn cùng dấu và không âm), phần dư dồn vào kỳ cuối. `months=1` cho chi phí một lần (Once-off).
    """
    if months < 1:
        raise ValueError("Số kỳ phân bổ phải từ 1 trở lên.")
    if start.day != 1:
        raise ValueError("Kỳ bắt đầu phải là ngày đầu tháng.")
    total = round_vnd(amount)
    each = (total / months).quantize(Decimal("1"), rounding=ROUND_DOWN)
    rows = [(add_months(start, i), each) for i in range(months - 1)]
    rows.append((add_months(start, months - 1), total - each * (months - 1)))
    return rows
