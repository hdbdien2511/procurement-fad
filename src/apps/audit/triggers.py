def install_append_only_trigger(table: str) -> str:
    """SQL tạo hàm + trigger chặn UPDATE/DELETE trên `table` (TRUNCATE xử lý bằng quyền DB)."""
    return f"""
CREATE OR REPLACE FUNCTION {table}_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'append-only table';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER {table}_append_only_trg
BEFORE UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION {table}_append_only();
"""


def drop_append_only_trigger(table: str) -> str:
    return f"""
DROP TRIGGER IF EXISTS {table}_append_only_trg ON {table};
DROP FUNCTION IF EXISTS {table}_append_only();
"""
