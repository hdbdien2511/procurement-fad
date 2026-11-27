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

## Chạy ứng dụng cục bộ

`manage.py` **không tự đọc tệp `.env`** (không dùng thư viện dotenv): tệp `.env` chỉ được **Docker
Compose** đọc khi chạy bằng bộ cài đặt trong `deploy/`. Khi chạy cục bộ thì tự nạp biến vào shell:

```bash
cp .env.example .env
set -a && . ./.env && set +a          # nạp .env vào môi trường shell hiện tại
python src/manage.py migrate
python src/manage.py runserver
```

Kiểm tra sống: `GET /healthz` → `{"status": "ok", "db": "ok"}`.

## Cài đặt trên máy chủ (Docker)

Bộ cài đặt cho IT nằm ở `deploy/` (Dockerfile, docker-compose.yml, nginx, script cài/sao
lưu/khôi phục/nâng cấp). Hướng dẫn đầy đủ: `docs/05-ban-giao-it/huong-dan-cai-dat.md`.

```bash
cd deploy && ./scripts/install.sh --host mua-sam.hsc.local
```

`install.sh` sinh `deploy/.env` (khoá bí mật ngẫu nhiên) — Docker Compose đọc tệp này và truyền biến
vào các container. Lệnh quản trị chạy trong container:
`docker compose -f deploy/docker-compose.yml exec app python src/manage.py <lệnh>`.

## Cập nhật phụ thuộc

Sửa `pyproject.toml`, sau đó:

```bash
uv pip compile pyproject.toml -o requirements.lock
uv pip compile pyproject.toml --extra dev -o requirements-dev.lock
```
