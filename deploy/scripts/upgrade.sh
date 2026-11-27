#!/usr/bin/env bash
# Nâng cấp hệ thống sau khi cập nhật mã nguồn (git pull) trên máy chủ.
#
#   cd /opt/procurement && git pull && deploy/scripts/upgrade.sh
#
# Trình tự: sao lưu (scripts/backup.sh) → dựng/tải ảnh mới → migrate (role sở hữu schema) → cấp lại quyền → khởi động lại.
# Sao lưu luôn chạy TRƯỚC khi đổi bất cứ thứ gì để còn đường quay lại bằng scripts/restore.sh.
set -euo pipefail

. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

kiem_tra_docker
doc_env

say "=== Nâng cấp hệ thống mua sắm ==="
say "Bước 1/6: sao lưu trước khi nâng cấp"
"$SCRIPTS_DIR/backup.sh"

say "Bước 2/6: tải và dựng ảnh mới"
# --ignore-buildable cần Compose v2.22+; bản cũ hơn thì bỏ qua bước pull (ảnh ứng dụng dựng tại chỗ).
dc pull --ignore-buildable || canh_bao "Bỏ qua bước tải ảnh (docker compose pull không thành công)."
dc build --pull app

say "Bước 3/6: khởi động cơ sở dữ liệu"
dc up -d db
cho_dich_vu_khoe db

say "Bước 4/6: cập nhật lược đồ cơ sở dữ liệu (migrate, role $DB_OWNER_USER)"
manage_owner migrate --noinput
say "Bước 5/6: cấp lại quyền cho role runtime $DB_APP_USER (bảng mới sinh ra sau migrate)"
manage_owner apply_db_grants --role "$DB_APP_USER"

say "Bước 6/6: khởi động lại ứng dụng, worker và nginx"
dc up -d
dc restart app worker nginx
cho_dich_vu_khoe app
# Volume `static` dùng chung với nginx không tự cập nhật theo ảnh mới.
say "Đang gom lại tệp tĩnh vào volume dùng chung ..."
manage collectstatic --noinput >/dev/null

say ""
say "=== Nâng cấp xong ==="
say "Kiểm tra sống: curl -k $SITE_URL/healthz"
say "Nếu có sự cố: scripts/restore.sh <bản sao lưu vừa tạo ở bước 1>"
