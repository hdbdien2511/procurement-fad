#!/usr/bin/env bash
# Khôi phục từ một bản sao lưu do backup.sh tạo ra.
#
#   ./scripts/restore.sh /đường/dẫn/db-20261127-010000.dump [media-20261127-010000.tar.gz]
#
# Nếu không chỉ tệp chứng từ, script tự tìm tệp media-<dấu thời gian>.tar.gz cùng thư mục.
# Thao tác này GHI ĐÈ toàn bộ dữ liệu hiện tại nên script hỏi xác nhận trước khi chạy.
set -euo pipefail

. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

DB_FILE="${1:-}"
[ -n "$DB_FILE" ] || loi "Thiếu tham số: restore.sh <tệp db-*.dump> [tệp media-*.tar.gz]"
[ -f "$DB_FILE" ] || loi "Không thấy tệp $DB_FILE"
DB_FILE=$(cd -- "$(dirname -- "$DB_FILE")" && printf '%s/%s' "$(pwd)" "$(basename -- "$DB_FILE")")

MEDIA_FILE="${2:-}"
if [ -z "$MEDIA_FILE" ]; then
	MEDIA_FILE="$(dirname -- "$DB_FILE")/$(basename -- "$DB_FILE" | sed 's/^db-/media-/; s/\.dump$/.tar.gz/')"
fi

kiem_tra_docker
doc_env

say "=== Khôi phục hệ thống mua sắm ==="
say "Cơ sở dữ liệu: $DB_FILE"
if [ -f "$MEDIA_FILE" ]; then
	say "Chứng từ:      $MEDIA_FILE"
else
	canh_bao "Không thấy tệp chứng từ $MEDIA_FILE — chỉ khôi phục cơ sở dữ liệu."
	MEDIA_FILE=""
fi
say ""
say "TOÀN BỘ dữ liệu hiện tại trong cơ sở dữ liệu $POSTGRES_DB sẽ bị thay thế."
read -r -p 'Nhập KHOI-PHUC để xác nhận: ' tra_loi
[ "$tra_loi" = "KHOI-PHUC" ] || loi "Đã huỷ: không khôi phục gì."

say "Đang dừng ứng dụng và worker (cơ sở dữ liệu vẫn chạy) ..."
dc stop app worker

say "Đang khôi phục cơ sở dữ liệu ..."
# --clean --if-exists: xoá đối tượng cũ trước khi nạp lại (chạy bằng role sở hữu schema).
# Một vài thông báo "does not exist" ở lần khôi phục trên CSDL rỗng là bình thường.
dc exec -T db pg_restore --clean --if-exists --no-owner --no-privileges \
	-U "$DB_OWNER_USER" -d "$POSTGRES_DB" <"$DB_FILE"

if [ -n "$MEDIA_FILE" ]; then
	say "Đang khôi phục chứng từ ..."
	dc run --rm -T --no-deps --entrypoint sh app \
		-c 'rm -rf /app/media/* && tar xzf - -C /app/media' <"$MEDIA_FILE"
fi

# pg_restore nạp lại bảng nên phải cấp quyền lại cho role runtime.
say "Đang cấp lại quyền cho role runtime $DB_APP_USER ..."
manage_owner apply_db_grants --role "$DB_APP_USER"

say "Đang khởi động lại toàn bộ dịch vụ ..."
dc up -d
cho_dich_vu_khoe app

say ""
say "=== Khôi phục xong ==="
say "Hãy kiểm tra: curl -k $SITE_URL/healthz và chạy kiểm tra chuỗi audit:"
say "    docker compose -f $COMPOSE_FILE exec app python src/manage.py audit_verify"
