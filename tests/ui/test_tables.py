import io
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.template.loader import render_to_string
from django.test import RequestFactory
from openpyxl import load_workbook

from apps.ui import export
from apps.ui.models import SavedFilter
from apps.ui.saved_filters import delete_filter, list_filters, save_filter
from apps.ui.tables import Column, TableSpec, apply_table
from tests.factories import OrgUnitFactory, UserFactory
from tests.testapp.models import Dummy

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return UserFactory()


@pytest.fixture
def units():
    return {
        "cd": OrgUnitFactory(name="Chương Dương"),
        "hn": OrgUnitFactory(name="Hà Nội"),
    }


def mk(owner, unit, amount, cum=0, status=""):
    return Dummy.objects.create(
        owner=owner, unit=unit, amount_vnd=Decimal(amount), cumulative_vnd=Decimal(cum), finished_status=status
    )


def spec(**kw):
    base = dict(
        key="dummy",
        columns=[
            Column("unit__name", "Đơn vị"),
            Column("amount_vnd", "Số tiền", money=True, sum=True),
            Column("cumulative_vnd", "Lũy kế", money=True, sum=True),
            Column("finished_status", "Trạng thái"),
            Column("owner__username", "Người tạo", sortable=False),
        ],
        filters={"status": "finished_status", "min": "amount_vnd__gte"},
        search_fields=["unit__name"],
        default_sort=["-amount_vnd"],
    )
    base.update(kw)
    return TableSpec(**base)


def req(**params):
    return RequestFactory().get("/x", params)


def test_multi_column_sort_order(owner, units):
    a = mk(owner, units["cd"], 100, status="B")
    b = mk(owner, units["cd"], 300, status="A")
    c = mk(owner, units["hn"], 200, status="A")
    page = apply_table(req(sort="finished_status,-amount_vnd"), Dummy.objects.all(), spec())
    assert [r.pk for r in page.rows] == [b.pk, c.pk, a.pk]
    assert page.sort == ["finished_status", "-amount_vnd"]


def test_default_sort_and_stable_tiebreak(owner, units):
    rows = [mk(owner, units["cd"], 5) for _ in range(3)]
    page = apply_table(req(), Dummy.objects.all(), spec())
    assert [r.pk for r in page.rows] == [r.pk for r in rows]


def test_unknown_or_unsortable_sort_ignored(owner, units):
    mk(owner, units["cd"], 1)
    mk(owner, units["cd"], 2)
    page = apply_table(req(sort="password,owner__username,-bogus"), Dummy.objects.all(), spec())
    assert page.sort == ["-amount_vnd"]
    assert [r.amount_vnd for r in page.rows] == [2, 1]


def test_unknown_filter_ignored_and_known_applied(owner, units):
    mk(owner, units["cd"], 1, status="X")
    mk(owner, units["cd"], 2, status="Y")
    page = apply_table(req(status="X", owner="999", password="x"), Dummy.objects.all(), spec())
    assert [r.finished_status for r in page.rows] == ["X"]
    assert page.params == {"status": "X"}


def test_search_unaccented(owner, units):
    mk(owner, units["cd"], 1)
    mk(owner, units["hn"], 2)
    page = apply_table(req(q="chuong duong"), Dummy.objects.all(), spec())
    assert [r.unit.name for r in page.rows] == ["Chương Dương"]
    page = apply_table(req(q="CHƯƠNG dương"), Dummy.objects.all(), spec())
    assert len(page.rows) == 1
    page = apply_table(req(q="ha noi"), Dummy.objects.all(), spec())
    assert [r.unit.name for r in page.rows] == ["Hà Nội"]


def test_totals_cover_whole_filtered_set_not_page(owner, units):
    for i in range(1, 8):
        mk(owner, units["cd"], i * 10, cum=1)
    mk(owner, units["hn"], 1000, cum=5)
    page = apply_table(req(q="chuong", page_size_ignored="1"), Dummy.objects.all(), spec(page_size=3))
    assert len(page.rows) == 3
    assert page.page_obj.paginator.count == 7
    assert page.totals == {"amount_vnd": Decimal("280"), "cumulative_vnd": Decimal("7")}
    assert isinstance(page.totals["amount_vnd"], Decimal)


def test_totals_empty_are_zero(owner):
    page = apply_table(req(), Dummy.objects.all(), spec())
    assert page.totals == {"amount_vnd": Decimal("0"), "cumulative_vnd": Decimal("0")}


