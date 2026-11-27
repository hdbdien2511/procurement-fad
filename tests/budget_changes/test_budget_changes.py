from datetime import date
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from apps.accounts import roles as R
from apps.audit.models import AuditEvent
from apps.budget import ledger
from apps.budget.ledger import InsufficientBudget, post
from apps.budget.models import ADJUST, RESERVE, TRANSFER, BudgetEntry, BudgetLine
from apps.core.models import Setting
from apps.documents.models import MEETING_MINUTES, Document
from apps.notifications.models import Notification
from apps.workflow import resolver
from apps.workflow.engine import act
from tests.factories import UserFactory
from tests.requisitions.conftest import make_requisition
from tests.workflow.conftest import grant

SUPPLEMENT_REASON = "Phát sinh nhu cầu ngoài kế hoạch"


def make_change(org, to_line, amount, *, kind="SUPPLEMENT", from_line=None, start=date(2026, 1, 1), months=1,
                reason=SUPPLEMENT_REASON, requester=None, created_by=None, **extra):
    from apps.budget_changes.models import BudgetChangeRequest

    return BudgetChangeRequest.objects.create(
        kind=kind, from_line=from_line, to_line=to_line, amount_vnd=Decimal(amount), start=start, months=months,
        reason=reason, requester=requester or org.requester, created_by=created_by or requester or org.requester,
        **extra,
    )


def attach_minutes(subject, user):
    return Document.objects.create(
        content_type=ContentType.objects.get_for_model(subject), object_id=str(subject.pk),
        doc_type=MEETING_MINUTES, original_name="bien-ban.pdf", stored_path="x/bien-ban.pdf",
        size=1, mime="application/pdf", sha256="0" * 64, uploaded_by=user,
    )


def pending_task(instance):
    task = instance.tasks.filter(status="PENDING", mandatory=True).order_by("seq", "pk").first()
    if task is not None:
        task.instance = instance
    return task


def approve_all(subject):
    """Chấp thuận lần lượt mọi bước bắt buộc (đính kèm biên bản họp trước bước họp)."""
    instance = subject.workflow_instances().get(status="RUNNING")
    while (task := pending_task(instance)) is not None:
        actor = resolver.candidates(task).order_by("pk").first()
        if task.kind == "MEETING":
            attach_minutes(subject, actor)
        act(task, actor, "APPROVE")
        instance.refresh_from_db()
    subject.refresh_from_db()
    return instance


def entries_of(bcr):
    return list(
        BudgetEntry.objects.filter(source_type="budget_changes.budgetchangerequest", source_id=str(bcr.pk))
        .order_by("line_id", "period")
        .values_list("line_id", "period", "kind", "amount")
    )


@pytest.fixture
def submit():
    from apps.budget_changes.services import submit

    return submit


# --- bổ sung ngân sách ----------------------------------------------------------------------------

def test_supplement_60tr_6_months_posts_six_adjust_entries(db, org, budget, out_budget_policy, submit):
    bcr = make_change(org, budget.line, 60_000_000, start=date(2026, 1, 15), months=6)
    assert bcr.start == date(2026, 1, 1)  # chuẩn hoá về ngày đầu tháng

    instance = submit(bcr, org.requester)
    assert bcr.number == "NS-2026-00001"
    assert bcr.status == "IN_APPROVAL"
    assert instance.policy.subject_kind == "budget_change"
    assert instance.rule.label == "B"  # 60tr vượt max của A

    approve_all(bcr)
    assert bcr.status == "APPROVED"
    assert entries_of(bcr) == [
        (budget.line.pk, date(2026, m, 1), ADJUST, Decimal("10000000")) for m in range(1, 7)
    ]
    assert ledger.balance(budget.line).budget == Decimal("260000000")
    actions = list(
        AuditEvent.objects.filter(object_type="budget_changes.budgetchangerequest")
        .order_by("-id").values_list("action", flat=True)[:4]
    )
    assert actions == ["workflow.approved", "workflow.task_acted", "budget_change.status_changed",
                       "budget.entries_posted"]


