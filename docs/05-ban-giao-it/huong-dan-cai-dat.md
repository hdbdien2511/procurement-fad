# Hướng dẫn cài đặt và vận hành — Hệ thống mua sắm HSC (đợt 1)

Tài liệu dành cho bộ phận **IT/hạ tầng** của HSC. Hệ thống chạy bằng Docker Compose trên **một máy
chủ Ubuntu 26.04** nội bộ: không cần Redis, không cần Celery, không gọi dịch vụ bên ngoài ngoài
Entra ID (nếu bật) và máy chủ SMTP của HSC.

Toàn bộ bộ cài đặt nằm trong thư mục `deploy/` của repo.

---

## 1. Chuẩn bị máy chủ

**Yêu cầu tối thiểu**

| Hạng mục | Mức đề nghị |
|---|---|
| Hệ điều hành | Ubuntu Server 26.04 LTS (64-bit) |
| CPU | 4 vCPU |
| RAM | 8 GB (giới hạn trong compose: app 1 GB, db 1 GB, worker 512 MB, nginx 256 MB) |
| Ổ đĩa | 100 GB SSD (CSDL + chứng từ lưu **vĩnh viễn**, nên theo dõi dung lượng) |
| Mạng | Mở cổng **443/TCP** từ mạng nội bộ HSC tới máy chủ (cổng **80/TCP** chỉ để chuyển hướng sang HTTPS; có thể không mở nếu không cần) |
| Ra ngoài | HTTPS tới `login.microsoftonline.com` và `graph.microsoft.com` (chỉ khi bật Entra ID); SMTP tới máy chủ thư của HSC |
| Phần mềm | Docker Engine 27+ kèm plugin Docker Compose v2, `git`, `openssl` |

**Cài Docker** (theo kho chính thức của Docker):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git openssl
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Kiểm tra: `docker compose version` phải in ra phiên bản v2.x.

**Đặt mã nguồn và chứng chỉ**

```bash
sudo mkdir -p /opt/procurement && sudo chown "$USER" /opt/procurement
git clone <địa chỉ repo nội bộ> /opt/procurement
cd /opt/procurement/deploy
# chứng chỉ TLS: xem deploy/certs/README.md
cp /đường/dẫn/fullchain.pem certs/fullchain.pem
cp /đường/dẫn/privkey.pem  certs/privkey.pem
chmod 600 certs/privkey.pem
```

---

## 2. Cài đặt

```bash
cd /opt/procurement/deploy
./scripts/install.sh --host mua-sam.hsc.local
```

Script làm lần lượt:

1. kiểm tra Docker và plugin Compose;
2. **từ chối chạy nếu đã có `deploy/.env`** (không ghi đè khoá bí mật đang dùng);
3. sinh `SECRET_KEY`, `APP_ENCRYPTION_KEY` (khoá Fernet) và mật khẩu cho hai role CSDL, ghi vào
   `deploy/.env` quyền `600`;
4. dựng ảnh, khởi động PostgreSQL và chờ healthcheck;
5. chạy `migrate` bằng role **`procurement_owner`**;
6. chạy `apply_db_grants` để cấp quyền cho role **`procurement_app`** và thu hồi quyền sửa/xoá trên
   các bảng chỉ-ghi-thêm;
7. khởi động `app`, `worker`, `nginx`, gom tệp tĩnh;
8. hỏi tạo **tài khoản quản trị kỹ thuật (`SYS_ADMIN`) đầu tiên** rồi in đường dẫn nạp mã xác thực
   hai lớp (TOTP) của tài khoản đó.

Chế độ cài tự động (không hỏi gì; mật khẩu tạm được in **một lần**):

```bash
./scripts/install.sh --non-interactive --host mua-sam.hsc.local \
  --admin-user quantri --admin-email it@hsc.example.vn
```

**Nạp TOTP:** đường dẫn `otpauth://...` in ra ở bước cuối phải được nhập ngay vào ứng dụng xác thực
(Microsoft Authenticator / Google Authenticator) của người quản trị. Đăng nhập bằng mật khẩu bắt
buộc có mã TOTP. Mất thiết bị thì chạy lại `enroll_totp` (xem mục 8).

