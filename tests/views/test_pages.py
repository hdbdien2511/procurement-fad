"""Kiểm thử màn hình nghiệp vụ đợt 1: quyền truy cập, CSRF, hiển thị tiền, xử lý hàng loạt."""

import re
from decimal import Decimal

import pytest

from apps.accounts import roles as R
from apps.requisitions.services import submit
from tests.factories import UserFactory
from tests.views.conftest import advance_to_fad, login
from tests.requisitions.conftest import make_requisition
from tests.workflow.conftest import grant

pytestmark = pytest.mark.django_db

LOGIN_PREFIX = "/dang-nhap/"


def pages(scene):
    """`(phương thức, đường dẫn, vai trò bắt buộc)` của mọi màn hình nghiệp vụ đợt 1."""
    req, line, task = scene.submitted.pk, scene.budget.line.pk, scene.fad_task.pk
    bcr, dele = scene.bcr.pk, scene.delegation.pk
    return [
        ("get", "/", None),
        ("get", f"/viec/{task}/", None),
        ("post", "/viec/xu-ly-hang-loat/", None),
        ("get", "/to-trinh/", None),
        ("get", "/to-trinh/xuat/", None),
        ("get", "/to-trinh/tao/", None),
        ("get", f"/to-trinh/{req}/", None),
        ("post", f"/to-trinh/{req}/nop/", None),
        ("post", f"/to-trinh/{req}/sao-chep/", None),
        ("post", f"/to-trinh/{req}/sua-lai/", None),
        ("post", f"/to-trinh/{req}/huy/", None),
        ("post", f"/to-trinh/{req}/giu-cho-lai/", None),
        ("post", f"/to-trinh/{req}/chung-tu/", None),
        ("get", f"/to-trinh/{req}/tien-kiem/", R.FAD_PRECHECK),
        ("post", f"/to-trinh/{req}/tien-kiem/xu-ly/", R.FAD_PRECHECK),
        ("get", "/ngan-sach/", None),
        ("get", "/ngan-sach/xuat/", None),
        ("get", f"/ngan-sach/{line}/so-cai/", None),
        ("get", "/ngan-sach/nhap-excel/", R.FAD_BUDGET_ADMIN),
        ("post", "/ngan-sach/nhap-excel/", R.FAD_BUDGET_ADMIN),
        ("get", "/ngan-sach/de-nghi/", None),
        ("get", "/ngan-sach/de-nghi/tao/", None),
        ("get", f"/ngan-sach/de-nghi/{bcr}/", None),
        ("post", f"/ngan-sach/de-nghi/{bcr}/nop/", None),
        ("get", "/nha-cung-cap/", None),
        ("get", "/nha-cung-cap/xuat/", None),
        ("get", "/nha-cung-cap/nhap-excel/", R.FAD_BUDGET_ADMIN),
        ("get", "/uy-quyen/", None),
        ("post", f"/uy-quyen/{dele}/thu-hoi/", None),
        ("get", "/tim-kiem/?q=may", None),
        ("get", "/nhat-ky/", R.AUDITOR),
        ("get", "/nhat-ky/xuat/", R.AUDITOR),
        ("get", "/cai-dat/", R.SYS_ADMIN),
        ("post", "/cai-dat/tham-so/", R.SYS_ADMIN),
        ("post", "/cai-dat/ty-gia/", R.SYS_ADMIN),
        ("get", "/quan-tri/", R.SYS_ADMIN),
    ]


# --- chưa đăng nhập -------------------------------------------------------------------------------

def test_anonymous_redirected_to_login(client, scene):
    for method, url, _ in pages(scene):
        response = getattr(client, method)(url)
        assert response.status_code == 302, f"{method.upper()} {url} -> {response.status_code}"
        assert response["Location"].startswith(LOGIN_PREFIX), f"{method.upper()} {url} -> {response['Location']}"


# --- sai vai trò ----------------------------------------------------------------------------------

def test_wrong_role_forbidden(client, scene, requester):
    login(client, requester)
    checked = 0
    for method, url, role in pages(scene):
        if role is None:
            continue
        checked += 1
        response = getattr(client, method)(url)
        assert response.status_code == 403, f"{method.upper()} {url} -> {response.status_code}"
    assert checked >= 8


def test_auditor_and_fad_can_read_audit_log(client, scene, org):
    auditor = grant(UserFactory(username="kiem_toan"), R.AUDITOR)
    login(client, auditor)
    assert client.get("/nhat-ky/").status_code == 200
    login(client, org.fad)
    assert client.get("/nhat-ky/").status_code == 200


# --- quyền xem từng hồ sơ -------------------------------------------------------------------------

