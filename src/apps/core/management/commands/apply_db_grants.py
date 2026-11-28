"""Lệnh `apply_db_grants`: cấp quyền chạy ứng dụng cho role runtime của PostgreSQL.

Hệ thống dùng **hai role CSDL** (xem `docs/05-ban-giao-it/huong-dan-cai-dat.md`):

- `procurement_owner` — sở hữu schema, chạy `migrate` và chính lệnh này;
- `procurement_app` — role mà tiến trình `app`/`worker` dùng khi chạy: chỉ có DML, **không** có
  quyền DDL.

Lệnh cấp SELECT/INSERT/UPDATE/DELETE trên mọi bảng và USAGE trên sequence cho role runtime, cho áp
dụng với cả bảng sinh ra sau này (ALTER DEFAULT PRIVILEGES), rồi **thu hồi** quyền sửa/xoá trên các
bảng chỉ-ghi-thêm (`audit_auditevent`, `budget_budgetentry`) và quyền TRUNCATE trên bảng chứng từ
(`documents_document` — chứng từ lưu vĩnh viễn). Trigger ở migration 0002 của `audit`/`budget` chặn
UPDATE/DELETE theo hàng; quyền CSDL ở đây chặn thêm TRUNCATE mà trigger không thấy.

Lệnh chạy lại được nhiều lần (GRANT/REVOKE là luỹ đẳng) và phải chạy bằng `procurement_owner`.
"""

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

# Bảng chỉ-ghi-thêm: giống danh sách trigger trong apps/audit/migrations/0002, apps/budget/migrations/0002
APPEND_ONLY_TABLES = ("audit_auditevent", "budget_budgetentry")
# Bảng lưu vĩnh viễn: xoá từng hàng đã bị chặn ở tầng ứng dụng, ở đây chỉ chặn TRUNCATE
NO_TRUNCATE_TABLES = ("documents_document",)

DML = "SELECT, INSERT, UPDATE, DELETE"
IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


def _ident(value, what):
    """Chỉ cho phép tên định danh đơn giản: SQL dưới đây ghép chuỗi nên không nhận ký tự lạ."""
    if not isinstance(value, str) or not IDENTIFIER.match(value):
        raise CommandError(f"{what} không hợp lệ: {value!r} (chỉ chữ thường, số và dấu gạch dưới).")
    return value


def grant_statements(role: str, database: str, schema: str = "public") -> list[str]:
    """Danh sách câu lệnh SQL cấp quyền cho `role`. Các REVOKE luôn nằm sau mọi GRANT."""
    role = _ident(role, "Tên role")
    database = _ident(database, "Tên cơ sở dữ liệu")
    schema = _ident(schema, "Tên schema")
    append_only = ", ".join(f"{schema}.{t}" for t in APPEND_ONLY_TABLES)
    statements = [
        f"GRANT CONNECT ON DATABASE {database} TO {role};",
        f"GRANT USAGE ON SCHEMA {schema} TO {role};",
        f"GRANT {DML} ON ALL TABLES IN SCHEMA {schema} TO {role};",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {role};",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT {DML} ON TABLES TO {role};",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT USAGE, SELECT ON SEQUENCES TO {role};",
        f"REVOKE UPDATE, DELETE, TRUNCATE ON {append_only} FROM {role};",
    ]
    statements += [f"REVOKE TRUNCATE ON {schema}.{t} FROM {role};" for t in NO_TRUNCATE_TABLES]
    return statements


class Command(BaseCommand):
    help = (
        "Cấp quyền DML cho role runtime (mặc định procurement_app) và thu hồi quyền sửa/xoá trên "
        "các bảng chỉ-ghi-thêm. Chạy bằng role sở hữu schema (procurement_owner)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--role", default="procurement_app", help="Role runtime được cấp quyền.")
        parser.add_argument("--schema", default="public", help="Schema chứa các bảng.")
        parser.add_argument(
            "--database-name",
            default=None,
            help="Tên cơ sở dữ liệu (mặc định lấy từ cấu hình Django).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Chỉ in SQL, không thực thi.")

    def handle(self, *args, **options):
        database = options["database_name"] or connection.settings_dict["NAME"]
        statements = grant_statements(options["role"], database, options["schema"])

        if options["dry_run"]:
            self.stdout.write(f"Chỉ in SQL (không thực thi) cho role {options['role']}:")
            for sql in statements:
                self.stdout.write(f"  {sql}")
            return

        with transaction.atomic(), connection.cursor() as cursor:
            for sql in statements:
                cursor.execute(sql)

        self.stdout.write(f"Đã cấp quyền trên cơ sở dữ liệu {database} cho role {options['role']}:")
        self.stdout.write(f"  - CONNECT, USAGE schema {options['schema']}, {DML} trên mọi bảng, USAGE sequence")
        self.stdout.write("  - áp dụng cho cả bảng/sequence tạo sau này (ALTER DEFAULT PRIVILEGES)")
        self.stdout.write(
            "  - thu hồi UPDATE, DELETE, TRUNCATE trên bảng chỉ-ghi-thêm: " + ", ".join(APPEND_ONLY_TABLES)
        )
        self.stdout.write("  - thu hồi TRUNCATE trên bảng lưu vĩnh viễn: " + ", ".join(NO_TRUNCATE_TABLES))