**Kiểm tra sau khi cài:**

```bash
curl -k https://mua-sam.hsc.local/healthz    # → {"status": "ok", "db": "ok"}
```

Thử nghiệm không có chứng chỉ TLS: xem `deploy/docker-compose.override.yml.example` (chỉ dùng trong
môi trường thử, không dùng cho máy chủ thật).

---

## 3. Biến môi trường

Tệp `deploy/.env` do `install.sh` sinh ra. **`.env` được Docker Compose đọc**, không phải do
`manage.py` đọc. Tệp này **không** được nạp cả vào container: `docker-compose.yml` liệt kê đúng
những biến mà `app`/`worker` cần (khối `x-app-env`), nên mật khẩu của role sở hữu schema
(`DB_OWNER_PASSWORD`, `DATABASE_URL_OWNER`) **không có trong môi trường của ứng dụng** — đó là một
phần của biện pháp bảo vệ bảng chỉ-ghi-thêm. Khi chạy lệnh trực tiếp ngoài Docker (máy lập trình)
phải tự nạp: `set -a && . ./.env && set +a`.

Sửa `.env` xong phải khởi động lại: `cd /opt/procurement/deploy && docker compose up -d`.

> **Luôn chạy `docker compose` từ thư mục `/opt/procurement/deploy`** (không truyền `-f`): khi đó
> Compose tự nạp cả `docker-compose.override.yml` nếu có. Nếu buộc phải truyền `-f` thì phải truyền
> **cả hai** tệp, ví dụ
> `docker compose -f /opt/procurement/deploy/docker-compose.yml -f /opt/procurement/deploy/docker-compose.override.yml up -d`
> — thiếu tệp ghi đè là chạy với cấu hình khác lúc cài. Các script trong `scripts/` tự xử lý việc này.

| Biến | Bắt buộc | Ý nghĩa |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | có | Luôn là `config.settings.prod` trên máy chủ |
| `SECRET_KEY` | có | Khoá ký phiên/CSRF của Django. Đổi khoá = mọi phiên đăng nhập mất hiệu lực |
| `ALLOWED_HOSTS` | có | Danh sách tên miền được phục vụ, cách nhau bằng dấu phẩy. **Phải giữ `localhost,127.0.0.1`** vì healthcheck của container gọi `http://127.0.0.1:8000/healthz` |
| `SITE_URL` | có | Địa chỉ gốc (`https://<tên miền>`) dùng dựng liên kết tuyệt đối trong email nhắc việc |
| `APP_ENCRYPTION_KEY` | có | Khoá Fernet mã hoá dữ liệu nhạy cảm trong CSDL (mật khẩu SMTP khai trên giao diện). **Mất khoá là không đọc lại được** các giá trị đã mã hoá — sao lưu cùng `.env` |
| `DATABASE_URL` | có | Kết nối của ứng dụng, dùng role `procurement_app` (chỉ DML) |
| `DATABASE_URL_OWNER` | có | Kết nối của role `procurement_owner`, chỉ dùng cho `migrate` và `apply_db_grants`; **không** được truyền vào container `app`/`worker` |
| `POSTGRES_DB`, `DB_OWNER_USER`, `DB_OWNER_PASSWORD` | có | Cấu hình container PostgreSQL (role sở hữu schema) |
| `DB_APP_USER`, `DB_APP_PASSWORD` | có | Role runtime; `deploy/postgres/init.sql` tạo role này khi khởi tạo cụm dữ liệu |
| `TRUSTED_PROXY_COUNT` | không | Số proxy tin cậy trước ứng dụng. Có nginx = `1` (để audit ghi đúng IP người dùng) |
| `SECURE_SSL_REDIRECT` | không | `1` (mặc định) chuyển hướng HTTP sang HTTPS; chỉ đặt `0` khi thử nghiệm không TLS |
| `OIDC_RP_CLIENT_ID`, `OIDC_RP_CLIENT_SECRET`, `OIDC_OP_TENANT_ID` | không | Đăng nhập Entra ID. Bỏ trống cả ba = tắt, dùng mật khẩu + TOTP |
| `BACKUP_DIR`, `BACKUP_KEEP` | không | Nơi lưu và số bản sao lưu giữ lại (mặc định `deploy/backups`, 30 bản) |