def test_requisition_detail_visible_to_creator_but_not_outsider(client, scene, requester, org):
    login(client, requester)
    assert client.get(f"/to-trinh/{scene.submitted.pk}/").status_code == 200

    outsider = UserFactory(username="nguoi_ngoai", org_unit=org.dti)
    login(client, outsider)
    assert client.get(f"/to-trinh/{scene.submitted.pk}/").status_code == 403


# --- hiển thị tiền --------------------------------------------------------------------------------

def test_detail_shows_money_grouped_and_in_words(client, scene, requester):
    login(client, requester)
    body = client.get(f"/to-trinh/{scene.submitted.pk}/").content.decode()
    assert "50.000.000" in body
    assert "Năm mươi triệu đồng" in body


# --- CSRF -----------------------------------------------------------------------------------------

FORM_RE = re.compile(r"<form[^>]*method=\"post\"[^>]*>(.*?)</form>", re.S | re.I)


def test_every_post_form_has_csrf_token(client, scene, org):
    power = UserFactory(username="toan_quyen")
    for role in (R.FAD_PRECHECK, R.FAD_BUDGET_ADMIN, R.SYS_ADMIN, R.AUDITOR):
        grant(power, role)
    login(client, power)
    urls = [url for method, url, _ in pages(scene) if method == "get" and "xuat" not in url]
    seen = 0
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, f"GET {url} -> {response.status_code}"
        body = response.content.decode()
        for inner in FORM_RE.findall(body):
            seen += 1
            assert "csrfmiddlewaretoken" in inner, f"form thiếu CSRF tại {url}"
    assert seen >= 5


# --- xử lý hàng loạt ------------------------------------------------------------------------------

def test_bulk_action_reports_per_item_results(client, org, budget, in_budget_policy, requester):
    fad = org.fad
    tasks = []
    for created_by in (requester, requester, fad):
        req = make_requisition(org, budget.line, 10_000_000, created_by=created_by, requester=requester)
        submit(req, requester)
        tasks.append(advance_to_fad(req.workflow_instances().get()))

    login(client, fad)
    response = client.post(
        "/viec/xu-ly-hang-loat/",
        {"ids": [str(t.pk) for t in tasks], "decision": "APPROVE", "comment": "Đạt"},
        follow=True,
    )
    body = response.content.decode()
    assert "Không được duyệt hồ sơ do chính mình lập" in body
    assert "2" in body
    statuses = [t.__class__.objects.get(pk=t.pk).status for t in tasks]
    assert statuses.count("APPROVED") == 2
    assert statuses.count("PENDING") == 1


# --- vài luồng thuận ------------------------------------------------------------------------------

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_exports_return_xlsx(client, scene, org):
    login(client, org.fad)
    for url in ("/to-trinh/xuat/", "/ngan-sach/xuat/", "/nha-cung-cap/xuat/", "/nhat-ky/xuat/"):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response["Content-Type"] == XLSX, url
        assert response.content[:2] == b"PK", url


def test_create_requisition_draft(client, scene, requester, budget):
    login(client, requester)
    response = client.post("/to-trinh/tao/", {
        "title": "Mua bàn ghế",
        "procurement_type": "BAU",
        "necessity": "Thay bàn hỏng",
        "currency": "VND",
        "service_start": "2026-01-01",
        "months": "1",
        "quote_exception_reason": "Chỉ có một nhà cung cấp",
        "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "1", "lines-MAX_NUM_FORMS": "1000",
        "lines-0-description": "Bàn làm việc", "lines-0-quantity": "2",
        "lines-0-unit_price": "1000000", "lines-0-vat_rate": "0",
        "fundings-TOTAL_FORMS": "1", "fundings-INITIAL_FORMS": "0",
        "fundings-MIN_NUM_FORMS": "1", "fundings-MAX_NUM_FORMS": "1000",
        "fundings-0-budget_line": str(budget.line.pk), "fundings-0-amount_vnd": "2000000",
    }, follow=True)
    assert response.status_code == 200
    from apps.requisitions.models import Requisition

    created = Requisition.objects.filter(title="Mua bàn ghế").get()
    assert created.status == "DRAFT" and created.created_by_id == requester.pk
    assert created.lines.count() == 1 and created.fundings.count() == 1
    assert "2.000.000" in response.content.decode()


def test_settings_params_saved(client, scene, org):
    login(client, org.sysadmin)
    response = client.post("/cai-dat/tham-so/", {
        "split_window_days": "45", "annual_fixed_cost_vnd": "100000000000",
        "cumulative_scope": "UNIT", "max_upload_mb": "30",
    }, follow=True)
    assert response.status_code == 200
    from apps.core.services import get_setting

    assert get_setting("split_window_days") == 45
    assert get_setting("cumulative_scope") == "UNIT"


