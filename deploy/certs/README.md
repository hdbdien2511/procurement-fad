# Chứng chỉ TLS

Đặt chứng chỉ của máy chủ vào đúng thư mục này, đúng hai tên tệp (nginx mount thư mục này ở chế độ
chỉ đọc):

- `fullchain.pem` — chứng chỉ máy chủ kèm chuỗi trung gian;
- `privkey.pem` — khoá riêng (quyền `600`, chủ sở hữu là người chạy Docker).

Hai tệp `*.pem` **không** được commit vào repo (xem `.gitignore`).

Chứng chỉ do HSC cấp: xin từ bộ phận hạ tầng theo tên miền nội bộ của hệ thống.

Chứng chỉ tự ký, chỉ dùng để thử nghiệm:

```bash
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout privkey.pem -out fullchain.pem -subj "/CN=mua-sam.hsc.local"
```

Sau khi thay chứng chỉ mới, nạp lại nginx — chạy **từ thư mục `deploy/`** để Docker Compose nạp cả
`docker-compose.override.yml` nếu có:

```bash
cd .. && docker compose restart nginx
```
