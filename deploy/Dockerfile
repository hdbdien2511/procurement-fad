# Ảnh chạy ứng dụng mua sắm (dùng chung cho dịch vụ `app` và `worker`).
# Build từ gốc repo:  docker build -f deploy/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    TZ=Asia/Ho_Chi_Minh

# curl: dùng cho HEALTHCHECK. tzdata: giờ Việt Nam. Không cần libpq (psycopg[binary]).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl tzdata \
    && rm -rf /var/lib/apt/lists/*

# Người dùng không phải root (uid/gid cố định để quyền trên volume ổn định giữa các lần build).
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# Phụ thuộc khoá phiên bản; lớp này được cache khi mã nguồn thay đổi.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock

COPY pyproject.toml ./
COPY src ./src

RUN mkdir -p /app/staticfiles /app/media && chown -R app:app /app

USER app

# Gom tệp tĩnh ngay lúc build (settings `base` để không cần biến môi trường bắt buộc của prod).
# Volume `static` dùng chung với nginx được nạp từ lớp này ở lần khởi tạo đầu; các lần nâng cấp sau
# `upgrade.sh` chạy lại `collectstatic` để làm mới volume.
RUN DJANGO_SETTINGS_MODULE=config.settings.base python src/manage.py collectstatic --noinput

EXPOSE 8000

# /healthz được miễn chuyển hướng HTTPS (SECURE_REDIRECT_EXEMPT trong config/settings/prod.py).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--chdir", "/app/src", \
     "-w", "3", \
     "-b", "0.0.0.0:8000", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
