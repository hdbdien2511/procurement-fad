#!/usr/bin/env bash
# Cài đặt hệ thống mua sắm lên máy chủ Ubuntu 26.04 (chạy một lần).
#
#   ./scripts/install.sh --host mua-sam.hsc.local
#   ./scripts/install.sh --non-interactive --host mua-sam.hsc.local \
#        --admin-user quantri --admin-email it@hsc.example.vn
#
# Script KHÔNG ghi đè tệp .env đã có: muốn cài lại thì xoá/đổi tên .env và xoá volume dữ liệu.
set -Eeuo pipefail

. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

NON_INTERACTIVE=0
ADMIN_USER=""
ADMIN_EMAIL=""
HOST=""

in_huong_dan() {
	cat <<'HD'
Cách dùng: install.sh [tuỳ chọn]

  --host <tên miền>        Tên miền/địa chỉ người dùng truy cập (vào ALLOWED_HOSTS và SITE_URL)
  --admin-user <tên>       Tên đăng nhập của tài khoản quản trị kỹ thuật đầu tiên
  --admin-email <email>    Thư điện tử của tài khoản đó
  --non-interactive        Không hỏi gì; tự sinh mật khẩu quản trị và in ra MỘT lần
  -h, --help               In hướng dẫn này
HD
}

while [ $# -gt 0 ]; do
	case "$1" in
	--non-interactive) NON_INTERACTIVE=1 ;;
	--admin-user)
		ADMIN_USER="${2:-}"
		shift
		;;
	--admin-email)
		ADMIN_EMAIL="${2:-}"
		shift
		;;
	--host)
		HOST="${2:-}"
		shift
		;;
	-h | --help)
		in_huong_dan
		exit 0
		;;
	*) loi "Tham số không hiểu: $1 (xem --help)" ;;
	esac
	shift
done

say "=== Cài đặt hệ thống mua sắm HSC ==="
say "Mã nguồn: $REPO_DIR"

# --- 1. Kiểm tra môi trường -------------------------------------------------
kiem_tra_docker
if [ -f "$ENV_FILE" ]; then
	loi "Đã có $ENV_FILE. Script từ chối ghi đè cấu hình/khoá bí mật đang dùng."
fi

if [ -z "$HOST" ]; then
	[ "$NON_INTERACTIVE" -eq 1 ] && loi "Chế độ --non-interactive cần --host <tên miền>."
	read -r -p "Tên miền người dùng truy cập (ví dụ mua-sam.hsc.local): " HOST
fi
[ -n "$HOST" ] || loi "Tên miền không được để trống."

if [ -z "$ADMIN_USER" ]; then
	[ "$NON_INTERACTIVE" -eq 1 ] && loi "Chế độ --non-interactive cần --admin-user <tên đăng nhập>."
	read -r -p "Tên đăng nhập quản trị kỹ thuật đầu tiên: " ADMIN_USER
fi
if [ -z "$ADMIN_EMAIL" ]; then
	[ "$NON_INTERACTIVE" -eq 1 ] && loi "Chế độ --non-interactive cần --admin-email <email>."
	read -r -p "Thư điện tử của tài khoản đó: " ADMIN_EMAIL
fi
[ -n "$ADMIN_USER" ] && [ -n "$ADMIN_EMAIL" ] || loi "Tên đăng nhập và thư điện tử không được để trống."

# --- 2. Chứng chỉ TLS -------------------------------------------------------
if [ -f "$OVERRIDE_FILE" ]; then
	canh_bao "Có $OVERRIDE_FILE: cài ở chế độ thử nghiệm theo tệp ghi đè (có thể không dùng HTTPS)."
elif [ ! -f "$CERT_DIR/fullchain.pem" ] || [ ! -f "$CERT_DIR/privkey.pem" ]; then
	loi "Thiếu chứng chỉ TLS: cần $CERT_DIR/fullchain.pem và $CERT_DIR/privkey.pem.
Chứng chỉ tự ký để thử nghiệm:
  mkdir -p $CERT_DIR && openssl req -x509 -nodes -newkey rsa:2048 -days 365 \\
    -keyout $CERT_DIR/privkey.pem -out $CERT_DIR/fullchain.pem -subj \"/CN=$HOST\""
fi

# --- 3. Sinh khoá bí mật và ghi .env ----------------------------------------
say "Đang sinh khoá bí mật và tệp cấu hình $ENV_FILE ..."
SECRET_KEY=$(sinh_chuoi_bi_mat 48)
APP_ENCRYPTION_KEY=$(sinh_khoa_fernet)
DB_NAME=procurement
DB_OWNER_USER=procurement_owner
DB_APP_USER=procurement_app
DB_OWNER_PASSWORD=$(sinh_chuoi_bi_mat 24)
DB_APP_PASSWORD=$(sinh_chuoi_bi_mat 24)

