"""Kịch bản nghiệm thu đợt 1 (spec mục 10, dòng "1. Nền tảng") chạy qua TẦNG DỊCH VỤ.

Hai hành trình, cả hai đều dựng dữ liệu bằng chính lệnh `seed_demo` (dữ liệu giả đã commit):

1. `test_dot1_end_to_end`: tờ trình USD, 2 nguồn ngân sách, 3 báo giá → nộp (> 2 tỷ → luồng BMS)
   → người lập không tự duyệt được → duyệt thay GĐĐH → 2 nhánh đơn vị quản lý ngân sách →
   ý kiến tham vấn → FAD tiền kiểm → biên bản họp + duyệt tại cuộc họp → đã duyệt, giữ chỗ
   ngân sách đúng, chuỗi audit liền mạch, email "cần duyệt".
2. `test_blocked_budget_journey`: tờ trình vượt ngân sách → chặn khi nộp → tạo sẵn đề nghị bổ sung
   → đề nghị được duyệt (ghi tăng ngân sách) → tờ trình nộp và duyệt được, giữ chỗ đúng.
"""

import json
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts import roles as R
from apps.accounts.models import OrgUnit, RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.audit.service import verify_chain
from apps.budget import ledger
from apps.budget.ledger import InsufficientBudget
from apps.budget.models import RESERVE, BudgetEntry, BudgetLine
from apps.budget_changes import models as bc_models
from apps.budget_changes import services as bc_services
from apps.core.management.commands import seed_demo
from apps.core.management.commands.seed_demo import demo_lines
from apps.core.models import ExchangeRate, Setting
from apps.documents.models import MEETING_MINUTES, QUOTE
from apps.notifications import outbox
from apps.requisitions import services as req_services
from apps.requisitions.models import APPROVED, Requisition, RequisitionFunding, RequisitionLine
from apps.workflow import delegation, engine, resolver
from apps.workflow.exceptions import NotAllowed
from apps.workflow.models import ApprovalPolicy
from tests.factories import UserFactory
from tests.workflow.conftest import grant

TODAY = "2026-11-27 10:00:00+07:00"  # ngày nộp: quyết định số hồ sơ và tỷ giá áp dụng
SERVICE_START = date(2026, 12, 1)
USD_TOTAL = Decimal("100000.00")  # × 25.460 = 2.546.000.000 đ → luồng "> 2 tỷ"
TOTAL_VND = Decimal("2546000000")
ITD_SHARE = Decimal("1527600000")  # 60%
ADM_SHARE = Decimal("1018400000")  # 40%
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(autouse=True)
def frozen_today():
    with freeze_time(TODAY, tick=True):
        yield


@pytest.fixture
def seeded(db):
    """Dữ liệu demo do `seed_demo` tạo (người dùng, vai trò, ngân sách 2026, chính sách, tỷ giá)."""
    call_command("seed_demo", stdout=StringIO(), stderr=StringIO())
    users = {u.username: u for u in User.objects.all()}
    return SimpleNamespace(
        requester=users["nv.mau1"],
        dept_head=users["tp.mau1"],
        gddh=users["gddh.mau"],
        deputy=users["gdnv.mau"],
        owner_itd=users["bo.itd"],
        owner_adm=users["bo.adm"],
        consultant=users["tv.dti"],
        fad=users["fad.tienkiem"],
        bms=users["thuky.bms"],
        lines=demo_lines(),
        consult_unit=OrgUnit.objects.get(code="DTI-DEMO"),
    )


def png(name):
    return SimpleUploadedFile(name, PNG, content_type="image/png")


def make_requisition(seeded, *, currency, unit_price, funding, title="Mua thiết bị demo"):
    """Tờ trình nháp: một dòng hàng, các nguồn ngân sách `funding = [(dòng, số tiền VND)]`."""
    req = Requisition.objects.create(
        title=title, requester=seeded.requester, created_by=seeded.requester,
        procurement_type="PROJECT", necessity="Thay thế thiết bị hết khấu hao",
        currency=currency, service_start=SERVICE_START, months=1,
    )
    RequisitionLine.objects.create(
        requisition=req, description="Thiết bị", quantity=Decimal("1"),
        unit_price=unit_price, vat_rate=Decimal("0"),
    )
    for line, amount in funding:
        RequisitionFunding.objects.create(requisition=req, budget_line=line, amount_vnd=amount)
    return req