def test_group_totals(owner, units):
    mk(owner, units["cd"], 100, cum=1)
    mk(owner, units["cd"], 50, cum=2)
    mk(owner, units["hn"], 7, cum=3)
    page = apply_table(req(), Dummy.objects.all(), spec(group_by="unit__name"))
    assert list(page.group_totals) == ["Chương Dương", "Hà Nội"]
    assert page.group_totals["Chương Dương"] == {"amount_vnd": Decimal("150"), "cumulative_vnd": Decimal("3")}
    assert page.group_totals["Hà Nội"]["amount_vnd"] == Decimal("7")
    assert apply_table(req(), Dummy.objects.all(), spec()).group_totals == {}


def test_pagination_and_invalid_page(owner, units):
    for i in range(5):
        mk(owner, units["cd"], i)
    s = spec(page_size=2)
    assert apply_table(req(page="3"), Dummy.objects.all(), s).page_obj.number == 3
    assert len(apply_table(req(page="3"), Dummy.objects.all(), s).rows) == 1
    for bad in ("abc", "0", "-2", "99"):
        assert apply_table(req(page=bad), Dummy.objects.all(), s).page_obj.number == 1


def test_export_matches_filter_and_format(owner, units):
    mk(owner, units["cd"], 1234567, cum=10, status="X")
    mk(owner, units["cd"], 100, cum=20, status="X")
    mk(owner, units["hn"], 5, status="Y")
    data = export.to_xlsx(spec(), apply_table(req(status="X", sort="amount_vnd"), Dummy.objects.all(), spec()).qs)
    ws = load_workbook(io.BytesIO(data)).active
    rows = list(ws.iter_rows(values_only=True))
    assert rows[0] == ("Đơn vị", "Số tiền", "Lũy kế", "Trạng thái", "Người tạo")
    assert len(rows) == 1 + 2 + 1  # header + 2 filtered rows + totals
    assert rows[1][1] == 100 and rows[2][1] == 1234567  # same ordering as table
    assert rows[-1][1] == 1234667 and rows[-1][2] == 30
    assert ws["B2"].number_format == "#,##0"
    assert ws["A1"].font.bold
    assert ws.freeze_panes == "A2"


def test_export_row_cap(owner, units, monkeypatch):
    mk(owner, units["cd"], 1)
    mk(owner, units["cd"], 2)
    monkeypatch.setattr(export, "MAX_ROWS", 1)
    with pytest.raises(export.ExportTooLarge, match="vượt quá"):
        export.to_xlsx(spec(), Dummy.objects.all())


def test_saved_filters_own_only_and_unique(owner):
    other = UserFactory()
    save_filter(owner, "dummy", "Của tôi", {"status": "X"})
    save_filter(other, "dummy", "Của tôi", {"status": "Y"})
    assert [f.params for f in list_filters(owner, "dummy")] == [{"status": "X"}]
    save_filter(owner, "dummy", "Của tôi", {"status": "Z"})  # cập nhật, không trùng
    assert SavedFilter.objects.filter(user=owner).count() == 1
    assert list_filters(owner, "dummy")[0].params == {"status": "Z"}
    f = list_filters(owner, "dummy")[0]
    assert delete_filter(other, f.pk) is False
    assert SavedFilter.objects.filter(pk=f.pk).exists()
    assert delete_filter(owner, f.pk) is True
    with pytest.raises(IntegrityError):
        SavedFilter.objects.create(user=other, table_key="dummy", name="Của tôi", params={})
        SavedFilter.objects.create(user=other, table_key="dummy", name="Của tôi", params={})


def test_table_template_renders(owner, units):
    for i in range(3):
        mk(owner, units["cd"], 1000 * (i + 1))
    s = spec(page_size=2, selectable=True)
    r = req(sort="amount_vnd", status="")
    page = apply_table(r, Dummy.objects.all(), s)
    html = render_to_string("ui/table.html", {"table": page, "spec": s}, request=r)
    assert 'name="ids"' in html
    assert "sticky" in html or "table-sticky" in html
    assert "6.000" in html  # tổng cột tiền, định dạng VND
    assert "sort=-amount_vnd" in html  # đảo chiều
    assert "page=2" in html
    empty = apply_table(req(q="zzz"), Dummy.objects.all(), s)
    assert "Không có dữ liệu phù hợp" in render_to_string("ui/table.html", {"table": empty, "spec": s}, request=req(q="zzz"))


