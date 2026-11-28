#!/usr/bin/env bash
# Hàm và biến dùng chung cho install.sh / upgrade.sh / backup.sh / restore.sh.
# Tệp này được `source`, không chạy trực tiếp. Mọi script tự xác định đường dẫn của mình nên chạy
# được từ thư mục bất kỳ.
# shellcheck shell=bash

SCRIPTS_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEPLOY_DIR=$(cd -- "$SCRIPTS_DIR/.." && pwd)
REPO_DIR=$(cd -- "$DEPLOY_DIR/.." && pwd)
COMPOSE_FILE="$DEPLOY_DIR/docker-compose.yml"
OVERRIDE_FILE="$DEPLOY_DIR/docker-compose.override.yml"
ENV_FILE="$DEPLOY_DIR/.env"
CERT_DIR="$DEPLOY_DIR/certs"

say() { printf '%s\n' "$*"; }
canh_bao() { printf 'CẢNH BÁO: %s\n' "$*" >&2; }
loi() {
	printf 'LỖI: %s\n' "$*" >&2
	exit 1
}

# `docker compose` với đúng tệp cấu hình (và tệp ghi đè nếu có).
dc() {
	local args=(-f "$COMPOSE_FILE")
	if [ -f "$OVERRIDE_FILE" ]; then
		args+=(-f "$OVERRIDE_FILE")
	fi
	docker compose "${args[@]}" "$@"
}

kiem_tra_docker() {
	command -v docker >/dev/null 2>&1 ||
		loi "Chưa cài Docker Engine. Xem docs/05-ban-giao-it/huong-dan-cai-dat.md mục 'Chuẩn bị máy chủ'."
	docker compose version >/dev/null 2>&1 ||
		loi "Thiếu plugin Docker Compose v2 (gói docker-compose-plugin)."
	docker info >/dev/null 2>&1 ||
		loi "Không kết nối được Docker daemon. Chạy bằng sudo hoặc thêm người dùng vào nhóm docker."
}

# Nạp .env vào môi trường của script (compose tự đọc tệp này cho các dịch vụ).
doc_env() {
	[ -f "$ENV_FILE" ] || loi "Không thấy $ENV_FILE. Hãy chạy scripts/install.sh trước."
	set -a
	# shellcheck disable=SC1090
	. "$ENV_FILE"
	set +a
}

# Lệnh manage.py bằng role runtime (procurement_app) trong container app đang chạy.
manage() { dc exec -T app python src/manage.py "$@"; }

# Lệnh manage.py bằng role sở hữu schema (procurement_owner): migrate, apply_db_grants.
# Chuỗi kết nối truyền qua môi trường của tiến trình (`-e DATABASE_URL` không kèm giá trị) nên không
# xuất hiện trong danh sách tham số của tiến trình docker trên máy chủ.
manage_owner() {
	DATABASE_URL="$DATABASE_URL_OWNER" dc run --rm -T -e DATABASE_URL app python src/manage.py "$@"
}

# Chờ healthcheck của một dịch vụ chuyển sang "healthy" (tối đa ~120 giây).
cho_dich_vu_khoe() {
	local service="$1" cid status
	say "Đang chờ dịch vụ $service sẵn sàng..."
	for _ in $(seq 1 60); do
		cid=$(dc ps -q "$service" 2>/dev/null || true)
		if [ -n "$cid" ]; then
			status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$cid" 2>/dev/null || true)
			if [ "$status" = "healthy" ]; then
				say "Dịch vụ $service đã sẵn sàng."
				return 0
			fi
		fi
		sleep 2
	done
	loi "Dịch vụ $service không sẵn sàng sau 120 giây. Xem log: docker compose -f $COMPOSE_FILE logs $service"
}

# Chuỗi bí mật an toàn, chỉ gồm ký tự base64url (không dấu, không khoảng trắng).
sinh_chuoi_bi_mat() {
	local bytes="${1:-48}"
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -base64 "$bytes" | tr -d '\n=' | tr '+/' '-_'
	else
		python3 -c "import secrets;print(secrets.token_urlsafe($bytes))"
	fi
}

# Khoá Fernet hợp lệ: 32 byte ngẫu nhiên mã hoá base64url (44 ký tự, kết thúc bằng '=').
sinh_khoa_fernet() {
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -base64 32 | tr -d '\n' | tr '+/' '-_'
	else
		python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
	fi
}