def task(instance, kind, **filters):
    instance.refresh_from_db()
    t = instance.tasks.get(kind=kind, status="PENDING", **filters)
    t.instance = instance
    return t


def approve(instance, kind, user, **filters):
    return engine.act(task(instance, kind, **filters), user, "APPROVE")


def req_audit_actions(req):
    return set(
        AuditEvent.objects.filter(object_type=Requisition._meta.label_lower, object_id=str(req.pk))
        .values_list("action", flat=True)
    )


def sent_subjects(mailoutbox):
    outbox.process_due(timezone.now())
    return [m.subject for m in mailoutbox]


# --- hành trình 1: tờ trình USD, 2 nguồn, luồng "> 2 tỷ" ----------------------------------------------

def test_dot1_end_to_end(seeded, mailoutbox):
    line_itd, line_adm = seeded.lines["ITD"], seeded.lines["ADM"]
    req = make_requisition(
        seeded, currency="USD", unit_price=USD_TOTAL,
        funding=[(line_itd, ITD_SHARE), (line_adm, ADM_SHARE)],
    )
    req.consult_units.set([seeded.consult_unit])
    for i in range(1, 4):
        req_services.attach_document(req, seeded.requester, png(f"bao-gia-{i}.png"), QUOTE)

    instance = req_services.submit(req, seeded.requester)
    req.refresh_from_db()
    assert req.total_vnd == TOTAL_VND and req.fx_rate == Decimal("25460.0000")
    assert instance.snapshot["rule"]["label"] == ">2ty"

    # phân tách nhiệm vụ: người lập không tự duyệt bước của hồ sơ mình (ở đây người lập cũng không
    # giữ vai trò GĐĐH; trường hợp "giữ đúng vai trò của bước mà vẫn bị chặn" xem
    # test_requester_holding_the_step_role_is_still_barred)
    with pytest.raises(NotAllowed, match="do chính mình lập"):
        engine.act(task(instance, "PROPOSE"), seeded.requester, "APPROVE")

    # duyệt thay GĐĐH theo uỷ quyền 3 ngày
    today = timezone.localdate()
    delegation.create_delegation(
        seeded.gddh, seeded.deputy, start_date=today, end_date=today + timedelta(days=3),
        subject_kinds=["requisition"],
    )
    propose = approve(instance, "PROPOSE", seeded.deputy)
    assert propose.on_behalf_of == seeded.gddh and propose.acted_by == seeded.deputy

    # hai nhánh đơn vị quản lý ngân sách chạy song song
    owners = {seeded.owner_itd: line_itd, seeded.owner_adm: line_adm}
    assert instance.tasks.filter(kind="BUDGET_OWNER", status="PENDING").count() == 2
    for owner, line in owners.items():
        approve(instance, "BUDGET_OWNER", owner, org_unit=line.budget_unit.managing_org_unit)

    # ý kiến tham vấn (không bắt buộc) hiển thị ở màn hình tiền kiểm
    opinion = engine.act(task(instance, "CONSULT"), seeded.consultant, "COMMENT", "Cấu hình phù hợp")
    assert opinion.status == "COMMENTED" and opinion.comment == "Cấu hình phù hợp"

    approve(instance, "FAD_PRECHECK", seeded.fad)

    # bước duyệt tại cuộc họp đòi biên bản họp đính kèm
    with pytest.raises(NotAllowed, match="biên bản họp"):
        approve(instance, "MEETING", seeded.bms)
    req_services.attach_document(req, seeded.bms, png("bien-ban-bms.png"), MEETING_MINUTES)
    approve(instance, "MEETING", seeded.bms)

    instance.refresh_from_db()
    req.refresh_from_db()
    assert instance.status == "APPROVED"
    assert req.status == APPROVED

    reserved = ledger.balance(line_itd).reserved + ledger.balance(line_adm).reserved
    assert reserved == req.total_vnd == TOTAL_VND
    assert ledger.balance(line_itd).reserved == ITD_SHARE

    # bút toán giữ chỗ gắn ĐÚNG tờ trình này (không phải bút toán của dữ liệu seed)
    entries = BudgetEntry.objects.filter(
        source_type=Requisition._meta.label_lower, source_id=str(req.pk), kind=RESERVE
    )
    assert {(e.line_id, e.period, e.amount) for e in entries} == {
        (line_itd.pk, date(2026, 12, 1), ITD_SHARE), (line_adm.pk, date(2026, 12, 1), ADM_SHARE)
    }

    assert verify_chain() == []
    assert {
        "requisition.submitted", "workflow.started", "workflow.task_acted", "workflow.approved",
        "budget.reserved", "requisition.status_changed",
    } <= req_audit_actions(req)
    # bản audit `budget.reserved` liệt kê đúng các bút toán giữ chỗ ở trên
    reserved_event = AuditEvent.objects.get(
        action="budget.reserved", object_type=Requisition._meta.label_lower, object_id=str(req.pk)
    )
    assert sorted(Decimal(c["amount"]) for c in reserved_event.changes["entries"]) == sorted(
        [ADM_SHARE, ITD_SHARE]
    )
    assert any("cần duyệt" in subject for subject in sent_subjects(mailoutbox))


