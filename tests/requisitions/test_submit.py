from datetime import date
from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.budget.ledger import InsufficientBudget
from apps.core.models import ExchangeRate, NumberSequence
from apps.requisitions.models import Requisition, RequisitionLine
from apps.requisitions.services import SubmitBlocked, check_budget, submit, validate_for_submit
from apps.vendors.models import Vendor
from apps.workflow.models import RUNNING, WorkflowInstance
from tests.requisitions.conftest import make_requisition


@pytest.fixture
def draft_req_over_budget(org, budget, in_budget_policy):
    return make_requisition(org, budget.line, 250_000_000)


@pytest.fixture
def usd_rate(db):
    ExchangeRate.objects.create(currency="USD", date=date(2026, 11, 1), rate=Decimal("25000.5000"))
    return ExchangeRate.objects.create(currency="USD", date=date(2026, 11, 20), rate=Decimal("25400.0000"))


@pytest.fixture
def draft_req_usd(org, budget, in_budget_policy, usd_rate):
    # 1.000,50 USD x 25.400 = 25.412.700 đ (tỷ giá gần nhất trước ngày nộp 27/11/2026)
    return make_requisition(org, budget.line, "1000.50", currency="USD", funding=25_412_700)


def test_submit_blocked_without_quotes_or_reason(db, draft_req, requester):
    with pytest.raises(SubmitBlocked) as e:
        submit(draft_req, requester)
    assert "03 báo giá" in " ".join(e.value.errors)
    draft_req.refresh_from_db()
    assert draft_req.status == "DRAFT" and draft_req.number is None


def test_submit_blocked_when_no_budget_offers_change_request(db, draft_req_over_budget, requester):
    with pytest.raises(InsufficientBudget) as e:
        submit(draft_req_over_budget, requester)
    assert e.value.shortfalls[0][1] == Decimal("50000000")
    draft_req_over_budget.refresh_from_db()
    assert (draft_req_over_budget.status, draft_req_over_budget.number) == ("DRAFT", None)
    assert draft_req_over_budget.total_vnd == 0  # không ghi gì
    assert not WorkflowInstance.objects.exists()
    assert not NumberSequence.objects.filter(prefix="TT").exclude(last=0).exists()  # chưa tiêu số


def test_usd_converted_at_submit_date(db, draft_req_usd, requester, usd_rate):
    submit(draft_req_usd, requester)
    draft_req_usd.refresh_from_db()
    assert draft_req_usd.fx_rate == Decimal("25400.0000")
    assert draft_req_usd.total_original == Decimal("1000.50")
    assert draft_req_usd.total_vnd == Decimal("25412700")


def test_submit_assigns_number_and_starts_workflow(db, ready_req, requester):
    instance = submit(ready_req, requester)
    ready_req.refresh_from_db()
    assert ready_req.number == "TT-2026-00001"
    assert ready_req.status == "IN_APPROVAL"
    assert ready_req.total_vnd == Decimal("50000000")
    assert instance.status == RUNNING and instance.rule.label == "<200tr"
    ctx = instance.snapshot["context"]
    assert ctx["amount_vnd"] == "50000000"
    assert ctx["budget_unit_ids"] == [ready_req.fundings.get().budget_line.budget_unit_id]
    assert ctx["requester_unit_id"] == ready_req.requester_unit_id
    last = AuditEvent.objects.order_by("-id").first()
    assert (last.action, last.object_id) == ("requisition.submitted", str(ready_req.pk))


def test_line_amount_includes_vat(db, org, budget, in_budget_policy):
    req = make_requisition(org, budget.line, 0)
    line = RequisitionLine(requisition=req, description="x", quantity=Decimal("3"),
                           unit_price=Decimal("333.33"), vat_rate=Decimal("8"))
    assert line.amount == Decimal("1079.99")  # 999,99 x 1,08 = 1079,9892


def test_only_requester_can_submit(db, ready_req, org):
    with pytest.raises(SubmitBlocked):
        submit(ready_req, org.dept_head)


def test_submit_blocked_while_workflow_running(db, submitted_req, requester):
    Requisition.objects.filter(pk=submitted_req.pk).update(status="DRAFT")  # trạng thái lệch bất thường
    with pytest.raises(SubmitBlocked) as e:
        submit(submitted_req, requester)
    assert e.value.errors == ["Tờ trình đang được duyệt"]


def test_validate_messages(db, org, budget, in_budget_policy):
    req = make_requisition(org, budget.line, 50_000_000, funding=40_000_000)
    req.vendor = Vendor.objects.create(code="V1", tax_code="0101", name="NCC", status="SUSPENDED")
    req.save()
    errors = validate_for_submit(req)
    assert "Tổng phân bổ ngân sách (40.000.000) khác tổng tờ trình (50.000.000)" in errors
    assert "Nhà cung cấp không ở trạng thái được phép giao dịch" in errors

    req.lines.all().delete()
    assert "Cần ít nhất một dòng hàng" in validate_for_submit(req)

    req.service_start = date(2027, 1, 1)
    req.status = "RETURNED"
    errors = validate_for_submit(req)
    assert "Dòng ngân sách phải thuộc năm của ngày bắt đầu dịch vụ" in errors
    assert "Chỉ nộp được tờ trình ở trạng thái nháp" in errors


def test_validate_ok_with_three_quotes(db, org, budget, in_budget_policy):
    from django.contrib.contenttypes.models import ContentType

    from apps.documents.models import QUOTE, Document

    req = make_requisition(org, budget.line, 50_000_000, quote_reason="")
    for i in range(3):
        Document.objects.create(
            content_type=ContentType.objects.get_for_model(req), object_id=str(req.pk), doc_type=QUOTE,
            original_name=f"bg{i}.pdf", stored_path=f"x/{i}.pdf", size=1, mime="application/pdf",
            sha256="0" * 64, uploaded_by=org.requester,
        )
    assert validate_for_submit(req) == []


def test_check_budget_warns_for_next_year_portion(db, org, budget, in_budget_policy):
    # 120tr, 12 tháng từ 07/2026: 60tr năm 2026 (đủ), 60tr năm 2027 (chưa có ngân sách) → cảnh báo
    req = make_requisition(org, budget.line, 120_000_000, service_start=date(2026, 7, 1), months=12)
    req.total_vnd = Decimal("120000000")
    result = check_budget(req)
    assert result.ok and result.shortfalls == []
    assert len(result.warnings) == 1 and "Năm 2027" in result.warnings[0]


def test_header_form_offers_only_active_vendors(db):
    from apps.requisitions.forms import RequisitionForm

    active = Vendor.objects.create(code="V1", tax_code="0101", name="NCC A", status="ACTIVE")
    Vendor.objects.create(code="V2", tax_code="0102", name="NCC B", status="BLACKLISTED")
    form = RequisitionForm()
    assert list(form.fields["vendor"].queryset) == [active]
    assert form.fields["service_start"].label == "Ngày bắt đầu dịch vụ"
    assert "status" not in form.fields and "number" not in form.fields
