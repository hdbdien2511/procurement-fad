# Procurement FAD

Hệ thống quản lý mua sắm và thanh toán nội bộ của HSC (Django 5.2, PostgreSQL 16).
Tài liệu thiết kế: `docs/superpowers/specs/`.

## Chạy kiểm thử cục bộ

```bash
uv venv --python /usr/bin/python3.12 .venv && source .venv/bin/activate
uv pip install -r requirements-dev.lock
# PostgreSQL 16 cần chạy sẵn; mặc định dùng
# DATABASE_URL=postgres://procurement:procurement@localhost:5432/procurement_test
pytest
```

Chạy ứng dụng: `cp .env.example .env`, rồi `python src/manage.py migrate && python src/manage.py runserver`.
Kiểm tra sống: `GET /healthz`.

## Cập nhật phụ thuộc

Sửa `pyproject.toml`, sau đó:

```bash
uv pip compile pyproject.toml -o requirements.lock
uv pip compile pyproject.toml --extra dev -o requirements-dev.lock
```
