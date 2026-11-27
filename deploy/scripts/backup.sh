#!/usr/bin/env bash
# Sao lưu cơ sở dữ liệu (pg_dump -Fc) và thư mục chứng từ (MEDIA_ROOT) vào BACKUP_DIR.
#
#   ./scripts/backup.sh            # BACKUP_DIR và BACKUP_KEEP lấy từ .env
#   BACKUP_DIR=/mnt/backup ./scripts/backup.sh
#
# Mỗi lần chạy sinh hai tệp có dấu thời gian và chỉ giữ lại BACKUP_KEEP (mặc định 30) bản mới nhất.
# Hẹn giờ bằng cron, ví dụ 1 giờ sáng mỗi ngày:
#   0 1 * * * /opt/procurement/deploy/scripts/backup.sh >> /var/log/procurement-backup.log 2>&1
set -euo pipefail

. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

kiem_tra_docker
doc_env

BACKUP_DIR="${BACKUP_DIR:-$DEPLOY_DIR/backups}"
BACKUP_KEEP="${BACKUP_KEEP:-30}"
mkdir -p "$BACKUP_DIR"

TS=$(date '+%Y%m%d-%H%M%S')
DB_FILE="$BACKUP_DIR/db-$TS.dump"
MEDIA_FILE="$BACKUP_DIR/media-$TS.tar.gz"

say "Sao lưu cơ sở dữ liệu $POSTGRES_DB → $DB_FILE"
umask 077
dc exec -T db pg_dump -Fc -U "$DB_OWNER_USER" -d "$POSTGRES_DB" >"$DB_FILE"
[ -s "$DB_FILE" ] || loi "Bản sao lưu cơ sở dữ liệu rỗng: $DB_FILE"

say "Sao lưu chứng từ (MEDIA_ROOT) → $MEDIA_FILE"
dc run --rm -T --no-deps --entrypoint tar app czf - -C /app/media . >"$MEDIA_FILE"
[ -s "$MEDIA_FILE" ] || loi "Bản sao lưu chứng từ rỗng: $MEDIA_FILE"

# Dọn bản cũ: giữ BACKUP_KEEP bản mới nhất của mỗi loại.
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
