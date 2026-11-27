"""Lệnh `apply_db_grants`: SQL cấp quyền cho role runtime `procurement_app`.

Chỉ kiểm tra SQL sinh ra (chế độ `--dry-run`): không thực thi lên CSDL kiểm thử vì lệnh thay đổi
quyền ở mức cụm dữ liệu.
"""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands.apply_db_grants import (
    APPEND_ONLY_TABLES,
    NO_TRUNCATE_TABLES,
    grant_statements,
)


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
