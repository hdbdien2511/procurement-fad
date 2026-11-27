"""Kiểm tra tĩnh bộ cài đặt Docker trong `deploy/` (không cần Docker daemon).

Các khẳng định ở đây thay cho `docker compose config` / `shellcheck` khi môi trường kiểm thử không có
Docker: tệp compose phải phân tích được và đủ dịch vụ/volume/cổng, nginx không được phục vụ
`MEDIA_ROOT`, script phải đúng cú pháp bash và `.env.example` phải liệt kê đủ biến `prod.py` cần.
"""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"
COMPOSE = DEPLOY / "docker-compose.yml"
NGINX_CONF = DEPLOY / "nginx" / "nginx.conf"
DOCKERFILE = DEPLOY / "Dockerfile"
SCRIPTS = DEPLOY / "scripts"
SCRIPT_NAMES = ["install.sh", "upgrade.sh", "backup.sh", "restore.sh"]
INSTALL_DOC = REPO / "docs" / "05-ban-giao-it" / "huong-dan-cai-dat.md"


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_compose_has_expected_services_and_volumes(compose):
    assert set(compose["services"]) == {"db", "app", "worker", "nginx"}
    assert set(compose["volumes"]) == {"pgdata", "media", "static"}


def test_compose_db_is_postgres16_with_healthcheck_and_pgdata(compose):
    db = compose["services"]["db"]
    assert db["image"] == "postgres:16"
    assert db["healthcheck"]["test"]
    assert any(v.startswith("pgdata:") for v in db["volumes"])
    # init.sql nạp lúc khởi tạo cụm dữ liệu, chỉ đọc
    assert any("docker-entrypoint-initdb.d" in v and v.endswith(":ro") for v in db["volumes"])


def test_compose_app_and_worker_share_image_env_and_media(compose):
    app, worker = compose["services"]["app"], compose["services"]["worker"]
    assert app["build"]["dockerfile"] == "deploy/Dockerfile"
    assert app["image"] == worker["image"]
    for svc in (app, worker):
        assert ".env" in str(svc["env_file"])
        assert any(v.startswith("media:") for v in svc["volumes"])
        assert svc["depends_on"]["db"]["condition"] == "service_healthy"
    assert "run_worker" in " ".join(worker["command"])  # worker chạy job định kỳ, không chạy gunicorn
    assert "ports" not in worker and "ports" not in app  # chỉ nginx mở cổng ra ngoài


def test_compose_nginx_serves_443_static_and_readonly_certs(compose):
    nginx = compose["services"]["nginx"]
    assert [p for p in nginx["ports"] if str(p).startswith("443:")]
    assert all(not str(p).startswith("80:") for p in nginx["ports"])
    mounts = nginx["volumes"]
    assert any(m.startswith("./certs") and m.endswith(":ro") for m in mounts)
    assert any(m.startswith("static:") and m.endswith(":ro") for m in mounts)
    assert any("nginx.conf" in m and m.endswith(":ro") for m in mounts)
    # không mount media vào nginx: chứng từ chỉ đi qua tầng ứng dụng (kiểm soát quyền)
    assert not any(m.startswith("media:") for m in mounts)


def test_compose_sets_resource_limits(compose):
    for name, svc in compose["services"].items():
        assert "mem_limit" in svc, f"dịch vụ {name} thiếu mem_limit"


def test_every_compose_variable_is_written_by_install_script():
    """Không có `docker compose config` trong CI: thay vào đó kiểm tra mọi ${VAR} đều có trong .env."""
    raw = COMPOSE.read_text(encoding="utf-8")
    referenced = set(re.findall(r"(?<!\$)\$\{([A-Z][A-Z0-9_]*)\}", raw))
    assert referenced, "tệp compose không tham chiếu biến nào?"
    install = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    written = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", install, re.MULTILINE))
    assert not (referenced - written), f"install.sh chưa ghi vào .env: {sorted(referenced - written)}"


def test_compose_override_example_parses(compose):
    example = DEPLOY / "docker-compose.override.yml.example"
    data = yaml.safe_load(example.read_text(encoding="utf-8"))
    assert "nginx" in data["services"]


def _nginx_directives():
    """nginx.conf không kể dòng chú thích (chú thích có thể nhắc tới /media để giải thích)."""
    lines = NGINX_CONF.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_nginx_conf_never_serves_media():
    directives = _nginx_directives()
    assert "location /media" not in directives
    assert "/app/media" not in directives
    assert re.search(r"location\s+/static/", directives)


