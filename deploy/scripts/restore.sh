#!/usr/bin/env bash
# Khôi phục từ một bản sao lưu do backup.sh tạo ra.
#
#   ./scripts/restore.sh /đường/dẫn/db-20261127-010000.dump [media-20261127-010000.tar.gz]
#
# Nếu không chỉ tệp chứng từ, script tự tìm tệp media-<dấu thời gian>.tar.gz cùng thư mục.
#
# Thao tác này GHI ĐÈ toàn bộ dữ liệu hiện tại nên script:
#   1. kiểm tra cả hai tệp sao lưu đọc được (pg_restore --list, tar tzf) TRƯỚC khi đổi gì;
#   2. tự sao lưu hiện trạng (backup.sh) để còn đường lùi;
#   3. mới dừng app/worker và nạp lại dữ liệu.
set -Eeuo pipefail

. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

BUOC="chuẩn bị"
BAN_LUI=""
HOAN_TAT=0
DA_THAY_DOI=0
HUY=0  # người dùng chủ động huỷ ở bước xác nhận: không phải lỗi, không cần hướng dẫn lùi
# Bẫy EXIT (không phải ERR): `loi` kết thúc bằng `exit` và phần lớn lỗi đi qua dạng `lệnh || loi`
# (ví dụ chờ healthcheck quá 120 giây), nên bẫy ERR bỏ sót đúng những đường lỗi hay gặp nhất.
bao_loi_khoi_phuc() {
	[ "$HOAN_TAT" -eq 1 ] && return 0
	if [ "$HUY" -eq 1 ]; then
		printf 'Đã huỷ, chưa thay đổi gì.\n' >&2
		return 0
	fi
	printf 'LỖI: khôi phục dừng ở bước: %s\n' "$BUOC" >&2
	if [ "$DA_THAY_DOI" -eq 0 ]; then
		printf 'Chưa thay đổi gì trên hệ thống (dịch vụ vẫn đang chạy như trước).\n' >&2
		return 0
	fi
	if [ -n "$BAN_LUI" ]; then
		printf 'Hiện trạng trước khi khôi phục đã được sao lưu tại: %s\n' "$BAN_LUI" >&2
		printf 'Muốn quay về hiện trạng đó: %s/restore.sh %s\n' "$SCRIPTS_DIR" "$BAN_LUI" >&2
	fi
	printf 'Dịch vụ app/worker có thể đang dừng; khởi động lại bằng:\n' >&2
	printf '  %s up -d\n' "$(dc_cmd)" >&2
	printf 'Nếu dừng ở bước nạp chứng từ: chứng từ cũ nằm trong /app/media/.restore-old của volume\n' >&2
	printf 'media (KHÔNG xoá thư mục đó). Đưa về chỗ cũ bằng:\n' >&2
	printf '  %s run --rm -T --no-deps --entrypoint sh app -c %s\n' "$(dc_cmd)" \
		"'find /app/media/.restore-old -mindepth 1 -maxdepth 1 -exec mv -t /app/media {} +'" >&2
	return 0
}
trap bao_loi_khoi_phuc EXIT

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

# --- 1. Kiểm tra bản sao lưu trước khi phá huỷ bất cứ thứ gì ----------------
BUOC="kiểm tra tệp sao lưu (chưa thay đổi gì)"
say ""
say "Đang kiểm tra bản sao lưu đọc được ..."
dc exec -T db pg_restore --list >/dev/null <"$DB_FILE" ||
	loi "Tệp $DB_FILE không phải bản pg_dump -Fc đọc được. KHÔNG thay đổi gì."
if [ -n "$MEDIA_FILE" ]; then
	dc run --rm -T --no-deps --entrypoint tar app tzf - >/dev/null <"$MEDIA_FILE" ||
		loi "Tệp $MEDIA_FILE không đọc được. KHÔNG thay đổi gì."
fi
say "Bản sao lưu đọc được."

