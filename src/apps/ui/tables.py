from dataclasses import dataclass, field
from decimal import Decimal

from django.core.paginator import EmptyPage, Page, PageNotAnInteger, Paginator
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
    keys = []
    for part in raw.split(","):
        part = part.strip()
        if part.lstrip("-") in allowed and part.lstrip("-") not in {k.lstrip("-") for k in keys}:
            keys.append(part)
    return keys


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
        value = get.get(param, "")
        if value != "":
            qs = qs.filter(**{lookup: value})
            params[param] = value

    q = get.get("q", "").strip()
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