**Không có biến môi trường cho SMTP.** Thông số máy chủ thư (địa chỉ, cổng, TLS, tài khoản, mật
khẩu, người gửi) khai trên **giao diện quản trị** của hệ thống; mật khẩu được mã hoá bằng
`APP_ENCRYPTION_KEY` trước khi lưu. Các tham số nghiệp vụ (hạn mức, cửa sổ chia nhỏ, dung lượng tải
lên...) cũng khai trên giao diện, không đặt trong `.env`.

---

## 4. Cấu hình Entra ID (đăng nhập một lần)

Trong Microsoft Entra ID → **App registrations** → *New registration*:

1. Tên: `HSC Procurement`; loại: *Accounts in this organizational directory only*.
2. **Redirect URI** (loại *Web*): `https://<tên miền>/oidc/callback/`
   — ví dụ `https://mua-sam.hsc.local/oidc/callback/` (có dấu `/` ở cuối).
3. **Certificates & secrets** → *New client secret* → lấy giá trị, hẹn lịch gia hạn trước khi hết hạn.
4. **API permissions**: `openid`, `email`, `profile` (Microsoft Graph, delegated) → *Grant admin consent*.
5. Ghi ba giá trị vào `deploy/.env`: `OIDC_RP_CLIENT_ID` (Application ID),
   `OIDC_RP_CLIENT_SECRET`, `OIDC_OP_TENANT_ID` (Directory ID) rồi `docker compose up -d`.

Hệ thống **không tự tạo người dùng** từ Entra ID: người dùng phải tồn tại (đồng bộ từ HRIS) và có
`entra_oid` khớp. Ai chưa có tài khoản trong hệ thống thì bị từ chối đăng nhập.

---

## 5. Sao lưu

```bash
/opt/procurement/deploy/scripts/backup.sh
```

Mỗi lần chạy tạo trong `BACKUP_DIR` hai tệp có dấu thời gian:

- `db-<YYYYmmdd-HHMMSS>.dump` — `pg_dump -Fc` (nén, dùng cho `pg_restore`);
- `media-<YYYYmmdd-HHMMSS>.tar.gz` — toàn bộ chứng từ (`MEDIA_ROOT`).

Chỉ giữ lại `BACKUP_KEEP` bản mới nhất của mỗi loại (mặc định 30). Biến truyền trực tiếp cho lệnh
thắng giá trị trong `.env`: `BACKUP_DIR=/mnt/backup ./scripts/backup.sh`.

Tệp được ghi ra `*.partial` rồi mới đổi tên khi thành công, nên một bản dở dang (hết đĩa, mất kết
nối) không bao giờ bị tính là bản sao lưu hợp lệ. Nếu thấy tệp `*.partial` còn lại thì lần chạy đó
đã lỗi — xem log cron.

Hẹn giờ hằng ngày (ví dụ 1 giờ sáng) trong `crontab -e`:

```cron
0 1 * * * /opt/procurement/deploy/scripts/backup.sh >> /var/log/procurement-backup.log 2>&1
```

**Phải sao bản sao lưu ra ngoài máy chủ** (lưu trữ tập trung/băng từ) theo quy định của HSC, kèm
**bản sao `deploy/.env`** giữ ở nơi an toàn: thiếu `APP_ENCRYPTION_KEY` thì không giải mã lại được
dữ liệu nhạy cảm trong bản sao lưu.

## 6. Khôi phục

```bash
/opt/procurement/deploy/scripts/restore.sh /đường/dẫn/db-20261127-010000.dump
```

Trình tự của script:

1. **kiểm tra hai tệp sao lưu đọc được** (`pg_restore --list`, `tar tzf`) — nếu tệp hỏng thì dừng
   ngay, **chưa thay đổi gì**;