def test_supplement_spanning_next_year_posts_on_next_year_line(db, org, budget, out_budget_policy, submit):
    bcr = make_change(org, budget.line, 40_000_000, start=date(2026, 11, 1), months=4)
    submit(bcr, org.requester)
    approve_all(bcr)
    next_line = BudgetLine.objects.get(
        year=2027, budget_unit=budget.line.budget_unit, cost_code=budget.line.cost_code,
        project=budget.line.project, location=budget.line.location,
    )
    assert entries_of(bcr) == [
        (budget.line.pk, date(2026, 11, 1), ADJUST, Decimal("10000000")),
        (budget.line.pk, date(2026, 12, 1), ADJUST, Decimal("10000000")),
        (next_line.pk, date(2027, 1, 1), ADJUST, Decimal("10000000")),
        (next_line.pk, date(2027, 2, 1), ADJUST, Decimal("10000000")),
    ]


# --- điều chuyển ----------------------------------------------------------------------------------

def test_transfer_exceeding_from_line_balance_raises_insufficient(db, org, budget, adm_line, out_budget_policy,
                                                                    submit):
    bcr = make_change(org, adm_line, 250_000_000, kind="TRANSFER", from_line=budget.line)
    with pytest.raises(InsufficientBudget) as exc:
        submit(bcr, org.requester)
    assert exc.value.shortfalls == [(budget.line, Decimal("50000000"))]
    bcr.refresh_from_db()
    assert bcr.status == "DRAFT"
    assert bcr.number is None
    assert not bcr.workflow_instances().exists()


def test_transfer_approved_posts_negative_and_positive_pairs(db, org, budget, adm_line, out_budget_policy,
                                                               submit):
    bcr = make_change(org, adm_line, 30_000_000, kind="TRANSFER", from_line=budget.line, months=3)
    instance = submit(bcr, org.requester)
    assert instance.rule.label == "A"
    assert instance.snapshot["context"]["budget_unit_ids"] == sorted([org.bu_itd.pk, org.bu_adm.pk])
    approve_all(bcr)
    assert bcr.status == "APPROVED"
    expected = [(budget.line.pk, date(2026, m, 1), TRANSFER, Decimal("-10000000")) for m in (1, 2, 3)]
    expected += [(adm_line.pk, date(2026, m, 1), TRANSFER, Decimal("10000000")) for m in (1, 2, 3)]
    assert entries_of(bcr) == sorted(expected)
    assert ledger.balance(budget.line).budget == Decimal("170000000")
    assert ledger.balance(adm_line).budget == Decimal("130000000")


def test_transfer_insufficient_at_approval_blocks_then_retry(db, org, budget, adm_line, out_budget_policy,
                                                               submit):
    from apps.budget_changes.services import BudgetChangeError, retry_apply

    bcr = make_change(org, adm_line, 30_000_000, kind="TRANSFER", from_line=budget.line)
    submit(bcr, org.requester)
    post(budget.line, date(2026, 1, 1), RESERVE, Decimal("190000000"), source=None, user=budget.admin)

    approve_all(bcr)
    assert bcr.status == "BLOCKED"
    assert entries_of(bcr) == []
    notified = set(Notification.objects.filter(title__contains="chưa ghi được").values_list("user__username",
                                                                                            flat=True))
    assert {"requester", "fad_admin"} <= notified

    with pytest.raises(BudgetChangeError):
        retry_apply(bcr, org.requester)
    with pytest.raises(InsufficientBudget):
        retry_apply(bcr, budget.admin)

    post(budget.line, date(2026, 1, 1), ADJUST, Decimal("20000000"), source=None, user=budget.admin)
    retry_apply(bcr, budget.admin)
    assert bcr.status == "APPROVED"
    assert len(entries_of(bcr)) == 2


# --- luỹ kế ngoài ngân sách -----------------------------------------------------------------------

def test_cumulative_150_approved_plus_60_routes_rule_b(db, org, budget, out_budget_policy, submit):
    make_change(org, budget.line, 150_000_000, status="APPROVED", number="NS-2026-09001")
    bcr = make_change(org, budget.line, 60_000_000)
    assert bcr.cumulative_amount_vnd("COMPANY") == Decimal("210000000")
    instance = submit(bcr, org.requester)
    assert instance.rule.label == "B"
    assert instance.snapshot["context"]["cumulative_after_vnd"] == "210000000"


