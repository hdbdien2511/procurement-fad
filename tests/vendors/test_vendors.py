import pytest
from django.core.exceptions import ValidationError

from apps.audit.models import AuditEvent
from apps.budget.importer import import_budget_workbook
from apps.budget.models import BudgetEntry
from apps.core.imports import ImportIssue, ImportReport
from apps.vendors.importer import import_vendors_from_rows
from apps.vendors.models import Vendor
from apps.vendors.validators import (
    normalize_tax_code,
    validate_bank_account,
    validate_tax_code,
)
from scripts import make_sample_data as gen
from tests.factories import OrgUnitFactory, UserFactory


@pytest.fixture
def user(db):
    return UserFactory(username="fad")


def row(kind, tax, name, n=2):
    return {"_row": n, "Loại hình": kind, "Mã số thuế": tax, "Tên nhà cung cấp": name}


def test_shared_report_classes_reexported():
    from apps.budget import importer

    assert importer.ImportReport is ImportReport and importer.ImportIssue is ImportIssue


def test_validate_tax_code():
    validate_tax_code("0300481551-006")
    validate_tax_code("0300481551")
    with pytest.raises(ValidationError) as e:
        validate_tax_code("03004815")
    assert e.value.messages == ["Mã số thuế không hợp lệ"]
    with pytest.raises(ValidationError):
        validate_tax_code("012345678901")  # CCCD không hợp lệ cho tổ chức
    validate_tax_code("012345678901", kind="INDIVIDUAL")


def test_normalize_tax_code():
    assert normalize_tax_code(" 0300 4815 51-006 ") == "0300481551-006"
    with pytest.raises(TypeError):
        normalize_tax_code(300481551)


def test_validate_bank_account():
    validate_bank_account("123456")
    with pytest.raises(ValidationError):
        validate_bank_account("12345")
    with pytest.raises(ValidationError):
        validate_bank_account("12ab56")


def test_is_selectable_only_active(db):
    v = Vendor.objects.create(code="1", tax_code="0300481551", name="A", status="BLACKLISTED")
    assert v.is_selectable() is False
    v.status = "ACTIVE"
    assert v.is_selectable() is True


def test_change_status_audits_with_diff(db, user):
    v = Vendor.objects.create(code="1", tax_code="0300481551", name="A", status="ACTIVE")
    v.change_status("BLACKLISTED", user, "Vi phạm hợp đồng")
    v.refresh_from_db()
    assert v.status == "BLACKLISTED"
    ev = AuditEvent.objects.get(action="vendor.status_changed")
    assert ev.changes["status"] == ["ACTIVE", "BLACKLISTED"]
    assert ev.changes["reason"] == "Vi phạm hợp đồng"
    assert ev.object_id == str(v.pk)


def test_change_status_rejects_unknown(db, user):
    v = Vendor.objects.create(code="1", tax_code="0300481551", name="A")
    with pytest.raises(ValueError):
        v.change_status("XYZ", user, "")


def test_import_creates_active_vendors(db, user):
    rows = [row("Tổ chức", "0300481551-006", "Cty A", 2), row("Cá nhân", "012345678901", "Ông B", 3)]
    r = import_vendors_from_rows(rows, user, dry_run=False)
    assert r.ok and r.created["vendors"] == 2
    a = Vendor.objects.get(tax_code="0300481551-006")
    assert a.code == a.tax_code and a.kind == "ORG" and a.status == "ACTIVE"
    assert Vendor.objects.get(tax_code="012345678901").kind == "INDIVIDUAL"
    assert AuditEvent.objects.filter(action="vendors.imported").count() == 1


def test_dry_run_writes_nothing(db, user):
    r = import_vendors_from_rows([row("Tổ chức", "0300481551", "A")], user)
    assert r.ok and r.created["vendors"] == 1 and Vendor.objects.count() == 0


def test_duplicate_tax_code_in_file_is_one_issue(db, user):
    rows = [row("Tổ chức", "0300481551", "A", 2), row("Tổ chức", "0300 481551", "B", 5)]
    r = import_vendors_from_rows(rows, user, dry_run=False)
    assert len(r.issues) == 1 and "2" in r.issues[0].message and "5" in r.issues[0].message
    assert r.issues[0].row == 5 and Vendor.objects.count() == 0


def test_invalid_tax_code_all_or_nothing(db, user):
    rows = [row("Tổ chức", "0300481551", "A", 2), row("Tổ chức", "03004815", "B", 3)]
    r = import_vendors_from_rows(rows, user, dry_run=False)
    assert [i.message for i in r.issues] == ["Mã số thuế không hợp lệ"] and r.issues[0].row == 3
    assert Vendor.objects.count() == 0


def test_blank_name_is_issue(db, user):
    r = import_vendors_from_rows([row("Tổ chức", "0300481551", "  ")], user, dry_run=False)
    assert len(r.issues) == 1 and r.issues[0].column == "Tên nhà cung cấp"


