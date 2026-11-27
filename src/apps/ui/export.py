from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .tables import TableSpec

MAX_ROWS = 50_000
MONEY_FORMAT = "#,##0"


class ExportTooLarge(Exception):
    pass


def _value(obj, path: str):
    for part in path.split("__"):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def to_xlsx(spec: TableSpec, qs) -> bytes:
    """Xuất đúng tập đang xem (đã lọc, đã sắp xếp như bảng) ra xlsx; tiền xuất dạng số."""
    if qs.count() > MAX_ROWS:
        raise ExportTooLarge(
            f"Số dòng cần xuất vượt quá giới hạn {MAX_ROWS:,} dòng. Vui lòng thu hẹp bộ lọc.".replace(",", ".")
        )
    wb = Workbook()
    ws = wb.active
    ws.title = (spec.key or "Dữ liệu")[:31]
    cols = spec.columns
    ws.append([c.label for c in cols])
    fill = PatternFill("solid", fgColor="E8EDF3")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = fill
    ws.freeze_panes = "A2"

    widths = [len(c.label) for c in cols]
    sums = {c.key: 0 for c in cols if c.sum}
    for obj in qs.iterator(chunk_size=1000):
        row = []
        for i, c in enumerate(cols):
            v = _value(obj, c.key)
            if c.money and v is not None:
                v = int(v)  # VND nguyên đồng, xuất số (không float)
            if c.sum and v is not None:
                sums[c.key] += v
            if v is None:
                v = ""
            elif not isinstance(v, (int, str)):
                v = str(v)
            widths[i] = max(widths[i], len(f"{v:,}") if isinstance(v, int) else len(str(v)))
            row.append(v)
        ws.append(row)
        for cell, c in zip(ws[ws.max_row], cols):
            if cell.data_type == "f":  # chuỗi người dùng bắt đầu bằng "=" không được thành công thức
                cell.data_type = "s"
            if c.money:
                cell.number_format = MONEY_FORMAT

    if sums:
        total_row = ["Tổng cộng" if i == 0 else "" for i in range(len(cols))]
        for i, c in enumerate(cols):
            if c.sum:
                total_row[i] = sums[c.key]
        ws.append(total_row)
        for cell, c in zip(ws[ws.max_row], cols):
            cell.font = Font(bold=True)
            if c.money:
                cell.number_format = MONEY_FORMAT
            if c.sum:
                widths[cols.index(c)] = max(widths[cols.index(c)], len(f"{sums[c.key]:,}"))

    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = min(max(w + 2, 8), 60)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