def test_cumulative_195_approved_plus_10_routes_rule_b(db, org, budget, out_budget_policy, submit):
    make_change(org, budget.line, 195_000_000, status="APPROVED", number="NS-2026-09001")
    bcr = make_change(org, budget.line, 10_000_000)
    instance = submit(bcr, org.requester)
    assert instance.rule.label == "B"  # luỹ kế 205tr không < 200tr
    assert instance.snapshot["context"]["cumulative_after_vnd"] == "205000000"


def test_cumulative_below_cap_routes_rule_a(db, org, budget, out_budget_policy, submit):
    make_change(org, budget.line, 150_000_000, status="APPROVED", number="NS-2026-09001")
    bcr = make_change(org, budget.line, 10_000_000)
    assert submit(bcr, org.requester).rule.label == "A"


def test_cumulative_counts_approved_and_in_flight_supplements_of_the_year(db, org, budget, adm_line):
    line_2025 = BudgetLine.objects.create(
        year=2025, budget_unit=budget.line.budget_unit, cost_code=budget.line.cost_code,
        project=budget.line.project, location=budget.line.location,
    )
    make_change(org, budget.line, 100_000_000, status="APPROVED", number="NS-2026-09001")
    make_change(org, budget.line, 1_000_000, status="REJECTED", number="NS-2026-09002")
    make_change(org, budget.line, 5_000_000, status="IN_APPROVAL", number="NS-2026-09005")
    make_change(org, budget.line, 3_000_000, status="BLOCKED", number="NS-2026-09006")
    make_change(org, budget.line, 2_000_000)  # nháp
    make_change(org, line_2025, 4_000_000, start=date(2025, 1, 1), status="APPROVED", number="NS-2025-09001")
    make_change(org, adm_line, 8_000_000, kind="TRANSFER", from_line=budget.line, status="APPROVED",
                number="NS-2026-09003")
    make_change(org, adm_line, 16_000_000, status="APPROVED", number="NS-2026-09004")
    bcr = make_change(org, budget.line, 10_000_000)
    assert bcr.cumulative_amount_vnd("COMPANY") == Decimal("134000000")
    assert bcr.cumulative_amount_vnd("UNIT") == Decimal("118000000")  # chỉ cùng đơn vị ngân sách ITD
    transfer = make_change(org, adm_line, 5_000_000, kind="TRANSFER", from_line=budget.line)
    assert transfer.cumulative_amount_vnd("COMPANY") == Decimal("5000000")  # điều chuyển không tính luỹ kế


def test_split_supplements_count_in_flight_cumulative(db, org, budget, out_budget_policy, submit):
    """Chia nhỏ đề nghị không lách được hạn mức luỹ kế: đề nghị đang duyệt cũng được tính."""
    make_change(org, budget.line, 150_000_000, status="APPROVED", number="NS-2026-09001")
    first = make_change(org, budget.line, 30_000_000)
    assert submit(first, org.requester).rule.label == "A"  # luỹ kế 180tr < 200tr
    second = make_change(org, budget.line, 30_000_000)
    assert second.cumulative_amount_vnd("COMPANY") == Decimal("210000000")
    assert submit(second, org.requester).rule.label == "B"  # luỹ kế 210tr gồm cả đề nghị đang duyệt


def test_split_requests_keep_their_submit_time_routing(db, org, budget, out_budget_policy, submit):
    """Luỹ kế khi duyệt chỉ tính các đề nghị nộp trước đó: đề nghị nộp sau không làm hỏng cấp của đề nghị trước."""
    requests = [make_change(org, budget.line, 45_000_000) for _ in range(5)]
    labels = [submit(bcr, org.requester).rule.label for bcr in requests]
    assert labels == ["A", "A", "A", "A", "B"]  # đến đề nghị thứ 5 thì luỹ kế 225tr ≥ 200tr

    first = requests[0]
    assert first.cumulative_amount_vnd("COMPANY") == Decimal("45000000")  # chỉ chính nó
    approve_all(first)
    assert first.status == "APPROVED"
    assert entries_of(first) == [(budget.line.pk, date(2026, 1, 1), ADJUST, Decimal("45000000"))]

    # đề nghị nộp sau vẫn tính cả đề nghị nộp trước (đã duyệt hoặc đang duyệt)
    assert requests[4].cumulative_amount_vnd("COMPANY") == Decimal("225000000")