def test_nginx_conf_security_directives():
    conf = NGINX_CONF.read_text(encoding="utf-8")
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in conf
    assert "Strict-Transport-Security" in conf
    assert "X-Content-Type-Options" in conf and "nosniff" in conf
    assert "Referrer-Policy" in conf and "same-origin" in conf
    assert "client_max_body_size 26m;" in conf
    assert "limit_req_zone" in conf
    login_block = conf[conf.index("location /dang-nhap/") :]
    assert "limit_req zone=" in login_block[: login_block.index("}")]
    for header in ("X-Forwarded-For", "X-Forwarded-Proto", "Host"):
        assert f"proxy_set_header {header}" in conf


def test_dockerfile_runs_as_non_root_from_lockfile():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in text
    users = re.findall(r"^USER\s+(\S+)", text, re.MULTILINE)
    assert users and users[-1] not in {"root", "0"}
    assert "requirements.lock" in text
    assert "collectstatic" in text
    assert "HEALTHCHECK" in text and "/healthz" in text
    assert "gunicorn" in text and '"-w", "3"' in text


@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_scripts_are_executable_strict_bash(name):
    script = SCRIPTS / name
    assert script.stat().st_mode & 0o111, f"{name} chưa có quyền thực thi"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text


@pytest.mark.parametrize("path", sorted(SCRIPTS.glob("*.sh")) if SCRIPTS.exists() else [])
def test_scripts_pass_bash_syntax_check(path):
    proc = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_scripts_resolve_their_own_path(name):
    # chạy được từ thư mục bất kỳ: không dùng đường dẫn tương đối tới compose
    assert "BASH_SOURCE" in (SCRIPTS / name).read_text(encoding="utf-8") or "BASH_SOURCE" in (
        SCRIPTS / "_common.sh"
    ).read_text(encoding="utf-8")


def test_install_script_contract():
    text = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    for flag in ("--non-interactive", "--admin-user", "--admin-email"):
        assert flag in text
    for step in ("migrate", "apply_db_grants", "collectstatic", "enroll_totp", "create_sys_admin"):
        assert step in text
    assert "docker compose" in text or "dc " in text


def test_backup_and_restore_contract():
    backup = (SCRIPTS / "backup.sh").read_text(encoding="utf-8")
    assert "pg_dump" in backup and "-Fc" in backup
    assert "tar" in backup and "BACKUP_DIR" in backup
    assert "BACKUP_KEEP" in backup and "30" in backup
    restore = (SCRIPTS / "restore.sh").read_text(encoding="utf-8")
    assert "pg_restore" in restore
    upgrade = (SCRIPTS / "upgrade.sh").read_text(encoding="utf-8")
    assert "backup.sh" in upgrade and upgrade.index("backup.sh") < upgrade.index("migrate")
    assert "apply_db_grants" in upgrade


def test_init_sql_creates_runtime_role():
    sql = (DEPLOY / "postgres" / "init.sql").read_text(encoding="utf-8")
    assert "CREATE ROLE" in sql
    assert "DB_APP_PASSWORD" in sql


def _prod_env_names():
    source = (REPO / "src" / "config" / "settings" / "prod.py").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'(?:_required|env)\(\s*"([A-Z][A-Z0-9_]*)"', source)))


def test_env_example_lists_every_var_prod_reads():
    names = _prod_env_names()
    assert "SITE_URL" in names, "prod.py phải yêu cầu SITE_URL"
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    missing = [n for n in names if not re.search(rf"^#?\s*{n}=", example, re.MULTILINE)]
    assert not missing, f"Thiếu trong .env.example: {missing}"


def test_env_example_lists_docker_vars():
    example = (REPO / ".env.example").read_text(encoding="utf-8")
    for name in ("POSTGRES_DB", "DB_OWNER_USER", "DB_OWNER_PASSWORD", "DB_APP_USER", "DB_APP_PASSWORD", "DATABASE_URL_OWNER"):
        assert re.search(rf"^#?\s*{name}=", example, re.MULTILINE), name


def test_install_doc_covers_handover_topics():
    doc = INSTALL_DOC.read_text(encoding="utf-8")
    for needle in (
        "Ubuntu 26.04",
        "/oidc/callback/",
        "docker compose exec app python src/manage.py",
        "/healthz",
        "backup.sh",
        "restore.sh",
        "upgrade.sh",
        "SITE_URL",
        "APP_ENCRYPTION_KEY",
        "procurement_owner",
        "procurement_app",
        "SMTP",
    ):
        assert needle in doc, f"Hướng dẫn cài đặt thiếu: {needle}"


def test_readme_explains_env_loading():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "Docker Compose" in readme and ".env" in readme