2. hỏi xác nhận (phải nhập đúng `KHOI-PHUC`);
3. **sao lưu hiện trạng** (gọi `backup.sh`) và in ra đường dẫn "bản lùi" — nếu khôi phục sai bản thì
   còn đường quay lại;
4. dừng `app` và `worker` (CSDL vẫn chạy);
5. nạp lại CSDL (`pg_restore --clean --if-exists`);
6. nạp lại chứng từ: giải nén ra thư mục tạm **trong** volume media rồi mới đổi chỗ (chứng từ hiện
   tại chỉ bị thay sau khi giải nén xong);
7. cấp lại quyền cho role runtime (`apply_db_grants`) vì `pg_restore` tạo lại bảng;
8. khởi động lại toàn bộ dịch vụ (kể cả nginx).

Nếu script dừng giữa đường, nó in ra bước đang chạy, đường dẫn bản lùi và lệnh cần chạy tiếp.

Sau khi khôi phục nên kiểm tra chuỗi nhật ký audit:

```bash
cd /opt/procurement/deploy && docker compose exec app python src/manage.py audit_verify
```

## 7. Nâng cấp

```bash
cd /opt/procurement && git pull && deploy/scripts/upgrade.sh
```

Thứ tự: **sao lưu trước** → giữ ảnh đang chạy (thẻ `procurement-app:before-<dấu thời gian>`, và
`procurement-app:previous` nếu chưa có) → dựng/tải ảnh mới → `migrate` (role owner) →
`apply_db_grants` → khởi động lại → gom lại tệp tĩnh → dịch thẻ `previous` sang ảnh vừa thay ra.

**Thẻ `previous` luôn là bản tốt gần nhất:** nó chỉ được dịch ở cuối một lần nâng cấp **thành
công**, nên chạy lại `upgrade.sh` sau một lần lỗi không ghi đè nó bằng ảnh hỏng. Ngoài ra mỗi lần
chạy để lại một thẻ `before-<dấu thời gian>` riêng (không bao giờ bị ghi đè);
`docker image ls procurement-app` liệt kê tất cả.

### Lùi về phiên bản trước

`migrate` đã đổi lược đồ CSDL và ảnh mới đã mang tên `procurement-app:latest`, nên **chỉ chạy
`restore.sh` là chưa đủ**: phải đưa cả mã nguồn, ảnh và dữ liệu về cùng một mốc. Làm đủ bốn bước
(script cũng in đúng bốn bước này khi nâng cấp lỗi):

```bash
cd /opt/procurement
git checkout <commit trước khi git pull>              # 1. mã nguồn cũ
docker tag procurement-app:previous procurement-app:latest   # 2. ảnh cũ
deploy/scripts/restore.sh <bản sao lưu ở bước 1 của upgrade>  # 3. dữ liệu + lược đồ cũ
cd deploy && docker compose up -d                     # 4. khởi động lại
```

`upgrade.sh` in đường dẫn bản sao lưu, danh sách ảnh đang giữ và các bước lùi (kể cả khi nâng cấp
lỗi giữa đường); giữ lại thông tin này cho tới khi chắc chắn bản mới chạy tốt.

Nếu đã thử nâng cấp nhiều lần thì chọn ảnh theo dấu thời gian trong `docker image ls
procurement-app` thay vì tin thẻ `previous`.

---

## 8. Chạy lệnh quản trị

Lệnh chạy bằng role runtime trong container `app`:

```bash
cd /opt/procurement/deploy
docker compose exec app python src/manage.py <lệnh>
```

> Lưu ý: luôn chạy từ thư mục `deploy/` để Compose tìm thấy `docker-compose.yml`, `.env` **và**
> `docker-compose.override.yml` (nếu có). Xem khung lưu ý ở mục 3 nếu buộc phải truyền `-f`.