def test_cumulative_grown_during_approval_blocks_without_posting(db, org, budget, adm_line, out_budget_policy,
                                                                   submit):
    """Luỹ kế vượt mức của cấp đã duyệt tại thời điểm duyệt xong → không ghi ngân sách, chờ trình lại."""
    from apps.budget_changes.services import BudgetChangeError, retry_apply

    make_change(org, budget.line, 150_000_000, status="APPROVED", number="NS-2026-09001")
    bcr = make_change(org, budget.line, 30_000_000)
    assert submit(bcr, org.requester).rule.label == "A"
    other = make_change(org, adm_line, 40_000_000)  # còn nháp khi nộp bcr nên chưa tính vào luỹ kế
    submit(other, org.requester)
    approve_all(other)  # được duyệt xong trước bcr → luỹ kế của bcr tăng

    approve_all(bcr)
    assert bcr.status == "BLOCKED"
    assert entries_of(bcr) == []
    assert ledger.balance(budget.line).budget == Decimal("200000000")
    note = AuditEvent.objects.filter(action="budget_change.status_changed").order_by("-id").first().changes["note"]
    assert note == "Luỹ kế ngoài ngân sách đã vượt mức của cấp đã duyệt; cần trình lại cấp cao hơn"
    assert Notification.objects.filter(title__contains="chưa ghi được",
                                        user=org.requester).exists()
    with pytest.raises(BudgetChangeError, match="trình lại cấp cao hơn"):
        retry_apply(bcr, budget.admin)
    assert entries_of(bcr) == []


def test_callback_posts_once_and_only_from_in_approval(db, org, budget, out_budget_policy, submit):
    from apps.budget_changes.services import BudgetChangeError

    bcr = make_change(org, budget.line, 10_000_000)
    submit(bcr, org.requester)
    approve_all(bcr)
    posted = entries_of(bcr)
    assert len(posted) == 1

    with pytest.raises(BudgetChangeError, match="không ở trạng thái đang duyệt"):
        bcr.on_workflow_finished("APPROVED")  # gọi lại callback: không ghi thêm bút toán
    assert entries_of(bcr) == posted

    draft = make_change(org, budget.line, 10_000_000)
    with pytest.raises(BudgetChangeError, match="không ở trạng thái đang duyệt"):
        draft.on_workflow_finished("APPROVED")
    assert entries_of(draft) == []


def test_cumulative_scope_setting_unit(db, org, budget, adm_line, out_budget_policy, submit):
    Setting.objects.update_or_create(key="cumulative_scope", defaults={"value": "UNIT"})
    make_change(org, adm_line, 195_000_000, status="APPROVED", number="NS-2026-09001")
    bcr = make_change(org, budget.line, 10_000_000)
    assert submit(bcr, org.requester).rule.label == "A"  # ADM không cùng đơn vị ngân sách với ITD


# --- tạo sẵn từ tờ trình bị chặn ------------------------------------------------------------------

