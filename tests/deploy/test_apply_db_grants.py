"""Lệnh `apply_db_grants`: SQL cấp quyền cho role runtime `procurement_app`.

Phần lớn test chỉ xem SQL sinh ra (`--dry-run`). Test cuối cùng chạy thật trên cơ sở dữ liệu kiểm
thử với một role dùng-một-lần: đây là biện pháp cốt lõi của task (bảng chỉ-ghi-thêm và chứng từ lưu
vĩnh viễn) nên phải được chứng minh bằng hành vi của chính PostgreSQL, không phải bằng chuỗi SQL.
"""

import psycopg
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.core.management.commands.apply_db_grants import (
    APPEND_ONLY_TABLES,
    NO_TRUNCATE_TABLES,
    grant_statements,
)

TEST_ROLE = "procurement_app_pytest"


def test_append_only_tables_match_triggers():
    # cùng danh sách với migration 0002 của audit/budget
    assert APPEND_ONLY_TABLES == ("audit_auditevent", "budget_budgetentry")
    assert NO_TRUNCATE_TABLES == ("documents_document",)


def test_statements_grant_dml_and_future_tables():
    sql = "\n".join(grant_statements("procurement_app", "procurement"))
    assert "GRANT CONNECT ON DATABASE procurement TO procurement_app;" in sql
    assert "GRANT USAGE ON SCHEMA public TO procurement_app;" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO procurement_app;" in sql
    assert "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO procurement_app;" in sql
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO procurement_app;" in sql
    assert "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO procurement_app;" in sql


def test_statements_revoke_on_append_only_and_permanent_tables():
    statements = grant_statements("procurement_app", "procurement")
    sql = "\n".join(statements)
    assert (
        "REVOKE UPDATE, DELETE, TRUNCATE ON public.audit_auditevent, public.budget_budgetentry "
        "FROM procurement_app;" in sql
    )
    assert "REVOKE TRUNCATE ON public.documents_document FROM procurement_app;" in sql
    # REVOKE phải chạy SAU các GRANT, nếu không quyền bị cấp lại
    last_grant = max(i for i, s in enumerate(statements) if s.startswith(("GRANT", "ALTER DEFAULT")))
    first_revoke = min(i for i, s in enumerate(statements) if s.startswith("REVOKE"))
    assert first_revoke > last_grant


def test_invalid_identifier_refused():
    with pytest.raises(CommandError):
        grant_statements('app"; DROP TABLE x; --', "procurement")
    with pytest.raises(CommandError):
        grant_statements("procurement_app", "db; DROP")


def test_dry_run_prints_sql_in_vietnamese(capsys):
    call_command("apply_db_grants", "--role", "procurement_app", "--database-name", "procurement", "--dry-run")
    out = capsys.readouterr().out
    assert "REVOKE UPDATE, DELETE, TRUNCATE" in out
    assert "Chỉ in SQL" in out
    assert "procurement_app" in out


@pytest.fixture
def runtime_role(db):
    """Role dùng-một-lần trong cụm dữ liệu kiểm thử, đã được cấp quyền như procurement_app."""
    with connection.cursor() as cur:
        cur.execute(f"DROP ROLE IF EXISTS {TEST_ROLE}")
        cur.execute(f"CREATE ROLE {TEST_ROLE} LOGIN PASSWORD 'pytest-khong-bi-mat'")
    call_command("apply_db_grants", "--role", TEST_ROLE, verbosity=0)
    cfg = connection.settings_dict
    conn = psycopg.connect(
        dbname=cfg["NAME"],
        user=TEST_ROLE,
        password="pytest-khong-bi-mat",
        host=cfg["HOST"] or "localhost",
        port=cfg["PORT"] or 5432,
        autocommit=True,
    )
    try:
        yield conn
    finally:
        conn.close()
        with connection.cursor() as cur:
            cur.execute(f"DROP OWNED BY {TEST_ROLE}")  # bỏ các GRANT/ALTER DEFAULT PRIVILEGES
            cur.execute(f"DROP ROLE IF EXISTS {TEST_ROLE}")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("sql", "vi_sao"),
    [
        ("UPDATE audit_auditevent SET action = 'x'", "nhật ký audit chỉ được ghi thêm"),
        ("DELETE FROM audit_auditevent", "nhật ký audit chỉ được ghi thêm"),
        ("TRUNCATE audit_auditevent", "nhật ký audit chỉ được ghi thêm"),
        ("UPDATE budget_budgetentry SET note = 'x'", "bút toán ngân sách chỉ được ghi thêm"),
        ("DELETE FROM budget_budgetentry", "bút toán ngân sách chỉ được ghi thêm"),
        ("TRUNCATE budget_budgetentry", "bút toán ngân sách chỉ được ghi thêm"),
        ("TRUNCATE documents_document", "chứng từ lưu vĩnh viễn"),
    ],
)
def test_runtime_role_is_denied_by_postgres(runtime_role, sql, vi_sao):
    with runtime_role.cursor() as cur, pytest.raises(psycopg.errors.InsufficientPrivilege):
        cur.execute(sql)


@pytest.mark.django_db(transaction=True)
def test_runtime_role_can_still_do_normal_work(runtime_role):
    with runtime_role.cursor() as cur:
        # chỉ-ghi-thêm nghĩa là VẪN ghi thêm được
        cur.execute("SELECT count(*) FROM audit_auditevent")
        assert cur.fetchone()[0] >= 0
        # bảng nghiệp vụ thường: đủ quyền DML
        cur.execute(
            "INSERT INTO accounts_orgunit (code, name, kind, is_active) "
            "VALUES ('PYTEST-GRANTS', 'Thử quyền', 'PHONG', true) RETURNING id"
        )
        unit_id = cur.fetchone()[0]
        cur.execute("UPDATE accounts_orgunit SET name = 'Đã sửa' WHERE id = %s", (unit_id,))
        cur.execute("DELETE FROM accounts_orgunit WHERE id = %s", (unit_id,))
