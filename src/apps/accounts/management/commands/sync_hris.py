from django.core.management.base import BaseCommand, CommandError

from apps.accounts.services import sync_hris
from apps.integrations.fakes import FakeHrisClient


class Command(BaseCommand):
    help = "Đồng bộ đơn vị và nhân viên từ HRIS"

    def add_arguments(self, parser):
        parser.add_argument("--fake", metavar="PATH", help="Dùng file JSON HRIS giả")

    def handle(self, *args, **opts):
        if not opts["fake"]:
            raise CommandError("Chưa có HRIS thật; dùng --fake <đường dẫn JSON>.")
        report = sync_hris(FakeHrisClient(opts["fake"]))
        self.stdout.write(
            f"Tạo mới: {report.created}, cập nhật: {report.updated}, vô hiệu hoá: {report.deactivated}"
        )