def test_prefill_from_blocked_requisition(db, org, budget, in_budget_policy, out_budget_policy, submit):
    from apps.budget_changes.services import prefill_from_shortfall
    from apps.requisitions.services import submit as submit_requisition

    req = make_requisition(org, budget.line, 250_000_000, service_start=date(2026, 3, 10), months=6)
    with pytest.raises(InsufficientBudget) as exc:
        submit_requisition(req, org.requester)

    [bcr] = prefill_from_shortfall(req, exc.value.shortfalls, org.requester)
    assert (bcr.status, bcr.kind, bcr.to_line, bcr.from_line) == ("DRAFT", "SUPPLEMENT", budget.line, None)
    assert bcr.amount_vnd == Decimal("50000000")
    assert (bcr.start, bcr.months) == (date(2026, 3, 1), 6)
    assert bcr.requisition == req
    assert bcr.requester == org.requester
    assert bcr.reason == f"Bổ sung ngân sách cho tờ trình nháp #{req.pk}"

    # gọi lại: dùng bản nháp sẵn có, số tiền tính lại từ ngân sách (không tin số của người gọi)
    [again] = prefill_from_shortfall(req, [(budget.line, Decimal("999000000"))], org.requester)
    assert again.pk == bcr.pk
    assert again.amount_vnd == Decimal("50000000")
    assert req.budget_change_requests.count() == 1

    # đề nghị bổ sung được duyệt → tờ trình nộp được
    [bcr] = prefill_from_shortfall(req, exc.value.shortfalls, org.requester)
    submit(bcr, org.requester)
    approve_all(bcr)
    assert bcr.status == "APPROVED"
    submit_requisition(req, org.requester)
    assert req.status == "IN_APPROVAL"


def test_prefill_keeps_supplement_inside_the_year(db, org, budget, in_budget_policy):
    """Phân bổ của đề nghị không vượt sang năm sau, để toàn bộ phần bù rơi vào năm bị thiếu."""
    from apps.budget_changes.services import prefill_from_shortfall

    req = make_requisition(org, budget.line, 600_000_000, service_start=date(2026, 7, 1), months=12)
    shortfalls, _ = ledger.check_reserve(req.budget_allocations(), start=req.reserve_start, months=req.months)
    assert shortfalls == [(budget.line, Decimal("100000000"))]
    [bcr] = prefill_from_shortfall(req, shortfalls, org.requester)
    assert (bcr.start, bcr.months) == (date(2026, 7, 1), 6)


def test_prefill_checks_owner_lines_and_shortfall(db, org, budget, adm_line, in_budget_policy):
    from apps.budget_changes.services import BudgetChangeError, prefill_from_shortfall

    req = make_requisition(org, budget.line, 250_000_000)
    short = [(budget.line, Decimal("50000000"))]
    with pytest.raises(BudgetChangeError, match="người lập hoặc người đề nghị"):
        prefill_from_shortfall(req, short, UserFactory())
    with pytest.raises(BudgetChangeError, match="người lập hoặc người đề nghị"):
        prefill_from_shortfall(req, short, org.dept_head)  # xem được nhưng không phải người lập
    with pytest.raises(BudgetChangeError, match="không thuộc phân bổ"):
        prefill_from_shortfall(req, [(adm_line, Decimal("1000000"))], org.requester)

    enough = make_requisition(org, budget.line, 10_000_000)
    with pytest.raises(BudgetChangeError, match="không thiếu ngân sách"):
        prefill_from_shortfall(enough, [(budget.line, Decimal("50000000"))], org.requester)


def test_prefill_after_submit_reuses_the_pending_request(db, org, budget, in_budget_policy, out_budget_policy,
                                                          submit):
    from apps.budget_changes.services import prefill_from_shortfall

    req = make_requisition(org, budget.line, 250_000_000)
    short = [(budget.line, Decimal("50000000"))]
    [bcr] = prefill_from_shortfall(req, short, org.requester)
    submit(bcr, org.requester)

    [again] = prefill_from_shortfall(req, short, org.requester)
    assert again.pk == bcr.pk
    assert again.status == "IN_APPROVAL"
    assert req.budget_change_requests.count() == 1


# --- kiểm tra hợp lệ, khoá nội dung, vòng đời -------------------------------------------------------

