"""Lệnh `seed_demo`: dựng toàn bộ dữ liệu demo cho kịch bản nghiệm thu đợt 1.

Chạy lại được nhiều lần (get_or_create / bỏ qua phần đã có). Dữ liệu lấy từ `sample-data/` (dữ liệu
GIẢ sinh bằng `scripts/make_sample_data.py`):

1. `sync_hris` với `FakeHrisClient` đọc `hris_fake.json` → đơn vị + người dùng;
2. `import_budget_workbook` đọc `Budget Control - DEMO.xlsx` → đơn vị ngân sách ITD (kèm sheet
   L9_Code → nhà cung cấp);
3. đơn vị ngân sách ADM (dòng ngân sách demo thứ hai, để tờ trình có 2 nguồn → 2 nhánh duyệt);
4. phân quyền theo gợi ý `roles` trong `hris_fake.json`;
5. hai chính sách duyệt mẫu (`apps.workflow.sample_policies`);
6. tỷ giá USD và 4 tham số hệ thống.

Lệnh thay đổi diện rộng (xem `_check_target_database`) nên từ chối chạy khi cơ sở dữ liệu đã có
người dùng ngoài danh sách demo, trừ khi có cờ `--confirm`.

`--reset` chỉ xoá được phần dữ liệu cho phép xoá (chính sách chưa dùng, phân quyền, uỷ quyền, tỷ
giá, tham số). Bút toán ngân sách, nhật ký audit và chứng từ lưu vĩnh viễn (Ràng buộc chung) nên
muốn làm lại từ đầu thì tạo lại cơ sở dữ liệu.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.accounts import roles as R
from apps.accounts.models import OrgUnit, Role, RoleAssignment, User
from apps.accounts.services import sync_hris
from apps.budget.importer import import_budget_workbook
from apps.budget.ledger import post
from apps.budget.models import ORIGINAL, BudgetEntry, BudgetLine, BudgetUnit, CostCode, Location, Project
from apps.core.models import ExchangeRate, Setting
from apps.core.services import set_setting
from apps.integrations.fakes import FakeHrisClient
from apps.workflow.models import ApprovalPolicy, Delegation
from apps.workflow.sample_policies import build_in_budget_policy, build_out_budget_policy

SAMPLE_DIR = Path(settings.BASE_DIR).parent / "sample-data"
HRIS_FILE = SAMPLE_DIR / "hris_fake.json"
WORKBOOK_FILE = SAMPLE_DIR / "Budget Control - DEMO.xlsx"

YEAR = 2026
DEMO_PASSWORD = "Demo-MuaSam-2026"  # chỉ dùng cho dữ liệu giả; tối thiểu 12 ký tự
USD_RATE = Decimal("25460.0000")

# Đơn vị ngân sách lấy từ workbook (mã L8/L10 trong file thuộc đơn vị này).
ITD_UNIT = ("ITD", "Ngân sách CNTT Demo", "ITD-DEMO")
# Đơn vị ngân sách thứ hai: workbook chỉ chứa một bộ mã L8 nên dòng ngân sách của ADM được dựng
# trực tiếp (tờ trình demo cần 2 nguồn ngân sách thuộc 2 đơn vị quản lý khác nhau).
ADM_UNIT = ("ADM", "Ngân sách Hành chính Demo", "ADM-DEMO")
ADM_COST_CODE = ("ADM_2.1", "Chi phí hành chính Demo")
ADM_PROJECT = ("BAU_ADM", "BAU Hành chính Demo")
LOCATION = ("HSC", "TP.HCM (HO)")

# Dòng ngân sách của kịch bản: (mã L8, mã L10, địa điểm) → ngân sách gốc bổ sung cho demo.
# Số tiền đủ cho tờ trình 100.000 USD (= 2.546.000.000 đ) chia 60/40 trên hai dòng.
DEMO_BUDGET = {
    "ITD": (("DM_9.1", "BAU_ITD", "HSC"), Decimal("1600000000")),
    "ADM": ((ADM_COST_CODE[0], ADM_PROJECT[0], LOCATION[0]), Decimal("1100000000")),
}
DEMO_BUDGET_NOTE = "Ngân sách demo cho kịch bản nghiệm thu đợt 1"
DEMO_BUDGET_PERIOD = date(YEAR, 1, 1)

POLICY_CODES = ("TRONG_NGAN_SACH", "NGOAI_NGAN_SACH")
SETTINGS = {
    "split_window_days": 30,
    "annual_fixed_cost_vnd": 100_000_000_000,
    "cumulative_scope": "COMPANY",
    "max_upload_mb": 25,
}
DEMO_LOGINS = [
    ("nv.mau1", "Người đề nghị (Phòng Demo A)"),
    ("tp.mau1", "Trưởng phòng Demo A (đề nghị / phê duyệt < 200tr)"),
    ("bo.itd", "Đơn vị quản lý ngân sách CNTT"),
    ("bo.adm", "Đơn vị quản lý ngân sách Hành chính"),
    ("tv.dti", "Tham vấn chuyên môn (Phòng Dữ liệu)"),
    ("fad.tienkiem", "FAD tiền kiểm"),
    ("fad.ngansach", "FAD quản trị ngân sách"),
    ("gddh.mau", "Giám đốc điều hành"),
    ("gdnv.mau", "Giám đốc nghiệp vụ (người được uỷ quyền duyệt thay GĐĐH)"),
    ("thuky.bms", "Thư ký BMS (duyệt tại cuộc họp)"),
    ("thuky.hdqt", "Thư ký HĐQT"),
    ("ceo.mau", "Tổng giám đốc"),
]


def demo_lines() -> dict[str, BudgetLine]:
    """Hai dòng ngân sách demo của kịch bản nghiệm thu, theo mã đơn vị ngân sách."""
    out = {}
    for unit_code, ((l8, l10, loc), _) in DEMO_BUDGET.items():
        out[unit_code] = BudgetLine.objects.get(
            year=YEAR, budget_unit__code=unit_code, cost_code__code=l8, project__code=l10,
            location__code=loc,
        )
    return out


def _seed_user():
    """Người thực hiện các bước nhập liệu demo (ghi vào audit); None nếu chưa đồng bộ HRIS."""
    return User.objects.filter(username="fad.ngansach").first()


def _feed():
    if not HRIS_FILE.exists():
        raise CommandError(
            f"Không tìm thấy {HRIS_FILE}. Sinh lại bằng: python scripts/make_sample_data.py --out sample-data/"
        )
    return FakeHrisClient(HRIS_FILE)


def demo_usernames() -> set[str]:
    """Tên đăng nhập của người dùng demo (đúng danh sách trong hris_fake.json)."""
    return {row["username"] for row in _feed().fetch_employees()}


def _check_target_database(confirm: bool) -> None:
    """Chặn chạy nhầm lên cơ sở dữ liệu thật.

    Lệnh này thay đổi diện rộng: `sync_hris` vô hiệu hoá mọi nhân viên không có trong file giả (và
    xoá phiên của họ), mật khẩu demo được công bố trong tài liệu. Vì vậy chỉ chạy khi CSDL chưa có
    người dùng nào ngoài danh sách demo, hoặc người chạy khẳng định bằng `--confirm`.
    """
    if confirm:
        return
    others = (
        User.objects.exclude(username__in=demo_usernames())
        .exclude(is_superuser=True, employee_code__isnull=True)
        .count()
    )
    if others:
        raise CommandError(
            f"Cơ sở dữ liệu đang có {others} người dùng ngoài danh sách demo "
            f"({connection.settings_dict.get('NAME')}). Lệnh seed_demo thay đổi diện rộng "
            "(vô hiệu hoá nhân viên không có trong file giả, đặt mật khẩu demo). "
            "Kiểm tra lại DATABASE_URL; nếu đúng là CSDL demo thì chạy lại với --confirm."
        )


def _sync_hris(report):
    result = sync_hris(_feed())
    report.append(
        f"HRIS: tạo mới {result.created}, cập nhật {result.updated}, vô hiệu hoá {result.deactivated}"
    )


def _set_passwords(report):
    """Đặt mật khẩu demo CHỈ cho người dùng trong file giả (không chạm người dùng khác)."""
    changed = 0
    for user in User.objects.filter(username__in=demo_usernames()):
        if not user.has_usable_password():
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
            changed += 1
    report.append(f"Mật khẩu demo: đặt cho {changed} người dùng")


def _grant_roles(report):
    """Phân quyền theo gợi ý `roles` trong hris_fake.json (bỏ qua phân công đã có)."""
    granted = 0
    for row in _feed().fetch_employees():
        user = User.objects.filter(employee_code=row["employee_code"]).first()
        if user is None:
            continue
        for hint in row.get("roles") or []:
            code = hint["role"]
            if code not in R.ROLE_NAMES:
                raise CommandError(f"Gợi ý phân quyền của {row['username']}: vai trò '{code}' không tồn tại")
            Role.objects.get_or_create(code=code, defaults={"name": R.ROLE_NAMES[code]})
            org_code = hint.get("org_unit_code")
            # `org_unit=None` là vai trò TOÀN CÔNG TY: mã đơn vị sai không được âm thầm thành toàn công ty.
            org_unit = None
            if org_code:
                org_unit = OrgUnit.objects.filter(code=org_code).first()
                if org_unit is None:
                    raise CommandError(
                        f"Gợi ý phân quyền của {row['username']}: không có đơn vị '{org_code}' "
                        f"(vai trò {code}). Sửa hris_fake.json rồi chạy lại."
                    )
            if RoleAssignment.objects.filter(user=user, role__code=code, org_unit=org_unit).exists():
                continue
            R.assign(user, code, org_unit, actor=user)
            granted += 1
    report.append(f"Phân quyền: thêm {granted} phân công vai trò")


def _import_workbook(report, user):
    code, name, org_code = ITD_UNIT
    unit = BudgetUnit.objects.filter(code=code).first()
    if unit is not None and BudgetEntry.objects.filter(
        line__budget_unit=unit, line__year=YEAR, kind=ORIGINAL
    ).exists():
        report.append(f"Ngân sách {code}/{YEAR}: đã có, bỏ qua việc nhập lại file Excel")
        return
    if not WORKBOOK_FILE.exists():
        raise CommandError(
            f"Không tìm thấy {WORKBOOK_FILE}. Sinh lại bằng: "
            "python scripts/make_sample_data.py --out sample-data/"
        )
    result = import_budget_workbook(
        str(WORKBOOK_FILE), budget_unit_code=code, year=YEAR, user=user, dry_run=False,
        managing_org_unit_code=org_code,
    )
    if result.issues:
        raise CommandError(
            "File ngân sách demo không sạch: " + "; ".join(i.message for i in result.issues[:5])
        )
    BudgetUnit.objects.filter(code=code).update(name=name)
    report.append(
        f"Ngân sách {code}/{YEAR} từ Excel: {result.created['lines']} dòng, "
        f"{result.created['entries']} bút toán, {result.created.get('vendors', 0)} nhà cung cấp"
    )


def _adm_budget_unit(report):
    from apps.accounts.models import OrgUnit

    code, name, org_code = ADM_UNIT
    org = OrgUnit.objects.filter(code=org_code).first()
    if org is None:
        raise CommandError(f"Chưa có đơn vị {org_code} (kiểm tra hris_fake.json)")
    unit, created = BudgetUnit.objects.get_or_create(
        code=code, defaults={"name": name, "managing_org_unit": org}
    )
    cost_code, _ = CostCode.objects.get_or_create(
        code=ADM_COST_CODE[0], defaults={"name": ADM_COST_CODE[1], "budget_unit": unit}
    )
    project, _ = Project.objects.get_or_create(
        code=ADM_PROJECT[0],
        defaults={"name": ADM_PROJECT[1], "workstream": "BAU", "begin_year": YEAR, "budget_unit": unit},
    )
    location, _ = Location.objects.get_or_create(code=LOCATION[0], defaults={"name": LOCATION[1]})
    BudgetLine.objects.get_or_create(
        year=YEAR, budget_unit=unit, cost_code=cost_code, project=project, location=location
    )
    report.append(f"Đơn vị ngân sách {code}: {'tạo mới' if created else 'đã có'}")


def _demo_budget(report, user):
    """Ngân sách gốc cho hai dòng của kịch bản (đủ cho tờ trình > 2 tỷ)."""
    added = []
    for unit_code, line in demo_lines().items():
        amount = DEMO_BUDGET[unit_code][1]
        if BudgetEntry.objects.filter(line=line, kind=ORIGINAL, note=DEMO_BUDGET_NOTE).exists():
            continue
        post(line, DEMO_BUDGET_PERIOD, ORIGINAL, amount, source=None, user=user, note=DEMO_BUDGET_NOTE)
        added.append(f"{line.short_label}: {amount:,} đ".replace(",", "."))
    report.append("Ngân sách demo: " + ("; ".join(added) if added else "đã có, không ghi thêm"))


def _policies(report):
    today = date.today()
    for code, build in zip(POLICY_CODES, (build_in_budget_policy, build_out_budget_policy), strict=True):
        if ApprovalPolicy.objects.filter(code=code).exists():
            report.append(f"Chính sách {code}: đã có, bỏ qua")
            continue
        policy = build(today)
        report.append(f"Chính sách {code} v{policy.version}: {policy.rules.count()} quy tắc")


def _rate_and_settings(report):
    rate, created = ExchangeRate.objects.get_or_create(
        currency="USD", date=date(YEAR, 1, 1), defaults={"rate": USD_RATE}
    )
    report.append(f"Tỷ giá USD {rate.date:%d/%m/%Y} = {rate.rate}: {'tạo mới' if created else 'đã có'}")
    user = _seed_user()
    for key, value in SETTINGS.items():
        if Setting.objects.filter(key=key).exists():
            continue
        set_setting(key, value, user)
    report.append("Tham số hệ thống: " + ", ".join(f"{k}={v}" for k, v in SETTINGS.items()))


def _reset(report):
    """Xoá phần dữ liệu demo cho phép xoá (xem docstring: bút toán/audit/chứng từ là vĩnh viễn)."""
    policies = ApprovalPolicy.objects.filter(code__in=POLICY_CODES)
    try:
        removed = policies.delete()[0]
    except PermissionError:
        report.append("Chính sách mẫu: đã có hồ sơ duyệt dùng tới, KHÔNG xoá được")
    else:
        report.append(f"Đã xoá {removed} đối tượng chính sách mẫu")
    demo_users = User.objects.filter(username__in=demo_usernames())
    report.append(f"Đã xoá {Delegation.objects.filter(delegator__in=demo_users).delete()[0]} uỷ quyền")
    report.append(
        f"Đã xoá {RoleAssignment.objects.filter(user__in=demo_users).delete()[0]} phân công vai trò"
    )
    rates = ExchangeRate.objects.filter(currency="USD", date=date(YEAR, 1, 1), rate=USD_RATE)
    report.append(f"Đã xoá {rates.delete()[0]} tỷ giá USD của dữ liệu demo")
    report.append(f"Đã xoá {Setting.objects.filter(key__in=SETTINGS).delete()[0]} tham số hệ thống")
    report.append(
        "Bút toán ngân sách, nhật ký audit và chứng từ lưu vĩnh viễn: muốn làm lại từ đầu thì tạo lại CSDL"
    )


class Command(BaseCommand):
    help = "Tạo dữ liệu demo cho kịch bản nghiệm thu đợt 1 từ sample-data/ (chạy lại được)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Xoá dữ liệu demo xoá được (chính sách mẫu, phân quyền, uỷ quyền, tỷ giá, tham số) rồi dựng lại",
        )
        parser.add_argument(
            "--confirm", action="store_true",
            help="Khẳng định đây là CSDL demo (bắt buộc khi CSDL đã có người dùng ngoài danh sách demo)",
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        report: list[str] = []
        _check_target_database(opts["confirm"])
        if opts["reset"]:
            _reset(report)
        _sync_hris(report)
        _set_passwords(report)
        _grant_roles(report)
        user = _seed_user()
        _import_workbook(report, user)
        _adm_budget_unit(report)
        _demo_budget(report, user)
        _policies(report)
        _rate_and_settings(report)

        out = self.stdout.write
        out("DỮ LIỆU DEMO ĐỢT 1")
        for line in report:
            out(f"  - {line}")
        out(f"\nMật khẩu chung cho mọi tài khoản demo: {DEMO_PASSWORD}")
        out("(Đăng nhập bằng mật khẩu cần TOTP: python src/manage.py enroll_totp <tên đăng nhập>)")
        out("Tài khoản demo:")
        for username, role in DEMO_LOGINS:
            out(f"  - {username:<14} {role}")
