-- Chạy MỘT LẦN khi cụm dữ liệu PostgreSQL được khởi tạo (docker-entrypoint-initdb.d).
--
-- Ảnh postgres đã tạo sẵn cơ sở dữ liệu POSTGRES_DB thuộc sở hữu của POSTGRES_USER
-- (= DB_OWNER_USER = procurement_owner, role chạy `migrate`). Tệp này chỉ tạo thêm role runtime
-- procurement_app (= DB_APP_USER) mà dịch vụ `app`/`worker` dùng.
--
-- Quyền của role runtime KHÔNG đặt ở đây mà do `manage.py apply_db_grants` cấp sau khi `migrate`
-- (lúc đó mới có bảng), kèm việc thu hồi UPDATE/DELETE/TRUNCATE trên các bảng chỉ-ghi-thêm.
--
-- Mật khẩu lấy từ biến môi trường của container (\getenv có từ PostgreSQL 14), không ghi vào tệp.

\getenv app_user DB_APP_USER
\getenv app_password DB_APP_PASSWORD

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user')
\gexec

-- Không cho role bất kỳ (PUBLIC) tạo đối tượng trong schema public: chỉ chủ sở hữu được tạo bảng.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