def test_settings_reject_bad_parameter(client, scene, org):
    login(client, org.sysadmin)
    body = client.post("/cai-dat/tham-so/", {"split_window_days": "ba mươi"}, follow=True).content.decode()
    assert "phải là số nguyên" in body
    from apps.core.services import get_setting

    assert get_setting("split_window_days") == 30


def test_exchange_rate_added(client, scene, org):
    login(client, org.sysadmin)
    client.post("/cai-dat/ty-gia/", {"currency": "usd", "date": "2026-11-27", "rate": "25400.5"}, follow=True)
    from apps.core.models import ExchangeRate

    assert ExchangeRate.objects.get(currency="USD", date="2026-11-27").rate == Decimal("25400.5000")


def test_budget_change_prefilled_from_blocked_requisition(client, org, budget, in_budget_policy, requester):
    """Tờ trình vượt ngân sách khả dụng → tạo sẵn đề nghị bổ sung từ chính màn hình đề nghị."""
    req = make_requisition(org, budget.line, 500_000_000)
    login(client, requester)
    response = client.post("/ngan-sach/de-nghi/tao/", {"tu_to_trinh": str(req.pk)}, follow=True)
    assert response.status_code == 200
    from apps.budget_changes.models import BudgetChangeRequest

    created = BudgetChangeRequest.objects.filter(requisition=req).get()
    assert created.kind == "SUPPLEMENT" and created.amount_vnd == Decimal("300000000")


def test_task_detail_action_records_decision(client, scene, org):
    task = scene.fad_task
    login(client, org.fad)
    response = client.post(f"/viec/{task.pk}/xu-ly/", {"decision": "RETURN", "comment": "Thiếu báo giá"},
                           follow=True)
    assert response.status_code == 200
    task.refresh_from_db()
    assert task.status == "RETURNED" and task.comment == "Thiếu báo giá"
    scene.submitted.refresh_from_db()
    assert scene.submitted.status == "RETURNED"


def test_action_shows_vietnamese_error_instead_of_500(client, scene, requester):
    """Nộp tờ trình đã nộp → thông báo tiếng Việt, không phải lỗi máy chủ."""
    login(client, requester)
    body = client.post(f"/to-trinh/{scene.submitted.pk}/nop/", follow=True).content.decode()
    assert "Tờ trình đang được duyệt" in body


