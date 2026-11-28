import sys

from django.core.management.base import BaseCommand

from apps.audit.service import verify_chain


class Command(BaseCommand):
    help = "Kiểm tra chuỗi băm audit; exit code 1 nếu có bản ghi sai."

    def handle(self, *args, **opts):
        bad = verify_chain()
        self.stdout.write(f"Số bản ghi lỗi: {len(bad)}")
        if bad:
            self.stdout.write("ID: " + ", ".join(map(str, bad)))
            sys.exit(1)
