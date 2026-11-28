"""Lệnh `create_sys_admin`: tạo tài khoản quản trị kỹ thuật (`SYS_ADMIN`) đầu tiên.

Dùng trong `deploy/scripts/install.sh` ngay sau `migrate`: lúc đó CSDL chưa có người dùng nào nên
không thể vào `/quan-tri/` để phân quyền. Lệnh chỉ chạy khi hệ thống **chưa có** `SYS_ADMIN` nào
(sau đó việc phân quyền làm trên giao diện) và luôn ghi nhật ký audit qua `roles.assign`.

`SYS_ADMIN` là quản trị kỹ thuật: không đặt `is_staff`/`is_superuser` (khu `/quan-tri/` kiểm tra vai
trò, xem `apps.workflow.admin`) và theo Ràng buộc chung thì vai trò này không duyệt nghiệp vụ.
"""

import sys

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts import roles as R
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Tạo tài khoản SYS_ADMIN đầu tiên (chỉ chạy khi hệ thống chưa có SYS_ADMIN nào)."
    stealth_options = ("stdin",)

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True, help="Tên đăng nhập.")
        parser.add_argument("--email", required=True, help="Thư điện tử.")
        parser.add_argument(
            "--password-stdin",
            action="store_true",
            help="Đọc mật khẩu từ dòng đầu của đầu vào chuẩn (thay vì hỏi tương tác).",
        )

    def _read_password(self, options):
        if options["password_stdin"]:
            stream = options.get("stdin") or sys.stdin
            password = stream.readline().rstrip("\n")
            if not password:
                raise CommandError("Không đọc được mật khẩu từ đầu vào chuẩn.")
            return password
        from getpass import getpass

        password = getpass("Mật khẩu (tối thiểu 12 ký tự): ")
        if password != getpass("Nhập lại mật khẩu: "):
            raise CommandError("Hai lần nhập mật khẩu không giống nhau.")
        return password

    @transaction.atomic
    def handle(self, *args, **options):
        username = options["username"].strip()
        if R.users_with_role(R.SYS_ADMIN).exists():
            raise CommandError("Hệ thống đã có tài khoản SYS_ADMIN; hãy phân quyền trên /quan-tri/.")
        if User.objects.filter(username=username).exists():
            raise CommandError(f"Đã có người dùng {username}.")

        password = self._read_password(options)
        user = User(username=username, email=options["email"].strip(), is_active=True)
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("Mật khẩu không hợp lệ: " + " ".join(exc.messages)) from exc

        user.set_password(password)
        user.save()
        R.assign(user, R.SYS_ADMIN, actor=user)
        self.stdout.write(f"Đã tạo tài khoản quản trị kỹ thuật {username} với vai trò SYS_ADMIN.")
        self.stdout.write("Bước tiếp theo: chạy `enroll_totp` để nạp mã xác thực hai lớp.")