umask 077
cat >"$ENV_FILE" <<EOF
# Tệp này do scripts/install.sh sinh ra lúc $(date '+%d/%m/%Y %H:%M:%S').
# CHỨA KHOÁ BÍ MẬT: không commit, không sao chép ra ngoài máy chủ, giữ quyền 600.
# Docker Compose đọc tệp này (không phải manage.py đọc) — xem huong-dan-cai-dat.md.
DJANGO_SETTINGS_MODULE=config.settings.prod

# Django
SECRET_KEY=$SECRET_KEY
# 127.0.0.1 và localhost cần giữ lại: healthcheck của container gọi http://127.0.0.1:8000/healthz
ALLOWED_HOSTS=$HOST,localhost,127.0.0.1
SITE_URL=https://$HOST
APP_ENCRYPTION_KEY=$APP_ENCRYPTION_KEY
TRUSTED_PROXY_COUNT=1
SECURE_SSL_REDIRECT=1

# PostgreSQL: procurement_owner sở hữu schema (migrate), procurement_app chạy ứng dụng
POSTGRES_DB=$DB_NAME
DB_OWNER_USER=$DB_OWNER_USER
DB_OWNER_PASSWORD=$DB_OWNER_PASSWORD
DB_APP_USER=$DB_APP_USER
DB_APP_PASSWORD=$DB_APP_PASSWORD
DATABASE_URL=postgres://$DB_APP_USER:$DB_APP_PASSWORD@db:5432/$DB_NAME
DATABASE_URL_OWNER=postgres://$DB_OWNER_USER:$DB_OWNER_PASSWORD@db:5432/$DB_NAME

# Sao lưu (scripts/backup.sh)
BACKUP_DIR=$DEPLOY_DIR/backups
BACKUP_KEEP=30

# Entra ID (bỏ trống = đăng nhập bằng mật khẩu + TOTP). Redirect URI: https://$HOST/oidc/callback/
OIDC_RP_CLIENT_ID=
OIDC_RP_CLIENT_SECRET=
OIDC_OP_TENANT_ID=
EOF
chmod 600 "$ENV_FILE"
doc_env

# --- 4. Dựng ảnh và khởi động cơ sở dữ liệu ---------------------------------
say "Đang dựng ảnh ứng dụng (lần đầu có thể mất vài phút) ..."
dc build
say "Đang khởi động cơ sở dữ liệu ..."
dc up -d db
cho_dich_vu_khoe db

# --- 5. Migrate + cấp quyền bằng role sở hữu schema -------------------------
say "Đang tạo lược đồ cơ sở dữ liệu (migrate, role $DB_OWNER_USER) ..."
manage_owner migrate --noinput
say "Đang cấp quyền cho role runtime $DB_APP_USER ..."
manage_owner apply_db_grants --role "$DB_APP_USER"

# --- 6. Khởi động ứng dụng --------------------------------------------------
say "Đang khởi động ứng dụng, worker và nginx ..."
dc up -d
cho_dich_vu_khoe app
# Volume `static` dùng chung với nginx: chạy lại collectstatic để volume khớp ảnh vừa dựng.
say "Đang gom tệp tĩnh vào volume dùng chung ..."
manage collectstatic --noinput >/dev/null

# --- 7. Tài khoản quản trị kỹ thuật đầu tiên --------------------------------
say ""
say "=== Tạo tài khoản quản trị kỹ thuật (SYS_ADMIN) ==="
if [ "$NON_INTERACTIVE" -eq 1 ]; then
	ADMIN_PASSWORD=$(sinh_chuoi_bi_mat 18)
	printf '%s\n' "$ADMIN_PASSWORD" |
		manage create_sys_admin --username "$ADMIN_USER" --email "$ADMIN_EMAIL" --password-stdin
	say ""
	say "MẬT KHẨU TẠM CỦA $ADMIN_USER (chỉ hiện MỘT lần, hãy đổi sau khi đăng nhập):"
	say "    $ADMIN_PASSWORD"
else
	dc exec app python src/manage.py create_sys_admin --username "$ADMIN_USER" --email "$ADMIN_EMAIL"
fi

say ""
say "Đang tạo thiết bị xác thực hai lớp (TOTP) cho $ADMIN_USER ..."
say "Nạp đường dẫn dưới đây vào ứng dụng xác thực (Microsoft/Google Authenticator):"
manage enroll_totp "$ADMIN_USER"

# --- 8. Xong ----------------------------------------------------------------
say ""
say "=== Cài đặt xong ==="
say "Kiểm tra sống:   curl -k https://$HOST/healthz   → {\"status\": \"ok\", \"db\": \"ok\"}"
say "Đăng nhập:       https://$HOST/dang-nhap/"
say "Việc cần làm tiếp (xem docs/05-ban-giao-it/huong-dan-cai-dat.md):"
say "  - khai báo SMTP và tham số hệ thống trên giao diện quản trị (không đặt trong .env)"
say "  - khai báo Entra ID nếu dùng đăng nhập một lần (redirect URI https://$HOST/oidc/callback/)"
say "  - hẹn lịch cron chạy scripts/backup.sh hằng ngày"