| Lệnh | Việc |
|---|---|
| `enroll_totp <tên đăng nhập>` | Tạo thiết bị TOTP và in đường dẫn `otpauth://` (khi người dùng mất thiết bị) |
| `create_sys_admin --username … --email …` | Tạo `SYS_ADMIN` đầu tiên (chỉ chạy được khi hệ thống chưa có `SYS_ADMIN` nào) |
| `sync_hris --fake <đường dẫn JSON>` | Đồng bộ đơn vị và người dùng từ tệp JSON HRIS. **Đợt 1 chưa nối HRIS thật** (kết nối thật thuộc đợt 4): chạy không có `--fake` thì lệnh báo lỗi |
| `import_budget <tệp.xlsx> --unit <mã đơn vị ngân sách> --year <năm> [--commit]` | Nhập sổ ngân sách từ workbook Budget Control. **Mặc định chạy thử** và chỉ in báo cáo làm sạch; thêm `--commit` mới ghi. Thêm `--org-unit <mã>` khi tạo mới đơn vị ngân sách, `--user <tên đăng nhập>` để ghi vào audit |
| `import_vendors <tệp.xlsx> [--commit]` | Nhập danh mục nhà cung cấp từ sheet `L9_Code`. Mặc định chạy thử, thêm `--commit` mới ghi |
| `audit_verify` | Kiểm tra chuỗi băm của nhật ký audit |
| `run_worker --once` | Chạy một lượt job định kỳ (gửi email tồn, nhắc SLA) để chẩn đoán |

**Đưa tệp .xlsx / .json vào container** trước khi nhập (container không thấy ổ đĩa máy chủ):

```bash
cd /opt/procurement/deploy
docker compose cp "/home/itadmin/Budget Control 2026.xlsx" app:/tmp/budget.xlsx
docker compose exec app python src/manage.py import_budget /tmp/budget.xlsx --unit ITD --year 2026
# xem báo cáo làm sạch, sửa Excel nếu cần, rồi chạy lại kèm --commit
docker compose exec app python src/manage.py import_budget /tmp/budget.xlsx --unit ITD --year 2026 --commit
```

Tệp trong `/tmp` của container mất khi container được tạo lại — đó là chỗ tạm, đúng mục đích.

Hai lệnh phải chạy bằng role **owner** (không dùng `exec app` thường). Chuỗi kết nối truyền qua môi
trường để không nằm trong danh sách tiến trình:

```bash
cd /opt/procurement/deploy
set -a && . ./.env && set +a        # nạp .env vào shell (chỉ cần khi chạy tay)
DATABASE_URL="$DATABASE_URL_OWNER" docker compose run --rm -e DATABASE_URL app \
  python src/manage.py migrate
DATABASE_URL="$DATABASE_URL_OWNER" docker compose run --rm -e DATABASE_URL app \
  python src/manage.py apply_db_grants
```

(`install.sh`/`upgrade.sh` đã làm sẵn hai bước này.)

---

## 9. Theo dõi và nhật ký

| Nội dung | Nơi xem |
|---|---|
| Kiểm tra sống | `GET https://<tên miền>/healthz` → `{"status": "ok", "db": "ok"}`; mã 503 = không kết nối được CSDL |
| Nhật ký ứng dụng | `docker compose logs -f app` (gunicorn: truy cập + lỗi, ra stdout) |
| Nhật ký worker | `docker compose logs -f worker` (email tồn, nhắc/leo thang SLA) |
| Nhật ký nginx | `docker compose logs -f nginx`, hoặc `/var/log/nginx/` trong container |
| Nhật ký PostgreSQL | `docker compose logs -f db` |
| Nhật ký nghiệp vụ | Bảng `audit_auditevent` (xem trên giao diện; `audit_verify` để kiểm tra toàn vẹn) |
| Trạng thái dịch vụ | `docker compose ps` (cột health của `db` và `app`) |

Nhật ký container xoay vòng ở mức 20 MB × 5 tệp cho mỗi dịch vụ (khai trong `docker-compose.yml`).
Toàn bộ dịch vụ đặt `restart: unless-stopped` nên tự khởi động lại sau khi máy chủ khởi động lại.

**Việc cần kiểm tra sau khi lên chạy thật (go-live)**