@pytest.mark.parametrize("overrides, message", [
    ({"amount_vnd": Decimal("0")}, "Số tiền đề nghị phải lớn hơn 0"),
    ({"start": date(2027, 1, 1)}, "Kỳ bắt đầu phải thuộc năm của dòng ngân sách nhận"),
    ({"reason": "  "}, "Vui lòng nhập lý do đề nghị"),
    ({"from_line": "itd"}, "Đề nghị bổ sung không có dòng ngân sách nguồn"),
    ({"kind": "TRANSFER"}, "Điều chuyển cần chọn dòng ngân sách nguồn"),
    ({"kind": "TRANSFER", "from_line": "itd", "to_line": "itd"}, "Dòng ngân sách nguồn và nhận phải khác nhau"),
    ({"kind": "TRANSFER", "from_line": "itd_2025"}, "Dòng ngân sách nguồn và nhận phải cùng năm"),
])
def test_validation_blocks_submit(db, org, budget, adm_line, out_budget_policy, submit, overrides, message):
    from apps.budget_changes.services import SubmitBlocked

    line_2025 = BudgetLine.objects.create(
        year=2025, budget_unit=budget.line.budget_unit, cost_code=budget.line.cost_code,
        project=budget.line.project, location=budget.line.location,
    )
    lines = {"itd": budget.line, "adm": adm_line, "itd_2025": line_2025}
    data = {"to_line": "adm"} | overrides
    for key in ("from_line", "to_line"):
        if key in data:
            data[key] = lines[data[key]]
    to_line = data.pop("to_line")
    amount = data.pop("amount_vnd", Decimal("10000000"))
    bcr = make_change(org, to_line, amount, **data)
    with pytest.raises(SubmitBlocked) as exc:
        submit(bcr, org.requester)
    assert message in exc.value.errors
    bcr.refresh_from_db()
    assert (bcr.status, bcr.number) == ("DRAFT", None)


def test_amount_must_be_whole_dong(db, org, budget):
    with pytest.raises(ValueError, match="số nguyên đồng"):
        make_change(org, budget.line, Decimal("100.5"))


def test_months_must_be_positive(db, org, budget):
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        make_change(org, budget.line, 10_000_000, months=0)


def test_only_owner_submits(db, org, budget, out_budget_policy, submit):
    from apps.budget_changes.services import SubmitBlocked

    bcr = make_change(org, budget.line, 10_000_000)
    with pytest.raises(SubmitBlocked):
        submit(bcr, org.dept_head)


def test_header_locked_after_submit(db, org, budget, out_budget_policy, submit):
    bcr = make_change(org, budget.line, 10_000_000)
    submit(bcr, org.requester)
    bcr.amount_vnd = Decimal("1")
    with pytest.raises(PermissionError):
        bcr.save()


def test_returned_reopen_and_resubmit_keeps_number(db, org, budget, out_budget_policy, submit):
    from apps.budget_changes.services import BudgetChangeError, reopen

    bcr = make_change(org, budget.line, 10_000_000)
    first = submit(bcr, org.requester)
    task = pending_task(first)
    act(task, resolver.candidates(task).first(), "RETURN", "Bổ sung thuyết minh")
    bcr.refresh_from_db()
    assert bcr.status == "RETURNED"

    with pytest.raises(BudgetChangeError):
        reopen(bcr, org.dept_head)
    reopen(bcr, org.requester)
    assert bcr.status == "DRAFT"
    bcr.reason = "Thuyết minh bổ sung"
    bcr.save()
    second = submit(bcr, org.requester)
    assert second.pk != first.pk
    assert bcr.number == "NS-2026-00001"


def test_rejected_status(db, org, budget, out_budget_policy, submit):
    bcr = make_change(org, budget.line, 10_000_000)
    instance = submit(bcr, org.requester)
    task = pending_task(instance)
    act(task, resolver.candidates(task).first(), "REJECT", "Không cần thiết")
    bcr.refresh_from_db()
    assert bcr.status == "REJECTED"
    assert entries_of(bcr) == []


