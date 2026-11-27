import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook

from apps.audit.models import AuditEvent
from apps.budget.importer import import_budget_workbook
from apps.budget.models import (
    ADJUST,
    ORIGINAL,
    BudgetEntry,
    BudgetLine,
    BudgetUnit,
    CostCode,
    CostCodeMainItem,
    Location,
    Project,
)
from scripts import make_sample_data as gen
from tests.factories import OrgUnitFactory


@pytest.fixture
def org(db):
    return OrgUnitFactory(code="ADM-DEMO")


@pytest.fixture
def demo_xlsx(tmp_path):
    gen.main(["--out", str(tmp_path)])
    return tmp_path / gen.WORKBOOK_NAME


def run(path, user, org=None, *, dry_run=False, year=2026, unit="DEMO"):
    return import_budget_workbook(
        path, budget_unit_code=unit, year=year, user=user, dry_run=dry_run,
        managing_org_unit_code=org.code if org else None,
    )


L8_H = ["No", "L8_Code", "L8_name", "Capex/Opex", "Main_items", "Main_2025", "Main_2026", "Main_2027"]
L10_H = ["Project_Code", "Project Name", "Work streams", "Begin_Year", "Dept", "Status"]
EXP_H = ["L8_Code (AOP)", "L8_Code", "L8_name", "Date", "Original", "Adjust", "L10_Code", "Location", "Note"]
CAP_H = ["L8_Code (AOP)", "L8_Code", "L8_name", "Date", "Group", "Original", "Adjust", "L10_Code", "Location", "Note"]


def make_wb(path, l8, l10, exp, cap):
    wb = Workbook()
    ws = wb.active
    ws.title = "L8_Code"
    for name, headers, rows in [("L8_Code", L8_H, l8), ("L10_Code", L10_H, l10),
                                ("Budget_Expense", EXP_H, exp), ("Budget_Capex", CAP_H, cap)]:
        s = ws if name == "L8_Code" else wb.create_sheet(name)
        s.append(headers)
        for r in rows:
            s.append(r)
    wb.save(path)
    return path


def l8row(code, name="Tên", kind=None, main="01. Nhóm một"):
    return [1, code, name, kind, main, main, main, main]


def exprow(code, d=datetime(2026, 1, 1), orig=1000, adj=None, l10=None, loc="HSC", note=None):
    return [None, code, "x", d, orig, adj, l10, loc, note]


def sheet_totals(path, year):
    wb = load_workbook(path, data_only=True)
    orig = adj = Decimal(0)
    for name, o, a in [("Budget_Expense", 4, 5), ("Budget_Capex", 5, 6)]:
        for row in wb[name].iter_rows(min_row=2, values_only=True):
            if row[3] and row[3].year == year:
                orig += Decimal(round(Decimal(str(row[o] or 0))))
                adj += Decimal(round(Decimal(str(row[a] or 0))))
    return orig, adj


def test_dry_run_writes_nothing(demo_xlsx, user, org):
    r = run(demo_xlsx, user, org, dry_run=True)
    assert r.ok, r.issues
    assert BudgetEntry.objects.count() == 0 and BudgetUnit.objects.count() == 0
    assert AuditEvent.objects.filter(action="budget.imported").count() == 0
    assert r.skipped_other_year == 4
    assert r.totals[ORIGINAL] > 0


def test_import_totals_match_sheet(demo_xlsx, user, org):
    r = run(demo_xlsx, user, org)
    assert r.ok, r.issues
    orig, adj = sheet_totals(demo_xlsx, 2026)

    def total(kind):
        return sum(e.amount for e in BudgetEntry.objects.filter(kind=kind))

    assert total(ORIGINAL) == orig and total(ADJUST) == adj
    assert r.totals == {ORIGINAL: orig, ADJUST: adj}
    assert all(e.period.year == 2026 and e.period.day == 1 for e in BudgetEntry.objects.all())
    assert set(Location.objects.values_list("code", flat=True)) == {"HSC", "HNB"}
    assert CostCode.objects.get(code="DM_9.1").is_capex and CostCode.objects.get(code="DM_9.2").is_capex
    assert not CostCode.objects.get(code="DM_1.1").is_capex
    assert CostCodeMainItem.objects.get(cost_code__code="DM_1.1", year=2026).main_item.code == "01"
    assert Project.objects.filter(code="BAU_DEMO").exists()
    assert r.created["entries"] == BudgetEntry.objects.count()
    ev = AuditEvent.objects.get(action="budget.imported")
    assert ev.changes["created"]["entries"] == r.created["entries"]
    assert BudgetEntry.objects.first().note.startswith("Budget_Expense!R2")


def test_reimport_blocked(demo_xlsx, user, org):
    run(demo_xlsx, user, org)
    n = BudgetEntry.objects.count()
    r = run(demo_xlsx, user, org)
    assert not r.ok and "đã được nhập" in r.issues[0].message
    assert BudgetEntry.objects.count() == n


def test_missing_unit_without_org_unit_is_issue(demo_xlsx, user):
    r = run(demo_xlsx, user)
    assert not r.ok and BudgetUnit.objects.count() == 0