def test_base_layout(owner, django_assert_num_queries):
    from django.contrib.messages.storage.cookie import CookieStorage

    from apps.notifications.models import Notification

    Notification.objects.create(user=owner, title="a")
    Notification.objects.create(user=owner, title="b")
    r = req()
    r.user = owner
    r._messages = CookieStorage(r)
    with django_assert_num_queries(1):  # đúng một truy vấn count
        html = render_to_string("base.html", request=r)
    assert "Mua sắm HSC" in html and 'lang="vi"' in html
    assert "Việc chờ tôi" in html and 'href="#main"' in html
    assert "2 thông báo chưa đọc" in html


def test_base_layout_anonymous_no_query(django_assert_num_queries):
    from django.contrib.auth.models import AnonymousUser

    r = req()
    r.user = AnonymousUser()
    with django_assert_num_queries(0):
        html = render_to_string("base.html", request=r)
    assert "Việc chờ tôi" not in html


# --- sửa theo review ---
@pytest.mark.parametrize("bad", ["--amount_vnd", "-", "---amount_vnd", "-,,", "--"])
def test_malformed_sort_is_ignored(owner, units, bad):
    mk(owner, units["cd"], 1)
    page = apply_table(req(sort=bad), Dummy.objects.all(), spec())
    assert page.sort == ["-amount_vnd"] and len(page.rows) == 1


@pytest.mark.parametrize(
    "params",
    [{"min": "abc"}, {"unit": "abc"}, {"q": "a\x00b"}, {"status": "a\x00b"}],
)
def test_bad_values_do_not_crash(owner, units, params):
    mk(owner, units["cd"], 1)
    s = spec(filters={"min": "amount_vnd__gte", "unit": "unit_id", "status": "finished_status"})
    page = apply_table(req(**params), Dummy.objects.all(), s)
    assert page.params == {} or list(page.params) == ["status"]
    render_to_string("ui/table.html", {"table": page, "spec": s}, request=req(**params))


def test_header_link_on_default_sorted_column_changes_order(owner, units):
    from apps.ui.templatetags.vn import next_sort

    mk(owner, units["cd"], 1)
    mk(owner, units["cd"], 2)
    first = apply_table(req(), Dummy.objects.all(), spec())
    assert [r.amount_vnd for r in first.rows] == [2, 1]
    ns = next_sort(first, "amount_vnd")
    assert ns == "amount_vnd"
    second = apply_table(req(sort=ns), Dummy.objects.all(), spec())
    assert [r.amount_vnd for r in second.rows] == [1, 2]
    assert next_sort(second, "amount_vnd") == "-amount_vnd"


def test_related_columns_constant_queries(owner, units, django_assert_max_num_queries):
    for i in range(10):
        mk(owner, units["cd"], i)
    s = spec(page_size=50)
    r = req()
    with django_assert_max_num_queries(6):  # count + sums + select, không phụ thuộc số dòng
        page = apply_table(r, Dummy.objects.all(), s)
        render_to_string("ui/table.html", {"table": page, "spec": s}, request=r)
        export.to_xlsx(s, page.qs)
    n = len(page.rows)
    assert n == 10


def test_xlsx_formula_injection_neutralised(owner, units):
    evil = '=HYPERLINK("http://x","y")'
    u = OrgUnitFactory(name=evil)
    mk(owner, u, 1)
    mk(owner, OrgUnitFactory(name="+cmd"), 2)
    data = export.to_xlsx(spec(), Dummy.objects.order_by("pk"))
    ws = load_workbook(io.BytesIO(data)).active
    assert ws["A2"].data_type == "s" and ws["A2"].value == evil
    assert ws["A3"].data_type == "s"


def test_group_totals_rendered_as_subtotal_rows(owner, units):
    mk(owner, units["cd"], 100)
    mk(owner, units["cd"], 50)
    mk(owner, units["hn"], 7)
    s = spec(group_by="unit__name")
    r = req()
    html = render_to_string("ui/table.html", {"table": apply_table(r, Dummy.objects.all(), s), "spec": s}, request=r)
    assert "Tổng phụ: Chương Dương" in html and "Tổng phụ: Hà Nội" in html
    assert "150" in html


def test_base_has_no_missing_htmx_reference():
    assert "htmx" not in render_to_string("base.html", request=_anon())


def _anon():
    from django.contrib.auth.models import AnonymousUser

    r = req()
    r.user = AnonymousUser()
    return r
