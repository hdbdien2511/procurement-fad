from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from openpyxl import load_workbook

from apps.core.imports import ImportReport
from apps.vendors.importer import SHEET_L9, import_vendors_from_rows, read_vendor_sheet


class Command(BaseCommand):
    help = "Nhập danh mục nhà cung cấp từ sheet L9_Code. Mặc định chạy thử, thêm --commit để ghi."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Đường dẫn file .xlsx")
        parser.add_argument("--user", help="Tên đăng nhập người thực hiện (ghi vào audit)")
        parser.add_argument("--commit", action="store_true", help="Ghi dữ liệu thật (mặc định chỉ chạy thử)")

    def handle(self, *args, **opts):
        user = None
        if opts["user"]:
            user = get_user_model().objects.filter(username=opts["user"]).first()
            if user is None:
                raise CommandError(f"Không có người dùng {opts['user']}")
        try:
            wb = load_workbook(opts["path"], read_only=True, data_only=True)
        except FileNotFoundError as e:
            raise CommandError(f"Không tìm thấy file: {e.filename}") from e
        header_report = ImportReport()
        try:
            rows = read_vendor_sheet(wb, header_report)
        finally:
            wb.close()
        if rows is None:
            raise CommandError(f"Thiếu sheet {SHEET_L9}")
        report = import_vendors_from_rows(rows, user, dry_run=not opts["commit"]) if not header_report.issues \
            else header_report
        out = self.stdout.write
        out("BÁO CÁO LÀM SẠCH — nhà cung cấp")
        if report.issues:
            out(f"Có {len(report.issues)} vấn đề, KHÔNG ghi gì. Sửa trên Excel rồi nhập lại:")
            for i in report.issues:
                out(f"  - [{i.sheet}, dòng {i.row}, cột {i.column}] {i.message}")
            raise CommandError("Nhập thất bại do dữ liệu chưa sạch.")
        out(f"Nhà cung cấp mới: {report.created['vendors']}; cập nhật: {report.created['vendors_updated']}")
        out("Đã ghi dữ liệu." if opts["commit"] else "Chạy thử: chưa ghi gì (thêm --commit để ghi).")