# --- 2. Xác nhận ------------------------------------------------------------
say ""
say "TOÀN BỘ dữ liệu hiện tại trong cơ sở dữ liệu $POSTGRES_DB sẽ bị thay thế."
read -r -p 'Nhập KHOI-PHUC để xác nhận: ' tra_loi
if [ "$tra_loi" != "KHOI-PHUC" ]; then
	HUY=1
	exit 2  # khác 0 để cron/script gọi biết là chưa khôi phục, nhưng không phải lỗi hệ thống
fi

# --- 3. Sao lưu hiện trạng để còn đường lùi ---------------------------------
BUOC="sao lưu hiện trạng trước khi khôi phục (chưa thay đổi gì)"
say ""
say "Đang sao lưu hiện trạng trước khi khôi phục ..."
"$SCRIPTS_DIR/backup.sh"
BAN_LUI=$(find "${BACKUP_DIR:-$DEPLOY_DIR/backups}" -maxdepth 1 -name 'db-*.dump' -type f -printf '%T@ %p\n' |
	sort -rn | head -1 | cut -d' ' -f2-)
say "Bản lùi: ${BAN_LUI:-(không xác định)}"

# --- 4. Khôi phục -----------------------------------------------------------
BUOC="dừng app/worker"
say ""
say "Đang dừng ứng dụng và worker (cơ sở dữ liệu vẫn chạy) ..."
DA_THAY_DOI=1  # từ đây hệ thống bắt đầu bị thay đổi
dc stop app worker

BUOC="nạp lại cơ sở dữ liệu"
say "Đang khôi phục cơ sở dữ liệu ..."
# --clean --if-exists: xoá đối tượng cũ trước khi nạp lại (chạy bằng role sở hữu schema).
# Một vài thông báo "does not exist" ở lần khôi phục trên CSDL rỗng là bình thường.
dc exec -T db pg_restore --clean --if-exists --no-owner --no-privileges \
	-U "$DB_OWNER_USER" -d "$POSTGRES_DB" <"$DB_FILE"

if [ -n "$MEDIA_FILE" ]; then
	BUOC="nạp lại chứng từ"
	say "Đang khôi phục chứng từ (giải nén ra thư mục tạm rồi mới thay chỗ) ..."
	# Giải nén xong mới chuyển chỗ: nếu tar lỗi giữa đường thì chứng từ hiện tại vẫn còn nguyên.
	# Thư mục tạm nằm trong chính volume media để `mv` không phải chép dữ liệu sang phân vùng khác.
	# `find -mindepth 1` bao gồm cả tệp ẩn (rm -rf media/* thì không).
	dc run --rm -T --no-deps --entrypoint sh app -c '
set -e
MOI=/app/media/.restore-new
CU=/app/media/.restore-old
rm -rf "$MOI" "$CU"
mkdir -p "$MOI" "$CU"
tar xzf - -C "$MOI"
find /app/media -mindepth 1 -maxdepth 1 ! -name .restore-new ! -name .restore-old -exec mv -t "$CU" {} +
find "$MOI" -mindepth 1 -maxdepth 1 -exec mv -t /app/media {} +
rm -rf "$MOI" "$CU"
' <"$MEDIA_FILE"
fi

# pg_restore nạp lại bảng nên phải cấp quyền lại cho role runtime.
BUOC="cấp lại quyền cho role runtime"
say "Đang cấp lại quyền cho role runtime $DB_APP_USER ..."
manage_owner apply_db_grants --role "$DB_APP_USER"

BUOC="khởi động lại dịch vụ"
say "Đang khởi động lại toàn bộ dịch vụ ..."
dc up -d
dc restart nginx
cho_dich_vu_khoe app
HOAN_TAT=1

say ""
say "=== Khôi phục xong ==="
say "Bản sao lưu hiện trạng trước khi khôi phục: ${BAN_LUI:-(không xác định)}"
say "Hãy kiểm tra: curl -k $SITE_URL/healthz và chạy kiểm tra chuỗi audit:"
say "    $(dc_cmd) exec app python src/manage.py audit_verify"