def test_existing_vendor_updated_with_audit(db, user):
    Vendor.objects.create(code="0300481551", tax_code="0300481551", name="Tên cũ", kind="ORG", status="SUSPENDED")
    r = import_vendors_from_rows([row("Cá nhân", "0300481551", "Tên mới")], user, dry_run=False)
    assert r.ok and r.created["vendors"] == 0 and r.created["vendors_updated"] == 1
    v = Vendor.objects.get()
    assert v.name == "Tên mới" and v.kind == "INDIVIDUAL" and v.status == "SUSPENDED"
    ev = AuditEvent.objects.get(action="vendor.updated")
    assert ev.changes["name"] == ["Tên cũ", "Tên mới"]


def test_existing_vendor_unchanged_no_audit(db, user):
    Vendor.objects.create(code="0300481551", tax_code="0300481551", name="A", kind="ORG")
    r = import_vendors_from_rows([row("Tổ chức", "0300481551", "A")], user, dry_run=False)
    assert r.ok and r.created["vendors_updated"] == 0
    assert not AuditEvent.objects.filter(action="vendor.updated").exists()


# --- tích hợp vào import_budget_workbook ---

@pytest.fixture
def demo_xlsx(tmp_path):
    gen.main(["--out", str(tmp_path)])
    return tmp_path / gen.WORKBOOK_NAME


def _budget(path, user, **kw):
    org = OrgUnitFactory(code="ADM-DEMO")
    return import_budget_workbook(
        path, budget_unit_code="DEMO", year=2026, user=user, managing_org_unit_code=org.code, **kw
    )


def test_demo_workbook_imports_vendors_in_same_pass(demo_xlsx, user):
    r = _budget(demo_xlsx, user, dry_run=False)
    assert r.ok and r.created["vendors"] == 10
    assert Vendor.objects.count() == 10 and BudgetEntry.objects.exists()
    assert list(AuditEvent.objects.order_by("-id").values_list("action", flat=True)[:1]) == ["budget.imported"]


def test_demo_workbook_vendor_dry_run(demo_xlsx, user):
    r = _budget(demo_xlsx, user, dry_run=True)
    assert r.ok and r.created["vendors"] == 10 and Vendor.objects.count() == 0


def test_vendor_issue_blocks_budget_write(tmp_path, user):
    from openpyxl import load_workbook

    p = tmp_path / "bad.xlsx"
    gen.main(["--out", str(tmp_path)])
    wb = load_workbook(tmp_path / gen.WORKBOOK_NAME)
    wb["L9_Code"].append(["Tổ chức", "123", "Sai MST"])
    wb.save(p)
    r = _budget(p, user, dry_run=False)
    assert any(i.sheet == "L9_Code" and i.message == "Mã số thuế không hợp lệ" for i in r.issues)
    assert Vendor.objects.count() == 0 and BudgetEntry.objects.count() == 0


def test_workbook_without_l9_still_imports(tmp_path, user):
    from openpyxl import load_workbook

    p = tmp_path / "nol9.xlsx"
    gen.main(["--out", str(tmp_path)])
    wb = load_workbook(tmp_path / gen.WORKBOOK_NAME)
    del wb["L9_Code"]
    wb.save(p)
    r = _budget(p, user, dry_run=False)
    assert r.ok and Vendor.objects.count() == 0 and BudgetEntry.objects.exists()


def test_import_vendors_command(demo_xlsx, db, capsys):
    from django.core.management import call_command

    call_command("import_vendors", str(demo_xlsx))
    out = capsys.readouterr().out
    assert "Chạy thử" in out and Vendor.objects.count() == 0
    call_command("import_vendors", str(demo_xlsx), "--commit")
    assert Vendor.objects.count() == 10


def test_numeric_tax_cell_rejected(db, user):
    r = import_vendors_from_rows([row("Cá nhân", 1000000019, "Ông B")], user, dry_run=False)
    assert [i.message for i in r.issues] == ["Mã số thuế phải nhập dạng văn bản (mất số 0 đầu)"]
    assert Vendor.objects.count() == 0


def test_kind_label_normalized(db, user):
    import unicodedata

    label = unicodedata.normalize("NFD", " TỔ CHỨC ")
    import_vendors_from_rows([row(label, "0300481551", "A")], user, dry_run=False)
    assert Vendor.objects.get().kind == "ORG"


def test_dry_run_updated_count_matches_apply(db, user):
    Vendor.objects.create(code="0300481551", tax_code="0300481551", name="Cũ", kind="ORG")
    Vendor.objects.create(code="0300481552", tax_code="0300481552", name="Giữ", kind="ORG")
    rows = [row("Tổ chức", "0300481551", "Mới", 2), row("Tổ chức", "0300481552", "Giữ", 3),
            row("Tổ chức", "0300481553", "Thêm", 4)]
    dry = import_vendors_from_rows(rows, user)
    real = import_vendors_from_rows(rows, user, dry_run=False)
    assert dry.created == real.created == {"vendors": 1, "vendors_updated": 1}
    assert AuditEvent.objects.filter(action="vendor.updated").count() == 1


def test_change_status_same_status_noop(db, user):
    v = Vendor.objects.create(code="1", tax_code="0300481551", name="A", status="ACTIVE")
    stale = Vendor.objects.get(pk=v.pk)
    Vendor.objects.filter(pk=v.pk).update(status="SUSPENDED")
    stale.change_status("SUSPENDED", user, "x")
    assert stale.status == "SUSPENDED"
    assert not AuditEvent.objects.filter(action="vendor.status_changed").exists()
