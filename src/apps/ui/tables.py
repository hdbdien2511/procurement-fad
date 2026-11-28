from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.core.paginator import EmptyPage, Page, PageNotAnInteger, Paginator
from django.db import DataError, transaction
from django.db.models import Q, QuerySet, Sum

from apps.core.text import strip_accents


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    sortable: bool = True
    money: bool = False
    sum: bool = False


@dataclass
class TableSpec:
    key: str
    columns: list[Column]
    filters: dict[str, str] = field(default_factory=dict)  # tham số -> lookup ORM
    search_fields: list[str] = field(default_factory=list)
    default_sort: list[str] = field(default_factory=list)
    group_by: str | None = None
    page_size: int = 50
    selectable: bool = False
    row_url: str | None = None  # tên route chi tiết (nhận pk): ô cột đầu thành liên kết


@dataclass
class TablePage:
    rows: list
    page_obj: Page
    totals: dict
    group_totals: dict
    sort: list[str]
    params: dict
    qs: QuerySet  # tập đã lọc + sắp xếp (dùng cho xuất tệp)
    q: str = ""


def _sort_keys(raw: str, spec: TableSpec) -> list[str]:
    allowed = {c.key for c in spec.columns if c.sortable}
    keys, seen = [], set()
    for part in raw.split(","):
        part = part.strip()
        desc = part.startswith("-")
        name = part[1:] if desc else part
        if name in allowed and name not in seen:
            seen.add(name)
            keys.append(("-" if desc else "") + name)
    return keys


def _related_paths(model, spec: TableSpec) -> list[str]:
    """Đường FK (nhiều-một/một-một) trong khoá cột, để select_related tránh N+1."""
    paths = set()
    for c in spec.columns:
        parts = c.key.split("__")[:-1]
        m, acc = model, []
        for part in parts:
            try:
                f = m._meta.get_field(part)
            except FieldDoesNotExist:
                break
            if not (f.is_relation and (f.many_to_one or f.one_to_one) and f.related_model):
                break
            acc.append(part)
            paths.add("__".join(acc))
            m = f.related_model
    return sorted(paths)


def _search(qs: QuerySet, q: str, spec: TableSpec) -> QuerySet:
    for word in strip_accents(q).split():
        cond = Q()
        for f in spec.search_fields:
            cond |= Q(**{f"{f}__unaccent__icontains": word})
        qs = qs.filter(cond)
    return qs


def apply_table(request, qs: QuerySet, spec: TableSpec) -> TablePage:
    get = request.GET
    params = {}
    for param, lookup in spec.filters.items():
        value = get.get(param, "").replace("\x00", "")
        if value == "":
            continue
        try:
            candidate = qs.filter(**{lookup: value})
            with transaction.atomic():
                candidate.order_by().exists()  # lỗi kiểu dữ liệu/tràn số bộc lộ tại đây
        except (ValueError, ValidationError, DataError):
            continue  # giá trị không hợp lệ: bỏ qua bộ lọc này
        qs = candidate
        params[param] = value

    qs = qs.select_related(*_related_paths(qs.model, spec))
    q = get.get("q", "").replace("\x00", "").strip()
    if q and spec.search_fields:
        qs = _search(qs, q, spec)

    sort = _sort_keys(get.get("sort", ""), spec) or list(spec.default_sort)
    qs = qs.order_by(*sort, "pk")

    sum_cols = [c.key for c in spec.columns if c.sum]
    totals = {k: Decimal("0") for k in sum_cols}
    if sum_cols:
        agg = qs.order_by().aggregate(**{k: Sum(k) for k in sum_cols})
        totals = {k: agg[k] if agg[k] is not None else Decimal("0") for k in sum_cols}

    group_totals = {}
    if spec.group_by and sum_cols:
        grouped = (
            qs.order_by()
            .values(spec.group_by)
            .annotate(**{f"_sum_{k}": Sum(k) for k in sum_cols})
            .order_by(spec.group_by)
        )
        for row in grouped:
            group_totals[row[spec.group_by]] = {
                k: row[f"_sum_{k}"] if row[f"_sum_{k}"] is not None else Decimal("0") for k in sum_cols
            }

    paginator = Paginator(qs, spec.page_size)
    try:
        page_obj = paginator.page(get.get("page", 1))
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    return TablePage(
        rows=list(page_obj.object_list),
        page_obj=page_obj,
        totals=totals,
        group_totals=group_totals,
        sort=sort,
        params=params,
        qs=qs,
        q=q,
    )