def _vendor_workbook() -> bytes:
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "L9_Code"
    ws.append(["Loại hình", "Mã số thuế", "Tên nhà cung cấp"])
    ws.append(["Tổ chức", "0101243649", "Công ty TNHH Thiết bị ABC"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_vendor_import_dry_run_then_confirm(client, scene, budget):
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.vendors.models import Vendor

    login(client, budget.admin)
    data = _vendor_workbook()
    upload = SimpleUploadedFile("ncc.xlsx", data)
    body = client.post("/nha-cung-cap/nhap-excel/", {"file": upload}).content.decode()
    assert "Tệp hợp lệ" in body and not Vendor.objects.filter(tax_code="0101243649").exists()

    upload = SimpleUploadedFile("ncc.xlsx", data)
    body = client.post("/nha-cung-cap/nhap-excel/", {"file": upload, "confirm": "1"}).content.decode()
    assert "Đã nhập danh sách nhà cung cấp" in body
    assert Vendor.objects.filter(tax_code="0101243649").exists()


def test_budget_import_requires_file_and_pending(client, scene, budget):
    login(client, budget.admin)
    body = client.post("/ngan-sach/nhap-excel/", {"budget_unit_code": "ITD", "year": "2026"}).content.decode()
    assert "Vui lòng chọn tệp Excel ngân sách" in body
    response = client.post("/ngan-sach/nhap-excel/", {"action": "confirm"}, follow=True)
    assert "Không còn tệp đang chờ" in response.content.decode()


# --- sửa theo review ------------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _png(name="bao-gia.png"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile(name, PNG, content_type="image/png")


def _doc_count(req):
    from django.contrib.contenttypes.models import ContentType

    from apps.documents.models import Document

    return Document.objects.filter(
        content_type=ContentType.objects.get_for_model(req), object_id=str(req.pk)
    ).count()


def test_requisition_upload_only_by_owner(client, scene, org, requester):
    """Quyền xem tờ trình (FAD, Kiểm toán, cùng đơn vị, người duyệt) KHÔNG cho phép đính kèm chứng từ."""
    req = scene.draft
    colleague = UserFactory(username="dong_nghiep", org_unit=org.req_unit)  # cùng đơn vị đề nghị
    auditor = grant(UserFactory(username="kiem_toan_2"), R.AUDITOR)
    outsider = UserFactory(username="nguoi_ngoai_2", org_unit=org.dti)

    for user, expected in ((outsider, 403), (auditor, 302), (colleague, 302)):
        login(client, user)
        response = client.post(f"/to-trinh/{req.pk}/chung-tu/", {"doc_type": "QUOTE", "file": _png()})
        assert response.status_code == expected, user.username
    assert _doc_count(req) == 0

    login(client, colleague)
    body = client.post(f"/to-trinh/{req.pk}/chung-tu/",
                       {"doc_type": "QUOTE", "file": _png()}, follow=True).content.decode()
    assert "Chỉ người lập hoặc người đề nghị được đính kèm chứng từ" in body


def test_requisition_owner_can_upload_on_draft_only(client, scene, requester, approved_req):
    login(client, requester)
    response = client.post(f"/to-trinh/{scene.draft.pk}/chung-tu/",
                           {"doc_type": "QUOTE", "file": _png()}, follow=True)
    assert "Đã tải chứng từ lên" in response.content.decode()
    assert _doc_count(scene.draft) == 1

    body = client.post(f"/to-trinh/{approved_req.pk}/chung-tu/",
                       {"doc_type": "QUOTE", "file": _png()}, follow=True).content.decode()
    assert "Chỉ đính kèm chứng từ khi tờ trình ở trạng thái nháp hoặc bị trả lại" in body
    assert _doc_count(approved_req) == 0


def test_imports_reject_non_excel_file(client, scene, budget):
    from django.core.files.uploadedfile import SimpleUploadedFile

    login(client, budget.admin)
    for url, extra in (("/nha-cung-cap/nhap-excel/", {}),
                       ("/ngan-sach/nhap-excel/", {"budget_unit_code": "ITD", "year": "2026"})):
        upload = SimpleUploadedFile("gia-mao.xlsx", b"khong phai excel")
        response = client.post(url, {"file": upload, **extra})
        assert response.status_code == 200, url
        assert "Tệp không phải định dạng Excel (.xlsx) hợp lệ." in response.content.decode(), url


def test_admin_refuses_change_to_used_policy(client, scene, org, in_budget_policy):
    """Chính sách đã có hồ sơ dùng: trang quản trị hiện lỗi, không báo "thành công", không đổi gì."""
    login(client, org.sysadmin)
    url = f"/quan-tri/workflow/approvalpolicy/{in_budget_policy.pk}/change/"
    response = client.post(url, {
        "code": "DOI_MA", "subject_kind": in_budget_policy.subject_kind,
        "version": str(in_budget_policy.version), "effective_from": "2026-01-01", "is_active": "on",
    })
    body = response.content.decode()
    assert "Chính sách đã được sử dụng; hãy tạo phiên bản mới" in body
    assert "thành công" not in body
    in_budget_policy.refresh_from_db()
    assert in_budget_policy.code == "TRONG_NGAN_SACH"


def _create_delegation(client, delegate, *, start, end, letter=True):
    data = {"delegate": str(delegate.pk), "start_date": start, "end_date": end}
    if letter:
        data["letter"] = _png("giay-uy-quyen.png")
    return client.post("/uy-quyen/", data, follow=True)


def test_failed_delegation_leaves_no_document(client, scene, org, requester):
    from apps.documents.models import Document
    from apps.workflow.models import Delegation

    before = Document.objects.count()
    login(client, requester)
    body = _create_delegation(client, org.dept_head, start="2026-12-10", end="2026-12-01").content.decode()
    assert "Ngày kết thúc phải từ ngày bắt đầu trở đi" in body
    assert Document.objects.count() == before
    assert not Delegation.objects.filter(delegator=requester, start_date="2026-12-10").exists()


def test_delegation_letter_readable_by_both_parties_only(client, scene, org, requester):
    from apps.workflow.models import Delegation

    login(client, requester)
    assert "Đã tạo uỷ quyền duyệt thay" in _create_delegation(
        client, org.dept_head, start="2026-12-01", end="2026-12-10"
    ).content.decode()
    letter = Delegation.objects.filter(delegator=requester, start_date="2026-12-01").get().letter
    assert letter is not None

    url = f"/chung-tu/{letter.pk}/xem/"
    for user in (requester, org.dept_head):
        login(client, user)
        assert client.get(url).status_code == 200, user.username
    login(client, UserFactory(username="khong_lien_quan", org_unit=org.dti))
    assert client.get(url).status_code == 403