# --- phân tách nhiệm vụ: giữ đúng vai trò của bước mà vẫn không duyệt được hồ sơ của mình -------------

def test_requester_holding_the_step_role_is_still_barred(seeded):
    """Người đề nghị là Trưởng phòng Demo A — đúng vai trò của bước PROPOSE/DEPT_HEAD/REQUESTER_UNIT.

    Chỉ còn quy tắc phân tách nhiệm vụ chặn họ, nên khẳng định dưới đây sẽ đỏ nếu quy tắc đó mất.
    Người nộp là `nv.mau1` để bước đề nghị không bị bỏ qua (engine bỏ qua PROPOSE khi người nộp
    chính là người giữ vai trò của bước).
    """
    line = seeded.lines["ADM"]
    total = Decimal("500000000")  # nhóm 200tr–2 tỷ
    req = make_requisition(seeded, currency="VND", unit_price=total, funding=[(line, total)],
                           title="Tờ trình do Trưởng phòng đề nghị")
    Requisition.objects.filter(pk=req.pk).update(requester=seeded.dept_head)
    req.refresh_from_db()
    for i in range(1, 4):
        req_services.attach_document(req, seeded.requester, png(f"bao-gia-{i}.png"), QUOTE)

    instance = req_services.submit(req, seeded.requester)  # nv.mau1 là người lập
    assert instance.snapshot["rule"]["label"] == "200tr-2ty"
    propose = task(instance, "PROPOSE")
    assert propose.role_code == "DEPT_HEAD"
    # Trưởng phòng Demo A đúng vai trò + phạm vi của bước...
    assert resolver.role_holders(propose).filter(pk=seeded.dept_head.pk).exists()
    # ...nhưng là người đề nghị nên bị loại khỏi danh sách người xử lý và bị từ chối.
    assert not engine.candidates(propose).filter(pk=seeded.dept_head.pk).exists()
    with pytest.raises(NotAllowed, match="do chính mình lập"):
        engine.act(propose, seeded.dept_head, "APPROVE")
    with pytest.raises(NotAllowed, match="do chính mình lập"):
        engine.act(propose, seeded.requester, "APPROVE")


# --- hành trình 2: tờ trình bị chặn vì thiếu ngân sách → bổ sung ngân sách → duyệt ---------------------

def test_blocked_budget_journey(seeded):
    line = seeded.lines["ADM"]
    shortfall = Decimal("30000000")
    total = ledger.balance(line).available + shortfall
    req = make_requisition(seeded, currency="VND", unit_price=total, funding=[(line, total)],
                           title="Mua thiết bị vượt ngân sách")
    for i in range(1, 4):
        req_services.attach_document(req, seeded.requester, png(f"bao-gia-{i}.png"), QUOTE)

    with pytest.raises(InsufficientBudget) as blocked:
        req_services.submit(req, seeded.requester)
    assert [(l.pk, amount) for l, amount in blocked.value.shortfalls] == [(line.pk, shortfall)]
    req.refresh_from_db()
    assert req.status == "DRAFT" and req.number is None

    # nút "tạo sẵn đề nghị bổ sung ngân sách" (spec 4.1)
    (bcr,) = bc_services.prefill_from_shortfall(req, blocked.value.shortfalls, seeded.requester)
    assert bcr.kind == bc_models.SUPPLEMENT and bcr.amount_vnd == shortfall and bcr.to_line_id == line.pk

    bc_instance = bc_services.submit(bcr, seeded.requester)
    assert bc_instance.snapshot["rule"]["label"] == "A"
    approve(bc_instance, "PROPOSE", seeded.dept_head)
    approve(bc_instance, "FAD_PRECHECK", seeded.fad)
    approve(bc_instance, "APPROVE", seeded.gddh)
    bcr.refresh_from_db()
    assert bcr.status == bc_models.APPROVED
    assert ledger.balance(line).available == total

    instance = req_services.submit(req, seeded.requester)
    assert instance.snapshot["rule"]["label"] == "200tr-2ty"
    approve(instance, "PROPOSE", seeded.dept_head)
    approve(instance, "BUDGET_OWNER", seeded.owner_adm)
    approve(instance, "FAD_PRECHECK", seeded.fad)
    approve(instance, "APPROVE", seeded.gddh)

    req.refresh_from_db()
    assert req.status == APPROVED
    assert ledger.balance(line).reserved == req.total_vnd == total
    assert verify_chain() == []


