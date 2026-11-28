#!/usr/bin/env bash
# Nâng cấp hệ thống sau khi cập nhật mã nguồn (git pull) trên máy chủ.
#
#   cd /opt/procurement && git pull && deploy/scripts/upgrade.sh
#
# Trình tự: sao lưu (scripts/backup.sh) → giữ ảnh đang chạy (thẻ before-<dấu thời gian>) → dựng ảnh
# mới → migrate (role sở hữu schema) → cấp lại quyền → khởi động lại → gom tệp tĩnh → dịch thẻ
# procurement-app:last-good sang ảnh VỪA chạy tốt.
# Sao lưu luôn chạy TRƯỚC khi đổi bất cứ thứ gì, và ảnh cũ được giữ lại, nên lùi được về trước.
set -Eeuo pipefail

. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

BUOC="chuẩn bị"
BAN_LUI=""
MA_CU=""
HOAN_TAT=0
DA_THAY_DOI=0
# Thẻ "bản chạy tốt gần nhất": chỉ được dịch sang ảnh MỚI ở cuối một lần nâng cấp thành công, nên nó
# luôn là ảnh đã thật sự chạy được. Lần nâng cấp lỗi không chạm vào thẻ này.
ANH_TOT="procurement-app:last-good"
SO_THE_GIU=5  # số thẻ before-<dấu thời gian> giữ lại
# Bẫy EXIT (không phải ERR): `loi` kết thúc bằng `exit` và phần lớn lỗi đi qua dạng `lệnh || loi`
# (ví dụ chờ healthcheck quá 120 giây — đường lỗi hay gặp nhất), nên bẫy ERR bỏ sót hết các đường đó.
bao_loi_nang_cap() {
	[ "$HOAN_TAT" -eq 1 ] && return 0
	printf 'LỖI: nâng cấp dừng ở bước: %s\n' "$BUOC" >&2
	if [ "$DA_THAY_DOI" -eq 0 ]; then
		printf 'Chưa thay đổi gì trên hệ thống: sửa nguyên nhân rồi chạy lại upgrade.sh.\n' >&2
		return 0
	fi
	printf 'Cách lùi về phiên bản trước:\n' >&2
	printf '  1. git -C %s checkout %s\n' "$REPO_DIR" "${MA_CU:-<commit trước khi git pull>}" >&2
	printf '  2. docker tag %s procurement-app:latest\n' "$ANH_TOT" >&2
	if [ -n "$BAN_LUI" ]; then
		printf '  3. %s/restore.sh %s   (bắt buộc nếu bước migrate đã chạy)\n' "$SCRIPTS_DIR" "$BAN_LUI" >&2
	else
		printf '  3. %s/restore.sh <bản sao lưu mới nhất>   (bắt buộc nếu bước migrate đã chạy)\n' "$SCRIPTS_DIR" >&2
	fi
	printf '  4. %s up -d\n' "$(dc_cmd)" >&2
	printf 'Các ảnh còn giữ (%s KHÔNG bị thay đổi khi nâng cấp lỗi):\n' "$ANH_TOT" >&2
	docker image ls procurement-app --format '  {{.Repository}}:{{.Tag}}  {{.CreatedSince}}' >&2 || true
	return 0
}
trap bao_loi_nang_cap EXIT

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
# Mỗi lần chạy giữ ảnh đang chạy dưới một thẻ `before-<dấu thời gian>` riêng (không bao giờ bị ghi
# đè) để còn chọn đúng ảnh khi phải thử nhiều lần; chỉ giữ SO_THE_GIU thẻ mới nhất.
#
# Thẻ `last-good` thì KHÔNG đặt ở đây: nó chỉ được dịch sang ảnh mới ở cuối một lần nâng cấp thành
# công (xem bước cuối). Nhờ vậy "lỗi → lỗi → thành công" vẫn để lại `last-good` đúng là ảnh chạy
# được, chứ không phải ảnh hỏng của lần giữa. Lần đầu tiên (chưa có thẻ) thì gieo từ ảnh đang chạy.
if docker image inspect procurement-app:latest >/dev/null 2>&1; then
	docker tag procurement-app:latest "procurement-app:before-$(date '+%Y%m%d-%H%M%S')"
	if docker image inspect "$ANH_TOT" >/dev/null 2>&1; then
		say "Bản chạy tốt gần nhất: $ANH_TOT (giữ nguyên trong lúc nâng cấp)."
	else
		docker tag procurement-app:latest "$ANH_TOT"
		say "Lần đầu: gắn thẻ $ANH_TOT vào ảnh đang chạy."
	fi
fi
# Dọn các thẻ before-* cũ (chỉ bỏ thẻ, ảnh nào còn thẻ khác tham chiếu thì vẫn còn).
docker image ls --filter 'reference=procurement-app:before-*' --format '{{.Tag}}' |
	sort -r | tail -n "+$((SO_THE_GIU + 1))" | while IFS= read -r the; do
	say "Bỏ thẻ ảnh cũ: procurement-app:$the"
	docker rmi "procurement-app:$the" >/dev/null 2>&1 || true
done
DA_THAY_DOI=1  # từ đây ảnh/dịch vụ bắt đầu bị thay đổi
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

# Nâng cấp đã chạy xong và dịch vụ đã khoẻ: ảnh MỚI này mới là "bản chạy tốt gần nhất".
docker tag procurement-app:latest "$ANH_TOT"
HOAN_TAT=1

say ""
say "=== Nâng cấp xong ==="
say "Kiểm tra sống: curl -k $SITE_URL/healthz"
say "Bản sao lưu trước nâng cấp: ${BAN_LUI:-(không xác định)}"
say "Bản chạy tốt gần nhất giờ là ảnh vừa nâng cấp ($ANH_TOT)."
say "Muốn lùi về bản trước thì dùng thẻ before-<dấu thời gian> gần nhất dưới đây."
say "Các ảnh đang giữ:"
docker image ls procurement-app --format '  {{.Repository}}:{{.Tag}}  {{.CreatedSince}}' || true