def test_cancel(db, org, budget, out_budget_policy, submit):
    from apps.budget_changes.services import BudgetChangeError, cancel

    draft = make_change(org, budget.line, 10_000_000)
    with pytest.raises(BudgetChangeError):
        cancel(draft, org.requester, " ")
    with pytest.raises(BudgetChangeError):
        cancel(draft, org.dept_head, "Không cần nữa")
    cancel(draft, org.requester, "Không cần nữa")
    assert draft.status == "CANCELLED"

    running = make_change(org, budget.line, 10_000_000)
    instance = submit(running, org.requester)
    cancel(running, org.requester, "Đổi kế hoạch")
    instance.refresh_from_db()
    assert (running.status, instance.status) == ("CANCELLED", "CANCELLED")

    approved = make_change(org, budget.line, 10_000_000)
    submit(approved, org.requester)
    approve_all(approved)
    with pytest.raises(BudgetChangeError):
        cancel(approved, budget.admin, "Huỷ")


def test_requester_and_creator_are_barred(db, org, budget, out_budget_policy, submit):
    bcr = make_change(org, budget.line, 10_000_000, created_by=org.gddh)
    instance = submit(bcr, org.requester)
    assert {org.requester.pk, org.gddh.pk} <= resolver.barred_user_ids(instance)
    assert instance.snapshot["context"]["requester_unit_id"] == org.req_unit.pk


def test_visibility(db, org, budget, adm_line, out_budget_policy, submit):
    from apps.budget_changes.models import BudgetChangeRequest

    submitted = make_change(org, budget.line, 10_000_000)
    submit(submitted, org.requester)
    draft = make_change(org, adm_line, 10_000_000)
    outsider = UserFactory()
    member_itd = UserFactory(org_unit=org.itd)

    assert submitted.visible_to(org.requester)
    assert submitted.visible_to(org.dept_head)        # cùng đơn vị đề nghị
    assert submitted.visible_to(org.owner_itd)        # BUDGET_OWNER của đơn vị quản lý dòng nhận
    assert submitted.visible_to(org.fad)
    assert submitted.visible_to(budget.admin)
    assert submitted.visible_to(org.gddh)             # người đúng vai trò của một bước
    assert not submitted.visible_to(org.owner_adm)
    assert not submitted.visible_to(outsider)
    assert not submitted.visible_to(member_itd)
    assert draft.visible_to(org.owner_adm)
    assert not draft.visible_to(org.owner_itd)

    owner_all = grant(UserFactory(username="owner_all"), R.BUDGET_OWNER)  # phân công toàn công ty
    assert submitted.visible_to(owner_all) and draft.visible_to(owner_all)
    assert set(BudgetChangeRequest.objects.visible_to(owner_all).values_list("pk", flat=True)) == {
        submitted.pk, draft.pk
    }

    for user in (org.requester, org.owner_itd, org.owner_adm, org.gddh, outsider, org.fad):
        listed = set(BudgetChangeRequest.objects.visible_to(user).values_list("pk", flat=True))
        assert listed == {b.pk for b in (submitted, draft) if b.visible_to(user)}, user.username


def test_transfer_visible_to_source_budget_owner(db, org, budget, adm_line):
    transfer = make_change(org, adm_line, 10_000_000, kind="TRANSFER", from_line=budget.line)
    assert transfer.visible_to(org.owner_itd)
    assert transfer.visible_to(org.owner_adm)


def test_retry_apply_requires_budget_admin_role(db, org, budget):
    from apps.budget_changes.services import BudgetChangeError, retry_apply

    fad = org.fad
    assert not R.has_role(fad, R.FAD_BUDGET_ADMIN)
    bcr = make_change(org, budget.line, 10_000_000)
    with pytest.raises(BudgetChangeError):
        retry_apply(bcr, fad)


def test_transfer_into_next_year_needs_next_year_source_budget(db, org, budget, adm_line, out_budget_policy, submit):
    """Kỳ sang năm sau ghi giảm dòng nguồn cùng chiều của năm đó — chưa có ngân sách thì bị chặn."""
    bcr = make_change(org, adm_line, 40_000_000, kind="TRANSFER", from_line=budget.line,
                      start=date(2026, 11, 1), months=4)
    with pytest.raises(InsufficientBudget) as exc:
        submit(bcr, org.requester)
    [(short_line, amount)] = exc.value.shortfalls
    assert (short_line.year, short_line.pk, amount) == (2027, None, Decimal("20000000"))
    assert not BudgetLine.objects.filter(year=2027).exists()