def test_existing_unit_needs_no_org_unit(demo_xlsx, user, org):
    BudgetUnit.objects.create(code="DEMO", name="Demo", managing_org_unit=org)
    assert run(demo_xlsx, user).ok


def test_dirty_rows_reported_and_import_aborted(tmp_path, user, org):
    p = make_wb(
        tmp_path / "d.xlsx",
        [l8row("AD_26.1"), l8row("AD_26.1"), l8row("OK_1")],
        [["P1", "Dự án", "WS", 2026, "6. ADM", None]],
        [
            exprow(" OK_1 "),                       # chuẩn hoá được
            exprow("KHONG_CO"),                     # mã L8 không tồn tại
            exprow("OK_1", d=None),                 # Date trống
            exprow("OK_1", d="2026-01-01"),         # Date là chuỗi
            exprow("OK_1", orig="abc"),             # Original không phải số
            exprow("OK_1", loc="XYZ"),              # địa điểm lạ
            exprow("OK_1", l10="RENT_FL7_26"),      # L10 không có trong sheet
        ],
        [],
    )
    r = run(p, user, org)
    assert not r.ok and BudgetEntry.objects.count() == 0
    assert BudgetUnit.objects.count() == 0 and CostCode.objects.count() == 0
    assert {(i.sheet, i.column) for i in r.issues} >= {
        ("Budget_Expense", "L8_Code"), ("Budget_Expense", "Date"), ("Budget_Expense", "Original"),
        ("Budget_Expense", "Location"), ("Budget_Expense", "L10_Code"), ("L8_Code", "L8_Code"),
    }
    l10 = [i for i in r.issues if i.column == "L10_Code"][0]
    assert l10.row == 8 and "không có trong sheet L10_Code" in l10.message


def test_whitespace_normalised_and_float_noise_rounded(tmp_path, user, org):
    p = make_wb(
        tmp_path / "f.xlsx", [l8row("A_1")], [],
        [exprow(" A_1 ", orig=6250000.000000001, adj=-1000000.4)], [],
    )
    assert run(p, user, org).ok
    e = {x.kind: x.amount for x in BudgetEntry.objects.all()}
    assert e == {ORIGINAL: Decimal(6250000), ADJUST: Decimal(-1000000)}


def test_empty_amounts_skipped_and_other_year_counted(tmp_path, user, org):
    p = make_wb(
        tmp_path / "e.xlsx", [l8row("A_1")], [],
        [exprow("A_1", orig=None, adj=0), exprow("A_1", d=datetime(2025, 3, 1), orig="bad"),
         exprow("A_1", d=date(2026, 2, 1), orig=5)], [],
    )
    r = run(p, user, org)
    assert r.ok and r.skipped_other_year == 1
    assert BudgetEntry.objects.count() == 1
    assert BudgetLine.objects.get().project.code == "BAU_DEMO"


def test_negative_original_alone_is_net_negative_issue(tmp_path, user, org):
    p = make_wb(tmp_path / "n.xlsx", [l8row("A_1")], [], [exprow("A_1", orig=-5)], [])
    r = run(p, user, org)
    assert not r.ok and r.issues[0].column == "Original"


def test_main_item_fallback_and_capex_from_sheet(tmp_path, user, org):
    l8 = [[1, "A_1", "n", None, "02. Hai", None, None, None]]
    p = make_wb(tmp_path / "m.xlsx", l8, [], [],
                [[None, "A_1", "n", datetime(2026, 1, 1), "G", 10, None, None, "HNB", None]])
    assert run(p, user, org).ok
    assert CostCode.objects.get().is_capex
    assert CostCodeMainItem.objects.get().main_item.name == "Hai"


def test_missing_header_and_sheet_reported(tmp_path, user, org):
    wb = Workbook()
    wb.active.title = "L8_Code"
    wb.active.append(["L8_Code"])
    wb.save(tmp_path / "x.xlsx")
    r = run(tmp_path / "x.xlsx", user, org)
    assert not r.ok
    assert ("Budget_Expense", "") in {(i.sheet, i.column) for i in r.issues}
    assert ("L8_Code", "L8_name") in {(i.sheet, i.column) for i in r.issues}


