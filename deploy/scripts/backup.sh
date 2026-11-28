#!/usr/bin/env bash
# Sao lưu cơ sở dữ liệu (pg_dump -Fc) và thư mục chứng từ (MEDIA_ROOT) vào BACKUP_DIR.
#
#   ./scripts/backup.sh                        # BACKUP_DIR, BACKUP_KEEP lấy từ .env
#   BACKUP_DIR=/mnt/backup ./scripts/backup.sh # giá trị truyền vào ưu tiên hơn .env
#
# Mỗi lần chạy sinh hai tệp có dấu thời gian và chỉ giữ lại BACKUP_KEEP (mặc định 30) bản mới nhất.
# Tệp được ghi ra `*.partial` rồi mới đổi tên khi thành công, nên bản dở dang không bao giờ bị tính
# là một bản sao lưu hợp lệ (và không bị vòng xoay giữ lại thay cho bản tốt).
#
# Hẹn giờ bằng cron, ví dụ 1 giờ sáng mỗi ngày:
#   0 1 * * * /opt/procurement/deploy/scripts/backup.sh >> /var/log/procurement-backup.log 2>&1
set -Eeuo pipefail

. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

# Giá trị do người gọi truyền vào phải thắng giá trị trong .env (doc_env ghi đè biến môi trường).
BACKUP_DIR_ARG="${BACKUP_DIR:-}"
BACKUP_KEEP_ARG="${BACKUP_KEEP:-}"

kiem_tra_docker
doc_env

BACKUP_DIR="${BACKUP_DIR_ARG:-${BACKUP_DIR:-$DEPLOY_DIR/backups}}"
BACKUP_KEEP="${BACKUP_KEEP_ARG:-${BACKUP_KEEP:-30}}"
mkdir -p "$BACKUP_DIR"

TS=$(date '+%Y%m%d-%H%M%S')
DB_FILE="$BACKUP_DIR/db-$TS.dump"
MEDIA_FILE="$BACKUP_DIR/media-$TS.tar.gz"

# Dọn tệp dở dang nếu script dừng giữa đường (và báo rõ đã dừng ở đâu).
trap 'rm -f -- "$DB_FILE.partial" "$MEDIA_FILE.partial"; printf "LỖI: sao lưu KHÔNG hoàn tất, không có bản mới trong %s\n" "$BACKUP_DIR" >&2' ERR

say "Sao lưu cơ sở dữ liệu $POSTGRES_DB → $DB_FILE"
umask 077
dc exec -T db pg_dump -Fc -U "$DB_OWNER_USER" -d "$POSTGRES_DB" >"$DB_FILE.partial"
[ -s "$DB_FILE.partial" ] || loi "Bản sao lưu cơ sở dữ liệu rỗng, đã bỏ: $DB_FILE"
mv -- "$DB_FILE.partial" "$DB_FILE"

say "Sao lưu chứng từ (MEDIA_ROOT) → $MEDIA_FILE"
# tar trả 1 khi có tệp bị ghi trong lúc đọc ("file changed as we read it"): chứng từ mới tải lên
# trong lúc sao lưu là chuyện bình thường, chỉ coi mã >= 2 là lỗi thật.
set +e
dc run --rm -T --no-deps --entrypoint tar app czf - -C /app/media . >"$MEDIA_FILE.partial"
tar_rc=$?
set -e
if [ "$tar_rc" -ge 2 ]; then
	loi "tar lỗi (mã $tar_rc) khi sao lưu chứng từ."
fi
if [ "$tar_rc" -eq 1 ]; then
	canh_bao "Có tệp chứng từ thay đổi trong lúc sao lưu (tar mã 1) — bản sao lưu vẫn dùng được."
fi
[ -s "$MEDIA_FILE.partial" ] || loi "Bản sao lưu chứng từ rỗng, đã bỏ: $MEDIA_FILE"
mv -- "$MEDIA_FILE.partial" "$MEDIA_FILE"
trap - ERR

# Dọn bản cũ: giữ BACKUP_KEEP bản mới nhất của mỗi loại (chỉ xét tệp đã hoàn tất).
don_ban_cu() {
	local pattern="$1" cu
	cu=$(find "$BACKUP_DIR" -maxdepth 1 -name "$pattern" -type f -printf '%T@ %p\n' |
		sort -rn | tail -n "+$((BACKUP_KEEP + 1))" | cut -d' ' -f2- || true)
	if [ -n "$cu" ]; then
		printf '%s\n' "$cu" | while IFS= read -r f; do
			say "Xoá bản sao lưu cũ: $f"
			rm -f -- "$f"
		done
	fi
}
don_ban_cu 'db-*.dump'
don_ban_cu 'media-*.tar.gz'

say "Xong. Kích thước: $(du -h "$DB_FILE" | cut -f1) (CSDL), $(du -h "$MEDIA_FILE" | cut -f1) (chứng từ)."
say "Hãy sao bản này ra thiết bị/lưu trữ ngoài máy chủ theo quy định của HSC."
