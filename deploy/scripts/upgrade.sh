#!/usr/bin/env bash
# Nâng cấp hệ thống sau khi cập nhật mã nguồn (git pull) trên máy chủ.
#
#   cd /opt/procurement && git pull && deploy/scripts/upgrade.sh
#
# Trình tự: sao lưu (scripts/backup.sh) → gắn thẻ ảnh cũ thành procurement-app:previous → dựng ảnh
# mới → migrate (role sở hữu schema) → cấp lại quyền → khởi động lại → gom tệp tĩnh.
# Sao lưu luôn chạy TRƯỚC khi đổi bất cứ thứ gì, và ảnh cũ được giữ lại, nên lùi được về trước.
set -Eeuo pipefail

. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

BUOC="chuẩn bị"
BAN_LUI=""
MA_CU=""
bao_loi_nang_cap() {
	printf 'LỖI: nâng cấp dừng ở bước: %s\n' "$BUOC" >&2
	printf 'Cách lùi về phiên bản trước:\n' >&2
	printf '  1. git -C %s checkout %s\n' "$REPO_DIR" "${MA_CU:-<commit trước khi git pull>}" >&2
	printf '  2. docker tag procurement-app:previous procurement-app:latest\n' >&2
	if [ -n "$BAN_LUI" ]; then
		printf '  3. %s/restore.sh %s   (bắt buộc nếu bước migrate đã chạy)\n' "$SCRIPTS_DIR" "$BAN_LUI" >&2
	else
		printf '  3. %s/restore.sh <bản sao lưu mới nhất>   (bắt buộc nếu bước migrate đã chạy)\n' "$SCRIPTS_DIR" >&2
	fi
	printf '  4. docker compose -f %s up -d\n' "$COMPOSE_FILE" >&2
}
trap bao_loi_nang_cap ERR

kiem_tra_docker
doc_env

say "=== Nâng cấp hệ thống mua sắm ==="

BUOC="sao lưu trước khi nâng cấp (chưa thay đổi gì)"
say "Bước 1/6: sao lưu trước khi nâng cấp"
"$SCRIPTS_DIR/backup.sh"
BAN_LUI=$(find "${BACKUP_DIR:-$DEPLOY_DIR/backups}" -maxdepth 1 -name 'db-*.dump' -type f -printf '%T@ %p\n' |
	sort -rn | head -1 | cut -d' ' -f2-)
MA_CU=$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || true)

BUOC="dựng ảnh mới"
say "Bước 2/6: giữ lại ảnh đang chạy và dựng ảnh mới"
# Gắn thẻ ảnh đang chạy để lùi được bằng `docker tag procurement-app:previous procurement-app:latest`.
if docker image inspect procurement-app:latest >/dev/null 2>&1; then
	docker tag procurement-app:latest procurement-app:previous
	say "Ảnh đang chạy đã được gắn thẻ procurement-app:previous"
fi
# --ignore-buildable cần Compose v2.22+; bản cũ hơn thì bỏ qua bước pull (ảnh ứng dụng dựng tại chỗ).
dc pull --ignore-buildable || canh_bao "Bỏ qua bước tải ảnh (docker compose pull không thành công)."
dc build --pull app

BUOC="khởi động cơ sở dữ liệu"
say "Bước 3/6: khởi động cơ sở dữ liệu"
dc up -d db
cho_dich_vu_khoe db

BUOC="cập nhật lược đồ cơ sở dữ liệu (migrate ĐÃ chạy: phải khôi phục khi lùi)"
say "Bước 4/6: cập nhật lược đồ cơ sở dữ liệu (migrate, role $DB_OWNER_USER)"
manage_owner migrate --noinput

BUOC="cấp lại quyền cho role runtime"
say "Bước 5/6: cấp lại quyền cho role runtime $DB_APP_USER (bảng mới sinh ra sau migrate)"
manage_owner apply_db_grants --role "$DB_APP_USER"

BUOC="khởi động lại dịch vụ"
say "Bước 6/6: khởi động lại ứng dụng, worker và nginx"
# `up -d` tự tạo lại container của dịch vụ có ảnh/cấu hình thay đổi; không cần restart thêm.
dc up -d
cho_dich_vu_khoe app
# Volume `static` dùng chung với nginx không tự cập nhật theo ảnh mới.
say "Đang gom lại tệp tĩnh vào volume dùng chung ..."
manage collectstatic --noinput >/dev/null
trap - ERR

say ""
say "=== Nâng cấp xong ==="
say "Kiểm tra sống: curl -k $SITE_URL/healthz"
say "Bản sao lưu trước nâng cấp: ${BAN_LUI:-(không xác định)}"
say "Ảnh phiên bản trước: procurement-app:previous (giữ lại để lùi nếu cần)"