def test_generator_is_deterministic_and_hris_valid(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    gen.main(["--out", str(a)])
    gen.main(["--out", str(b)])
    assert (a / gen.HRIS_NAME).read_text() == (b / gen.HRIS_NAME).read_text()
    data = json.loads((a / gen.HRIS_NAME).read_text())
    assert {u["code"] for u in data["org_units"]} >= {"DEMO-A", "DEMO-B", "ITD-DEMO", "ADM-DEMO", "FAD-DEMO"}
    assert all(e["email"].endswith("@example.com") for e in data["employees"])
    roles = {r["role"] for e in data["employees"] for r in e["roles"]}
    assert roles >= {"REQUESTER", "DEPT_HEAD", "GDDH", "BUDGET_OWNER", "FAD_PRECHECK", "BMS_SECRETARY", "CEO"}
    rows = lambda p: list(load_workbook(p).worksheets[2].iter_rows(values_only=True))  # noqa: E731
    assert rows(a / gen.WORKBOOK_NAME) == rows(b / gen.WORKBOOK_NAME)


def test_generated_hris_loads_with_sync(tmp_path, db):
    from apps.accounts.services import sync_hris
    from apps.integrations.fakes import FakeHrisClient

    gen.main(["--out", str(tmp_path)])
    r = sync_hris(FakeHrisClient(tmp_path / gen.HRIS_NAME))
    assert r.created == 6 + 14


def test_import_budget_command_reports_in_vietnamese(demo_xlsx, db, org, capsys):
    from django.core.management import call_command

    call_command("import_budget", str(demo_xlsx), "--unit", "DEMO", "--year", "2026", "--org-unit", org.code)
    out = capsys.readouterr().out
    assert "BÁO CÁO LÀM SẠCH" in out and "Chạy thử" in out and BudgetEntry.objects.count() == 0


def _l8_main(code, m25, m26, items):
    return [1, code, "n", None, items, m25, m26, None]


def _one_row(tmp_path, l8):
    return make_wb(tmp_path / "mi.xlsx", [l8], [], [exprow(l8[1])], [])


def test_main_item_per_year_column(tmp_path, user, org):
    p = _one_row(tmp_path, _l8_main("A_1", "01. Một", "02. Hai", "03. Ba"))
    assert run(p, user, org).ok
    assert CostCodeMainItem.objects.get(year=2026).main_item.code == "02"


def test_main_item_falls_back_to_main_items(tmp_path, user, org):
    p = _one_row(tmp_path, _l8_main("A_1", "01. Một", None, "03. Ba"))
    assert run(p, user, org).ok
    assert CostCodeMainItem.objects.get(year=2026).main_item.code == "03"


def test_malformed_main_item_is_issue(tmp_path, user, org):
    p = _one_row(tmp_path, _l8_main("A_1", "01. Một", "không số", "03. Ba"))
    r = run(p, user, org)
    assert not r.ok and ("L8_Code", "Main_2026") in {(i.sheet, i.column) for i in r.issues}


def test_negative_original_becomes_adjust_when_net_not_negative(tmp_path, user, org):
    p = make_wb(tmp_path / "o.xlsx", [l8row("A_1")], [],
                [exprow("A_1", orig=-197926124), exprow("A_1", orig=197926124, note="bù")], [])
    assert run(p, user, org).ok
    es = list(BudgetEntry.objects.order_by("id"))
    assert [(e.kind, e.amount) for e in es] == [(ADJUST, -197926124), (ORIGINAL, 197926124)]
    assert "(Original âm)" in es[0].note and es[1].note.endswith("bù")


def test_net_negative_line_is_issue(tmp_path, user, org):
    p = make_wb(tmp_path / "o.xlsx", [l8row("A_1")], [], [exprow("A_1", orig=-5)], [])
    r = run(p, user, org)
    assert not r.ok and r.issues[0].column == "Original" and BudgetEntry.objects.count() == 0


def test_near_blank_row_skipped_silently(tmp_path, user, org):
    p = make_wb(tmp_path / "b.xlsx", [l8row("A_1")], [],
                [[None, "A_1", None, None, None, None, None, None, None], exprow("A_1")], [])
    r = run(p, user, org)
    assert r.ok and BudgetEntry.objects.count() == 1


def test_date_not_first_of_month_normalised(tmp_path, user, org):
    p = make_wb(tmp_path / "d.xlsx", [l8row("A_1")], [], [exprow("A_1", d=datetime(2026, 11, 2))], [])
    assert run(p, user, org).ok
    assert BudgetEntry.objects.get().period == date(2026, 11, 1)


def test_new_unit_cannot_reuse_other_units_codes(tmp_path, user, org):
    other = BudgetUnit.objects.create(code="OTH", name="Khác", managing_org_unit=org)
    cc = CostCode.objects.create(code="A_1", name="x", budget_unit=other)
    Project.objects.create(code="P9", name="p", begin_year=2026, budget_unit=other)
    p = make_wb(tmp_path / "c.xlsx", [l8row("A_1")], [["P9", "p", None, 2026, None, None]],
                [exprow("A_1", l10="P9")], [])
    r = run(p, user, org)
    assert not r.ok and {i.column for i in r.issues} == {"L8_Code", "L10_Code"}
    assert BudgetUnit.objects.count() == 1 and not BudgetEntry.objects.exists()
    cc.refresh_from_db()
    assert not cc.is_capex


def test_failure_mid_write_rolls_back_everything(tmp_path, user, org, monkeypatch):
    p = make_wb(tmp_path / "r.xlsx", [l8row("A_1")], [], [exprow("A_1")], [])

    def boom(*a, **k):
        raise RuntimeError("lỗi giả")

    monkeypatch.setattr(BudgetEntry.objects, "bulk_create", boom)
    with pytest.raises(RuntimeError):
        run(p, user, org)
    assert not BudgetUnit.objects.exists() and not CostCode.objects.exists()
    assert not BudgetLine.objects.exists() and not AuditEvent.objects.filter(action="budget.imported").exists()