# --- lệnh seed_demo chạy lại được --------------------------------------------------------------------

def _counts():
    from apps.accounts.models import RoleAssignment
    from apps.workflow.models import ApprovalPolicy

    return {
        "users": User.objects.count(),
        "roles": RoleAssignment.objects.count(),
        "lines": BudgetLine.objects.count(),
        "entries": BudgetEntry.objects.count(),
        "policies": ApprovalPolicy.objects.count(),
        "settings": Setting.objects.count(),
        "rates": ExchangeRate.objects.count(),
    }


def test_seed_demo_is_idempotent_and_resets(seeded):
    before = _counts()
    out = StringIO()
    call_command("seed_demo", stdout=out, stderr=StringIO())
    assert _counts() == before  # chạy lại không nhân bản dữ liệu
    assert "Tài khoản demo" in out.getvalue() and "nv.mau1" in out.getvalue()

    call_command("seed_demo", "--reset", stdout=StringIO(), stderr=StringIO())
    after = _counts()
    assert after["policies"] == before["policies"] == 2
    assert after["roles"] == before["roles"] and after["rates"] == before["rates"]
    assert after["entries"] == before["entries"]  # bút toán ngân sách lưu vĩnh viễn


# --- rào an toàn của lệnh seed_demo ------------------------------------------------------------------

def _bad_feed(tmp_path, mutate):
    """Bản copy của hris_fake.json đã bị sửa (để thử các trường hợp dữ liệu sai)."""
    data = json.loads(seed_demo.HRIS_FILE.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "hris_bad.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_unknown_org_unit_in_role_hint_fails_loudly(db, tmp_path, monkeypatch):
    """Mã đơn vị sai KHÔNG được âm thầm thành phân công toàn công ty (leo thang quyền)."""
    def mutate(data):
        for employee in data["employees"]:
            if employee["username"] == "bo.itd":
                employee["roles"][0]["org_unit_code"] = "KHONG-TON-TAI"

    monkeypatch.setattr(seed_demo, "HRIS_FILE", _bad_feed(tmp_path, mutate))
    with pytest.raises(CommandError, match="không có đơn vị 'KHONG-TON-TAI'"):
        call_command("seed_demo", stdout=StringIO(), stderr=StringIO())
    assert RoleAssignment.objects.count() == 0  # transaction bị cuộn lại, không phân quyền nửa vời


def test_refuses_database_with_non_demo_users_until_confirmed(db):
    """Chạy nhầm DATABASE_URL: lệnh từ chối và không ghi gì (vì nó vô hiệu hoá nhân viên lạ)."""
    real_user = UserFactory(username="nguoi.that", employee_code="X999")
    with pytest.raises(CommandError, match="ngoài danh sách demo"):
        call_command("seed_demo", stdout=StringIO(), stderr=StringIO())
    real_user.refresh_from_db()
    assert real_user.is_active and ApprovalPolicy.objects.count() == 0 and Setting.objects.count() == 0

    call_command("seed_demo", "--confirm", stdout=StringIO(), stderr=StringIO())
    assert ApprovalPolicy.objects.count() == 2


def test_reset_only_touches_demo_data(seeded):
    """`--reset` không chạm phân quyền / tỷ giá của người dùng ngoài danh sách demo."""
    other = grant(UserFactory(username="nguoi.khac"), R.AUDITOR)
    other_rate = ExchangeRate.objects.create(currency="USD", date=date(2026, 6, 1), rate=Decimal("26000"))

    call_command("seed_demo", "--reset", "--confirm", stdout=StringIO(), stderr=StringIO())

    assert RoleAssignment.objects.filter(user=other, role__code=R.AUDITOR).exists()
    assert ExchangeRate.objects.filter(pk=other_rate.pk).exists()
    assert ApprovalPolicy.objects.count() == 2