1. `curl -k https://<tên miền>/healthz` trả `{"status": "ok", "db": "ok"}`.
2. Đăng nhập được bằng tài khoản `SYS_ADMIN` kèm mã TOTP; vào được `/quan-tri/`.
3. Khai SMTP trên giao diện và gửi thử một email (nhắc việc tới đúng người nhận).
4. Khai các tham số hệ thống và tỷ giá; nhập sổ ngân sách năm và danh mục nhà cung cấp (chạy thử
   trước, xem báo cáo làm sạch, rồi chạy lại kèm `--commit`).
5. Đơn vị và người dùng đã có đủ: đợt 1 nạp bằng `sync_hris --fake <JSON do HRIS xuất>` (nối HRIS
   thật thuộc đợt 4), kiểm tra số đơn vị/người dùng khớp tệp nguồn và không có ai bị vô hiệu hoá oan.
6. Chạy thử `backup.sh` một lần và **thử khôi phục trên máy chủ thử nghiệm**.
7. Cron sao lưu đã được hẹn giờ; dung lượng ổ đĩa còn ít nhất 50%.
8. Chứng chỉ TLS đúng tên miền, còn hiệu lực; đã có lịch gia hạn.
9. Trình duyệt thấy đủ header `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
   `Referrer-Policy: same-origin`.
10. `docker compose ps` không còn container nào ở trạng thái `unhealthy`/`restarting`.

---

## 10. Ghi chú bảo mật (quan trọng khi vận hành)

- **Hai role CSDL.** `procurement_owner` sở hữu schema và chỉ dùng cho `migrate` /
  `apply_db_grants`. Vì nó là `POSTGRES_USER` của ảnh postgres nên nó **là superuser của cụm dữ
  liệu**: giữ mật khẩu của nó như khoá hệ thống. Chuỗi kết nối của role này
  (`DATABASE_URL_OWNER`) **không** được truyền vào container `app`/`worker` (xem `x-app-env` trong
  `docker-compose.yml`), chỉ được dùng từ máy chủ qua `docker compose run -e DATABASE_URL`.
  Ứng dụng chạy bằng `procurement_app`: chỉ có SELECT/INSERT/UPDATE/DELETE trên các bảng được cấp,
  không có quyền DDL. Không đổi `DATABASE_URL` sang role owner để "cho tiện" — làm vậy là trao
  quyền superuser cho tiến trình web và vô hiệu hoá toàn bộ phần dưới đây.
- **Bảng chỉ-ghi-thêm.** `audit_auditevent` và `budget_budgetentry` bị trigger CSDL chặn mọi
  `UPDATE`/`DELETE`, và `apply_db_grants` thu hồi luôn `UPDATE, DELETE, TRUNCATE` của role runtime.
  Nhật ký audit và bút toán ngân sách chỉ ghi thêm — sửa sai bằng bút toán điều chỉnh, không bằng
  sửa dữ liệu.
- **Chứng từ lưu vĩnh viễn.** `documents_document` bị thu hồi `TRUNCATE`; hệ thống không có chức
  năng xoá chứng từ.
- **nginx không phục vụ `MEDIA_ROOT`.** Chứng từ chỉ tải về qua tầng ứng dụng để kiểm tra quyền của
  từng người dùng. Không thêm `location /media` vào `deploy/nginx/nginx.conf` và không mount volume
  `media` vào nginx.
- **Khoá bí mật.** `deploy/.env` quyền `600`, chỉ người quản trị máy chủ đọc được; không commit,
  không gửi qua chat/email. Mật khẩu quản trị in ra ở chế độ `--non-interactive` chỉ hiện một lần và
  phải được đổi sau lần đăng nhập đầu.
- **Xác thực hai lớp.** Mọi tài khoản đăng nhập bằng mật khẩu đều phải có TOTP; tài khoản bị khoá
  tạm 15 phút sau 5 lần sai mật khẩu; phiên hết hạn sau 1800 giây không thao tác.
- **Phân tách nhiệm vụ.** `SYS_ADMIN` là quản trị kỹ thuật và **không** duyệt nghiệp vụ; đừng gán
  thêm vai trò duyệt cho tài khoản quản trị.
- **TLS.** Chỉ TLS 1.2/1.3, HSTS một năm. Khoá riêng để quyền `600`; thay chứng chỉ xong thì
  `docker compose restart nginx`.
