from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.budget.importer import import_budget_workbook
from apps.core.money import format_vnd


class Command(BaseCommand):
    help = "Nhập file Budget Control (Excel) và in báo cáo làm sạch. Mặc định chạy thử, thêm --commit để ghi."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Đường dẫn file .xlsx")
        parser.add_argument("--unit", required=True, help="Mã đơn vị ngân sách")
        parser.add_argument("--year", required=True, type=int)
        parser.add_argument("--org-unit", help="Mã đơn vị quản lý (chỉ cần khi tạo mới đơn vị ngân sách)")
        parser.add_argument("--user", help="Tên đăng nhập người thực hiện (ghi vào audit)")
        parser.add_argument("--commit", action="store_true", help="Ghi dữ liệu thật (mặc định chỉ chạy thử)")

    def handle(self, *args, **opts):
        user = None
        if opts["user"]:
            user = get_user_model().objects.filter(username=opts["user"]).first()
            if user is None:
                raise CommandError(f"Không có người dùng {opts['user']}")
        try:
            report = import_budget_workbook(
                opts["path"], budget_unit_code=opts["unit"], year=opts["year"], user=user,
                dry_run=not opts["commit"], managing_org_unit_code=opts["org_unit"],
            )
        except FileNotFoundError as e:
            raise CommandError(f"Không tìm thấy file: {e.filename}") from e
        out = self.stdout.write
        out(f"BÁO CÁO LÀM SẠCH — đơn vị {opts['unit']}, năm {opts['year']}")
        if report.issues:
            out(f"Có {len(report.issues)} vấn đề, KHÔNG ghi gì. Sửa trên Excel rồi nhập lại:")
            for i in report.issues:
                where = f"{i.sheet}, dòng {i.row}, cột {i.column}" if i.sheet else "Chung"
                out(f"  - [{where}] {i.message}")
            raise CommandError("Nhập thất bại do dữ liệu chưa sạch.")
        out(f"Bỏ qua {report.skipped_other_year} dòng thuộc năm khác.")
        out(f"Tổng kế hoạch gốc: {format_vnd(report.totals['ORIGINAL'])} đ; "
            f"tổng điều chỉnh: {format_vnd(report.totals['ADJUST'])} đ")
        labels = {"cost_codes": "mã chi phí mới", "projects": "dự án mới", "lines": "dòng ngân sách",
                  "entries": "bút toán"}
        out("; ".join(f"{labels[k]}: {v}" for k, v in report.created.items()))
        out("Đã ghi dữ liệu." if opts["commit"] else "Chạy thử: chưa ghi gì (thêm --commit để ghi).")
