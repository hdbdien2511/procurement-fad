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
        assert svc["environment"]["DATABASE_URL"]
        assert any(v.startswith("media:") for v in svc["volumes"])
        assert svc["depends_on"]["db"]["condition"] == "service_healthy"
    assert app["environment"] == worker["environment"]  # cùng bộ biến (YAML anchor)
    assert "run_worker" in " ".join(worker["command"])  # worker chạy job định kỳ, không chạy gunicorn
    assert "ports" not in worker and "ports" not in app  # chỉ nginx mở cổng ra ngoài


OWNER_VARS = ("DATABASE_URL_OWNER", "DB_OWNER_USER", "DB_OWNER_PASSWORD", "POSTGRES_PASSWORD")


def test_app_and_worker_never_see_the_schema_owner_credentials(compose):
    """Role sở hữu schema là superuser của cụm dữ liệu nên không được có trong container ứng dụng:
    rò biến môi trường hay RCE trong app sẽ vô hiệu hoá chính biện pháp chỉ-ghi-thêm của task này."""
    for name in ("app", "worker"):
        svc = compose["services"][name]
        # `.env` chứa mật khẩu owner nên không được nạp cả tệp vào container
        assert "env_file" not in svc, f"{name} không được dùng env_file: .env"
        env = svc["environment"]
        assert isinstance(env, dict)
        for var in OWNER_VARS:
            assert var not in env, f"{name} không được nhận biến {var}"
            for key, value in env.items():
                assert var not in str(value), f"{name}.{key} nội suy từ biến owner {var}"


def test_healthcheck_variables_are_defined_for_that_service(compose):
    """`$${VAR}` trong healthcheck do shell TRONG container giải nghĩa, nên biến phải tồn tại ở đó."""
    checked = 0
    for name, svc in compose["services"].items():
        hc = svc.get("healthcheck") or {}
        test = hc.get("test")
        if not test or hc.get("disable"):
            continue
        used = set(re.findall(r"\$\$\{?([A-Z][A-Z0-9_]*)\}?", " ".join(test)))
        if not used:
            continue
        checked += 1
        defined = set(svc.get("environment") or {})
        if svc.get("env_file"):  # cả tệp .env được nạp: không kiểm tra được ở đây
            continue
        missing = used - defined
        assert not missing, f"healthcheck của {name} dùng biến chưa khai báo cho dịch vụ đó: {sorted(missing)}"
    assert checked, "không có healthcheck nào dùng biến môi trường?"


def test_compose_nginx_serves_443_static_and_readonly_certs(compose):
    nginx = compose["services"]["nginx"]
    assert [p for p in nginx["ports"] if str(p).startswith("443:")]
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
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"' in conf
    assert "X-Content-Type-Options" in conf and "nosniff" in conf
    assert "Referrer-Policy" in conf and "same-origin" in conf
    assert "client_max_body_size 26m;" in conf
    assert "limit_req_zone" in conf
    for path in ("location /dang-nhap/", "location /xac-thuc-otp/"):
        block = conf[conf.index(path) :]
        assert "limit_req zone=" in block[: block.index("}")], path
    for header in ("X-Forwarded-For", "X-Forwarded-Proto", "Host"):
        assert f"proxy_set_header {header}" in conf
    # Django gửi cùng bốn header này: ẩn bản của ứng dụng để phản hồi không có header trùng
    for header in ("Strict-Transport-Security", "X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options"):
        assert f"proxy_hide_header {header};" in conf


def test_nginx_hsts_header_matches_what_django_would_send():
    """nginx ẩn header của ứng dụng và phát bản của mình, nên hai bên phải trùng từng chữ —
    nếu không thì `SECURE_HSTS_PRELOAD` ở prod chỉ là trang trí (directive bị mất trên đường ra)."""
    conf = NGINX_CONF.read_text(encoding="utf-8")
    prod = (REPO / "src" / "config" / "settings" / "prod.py").read_text(encoding="utf-8")
    assert "SECURE_HSTS_SECONDS = 31536000" in prod
    assert "SECURE_HSTS_INCLUDE_SUBDOMAINS = True" in prod
    assert "SECURE_HSTS_PRELOAD = True" in prod
    assert 'Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"' in conf


def test_nginx_port_80_only_redirects_to_https():
    directives = _nginx_directives()
    assert "listen 80;" in directives
    block = directives[directives.index("listen 80;") :]
    block = block[: block.index("}")]
    assert "return 301 https://$host$request_uri;" in block
    assert "proxy_pass" not in block and "root" not in block


def test_dockerfile_runs_as_non_root_from_lockfile():
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in text
    users = re.findall(r"^USER\s+(\S+)", text, re.MULTILINE)
    assert users and users[-1] not in {"root", "0"}
    assert "requirements.lock" in text
    assert "collectstatic" in text
    assert "HEALTHCHECK" in text and "/healthz" in text
    assert "gunicorn" in text and '"-w", "3"' in text


def test_dockerignore_keeps_build_context_small_and_free_of_secrets():
    """Bối cảnh build là gốc repo: khoá bí mật, chứng chỉ, bản sao lưu không được đi vào ảnh."""
    lines = {
        line.strip()
        for line in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for needed in (".git", ".venv", "graphify-out", ".env", "deploy/.env", "deploy/backups", "docs", "tests"):
        assert needed in lines, f".dockerignore thiếu {needed}"
    # những thứ Dockerfile thực sự COPY không được bị loại
    for kept in ("requirements.lock", "pyproject.toml", "src"):
        assert kept not in lines, f".dockerignore không được loại {kept}"


@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_scripts_are_executable_strict_bash(name):
    script = SCRIPTS / name
    assert script.stat().st_mode & 0o111, f"{name} chưa có quyền thực thi"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    # -E: bẫy ERR cũng có hiệu lực khi lỗi xảy ra bên trong hàm (dc, manage_owner, ...)
    assert "set -Eeuo pipefail" in text


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


def test_manage_owner_keeps_the_owner_url_out_of_the_docker_argv():
    """Mật khẩu owner không được nằm trong danh sách tham số (ai cũng đọc được bằng `ps`)."""
    common = (SCRIPTS / "_common.sh").read_text(encoding="utf-8")
    assert 'DATABASE_URL="$DATABASE_URL_OWNER" dc run --rm -T -e DATABASE_URL app' in common
    assert '-e DATABASE_URL="' not in common  # dạng truyền kèm giá trị


@pytest.mark.parametrize("name", ["backup.sh", "restore.sh", "upgrade.sh"])
def test_cleanup_and_report_run_on_every_failure_path(name):
    """`loi` kết thúc bằng `exit` và lỗi thường đi qua `lệnh || loi`, nên bẫy ERR không đủ:
    phải bẫy EXIT kèm cờ hoàn tất, nếu không hết thời gian chờ healthcheck sẽ không dọn/không báo."""
    text = (SCRIPTS / name).read_text(encoding="utf-8")
    assert "trap" in text and "EXIT" in text, f"{name} phải bẫy EXIT"
    assert "ERR\n" not in text.replace("EXIT", ""), f"{name} không nên chỉ dựa vào bẫy ERR"
    assert "HOAN_TAT=0" in text and "HOAN_TAT=1" in text, f"{name} thiếu cờ hoàn tất"


def test_printed_compose_commands_include_the_override_file():
    """Lệnh in ra cho người dùng phải kèm tệp ghi đè, nếu không họ chạy với cấu hình khác."""
    common = (SCRIPTS / "_common.sh").read_text(encoding="utf-8")
    assert "dc_cmd()" in common and "docker-compose.override.yml" in common.replace(
        "OVERRIDE_FILE", "docker-compose.override.yml"
    )
    for name in SCRIPT_NAMES + ["_common.sh"]:
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "docker compose -f" in line and "printf 'docker compose -f %s" not in line:
                assert "dc_cmd" in line, f"{name}: lệnh in ra phải dùng dc_cmd — {line.strip()}"


def test_backup_script_contract():
    backup = (SCRIPTS / "backup.sh").read_text(encoding="utf-8")
    assert "pg_dump" in backup and "-Fc" in backup
    assert "tar" in backup and "BACKUP_DIR" in backup
    assert "BACKUP_KEEP" in backup and "30" in backup
    # BACKUP_DIR/BACKUP_KEEP do người gọi truyền vào phải thắng giá trị trong .env
    assert "BACKUP_DIR_ARG" in backup and "BACKUP_KEEP_ARG" in backup
    assert backup.index("BACKUP_DIR_ARG=") < backup.index("\ndoc_env\n")
    # ghi ra .partial rồi mới đổi tên: bản dở dang không được tính là bản sao lưu
    assert ".partial" in backup and 'mv -- "$DB_FILE.partial"' in backup
    assert "trap don_dep_khi_thoat EXIT" in backup
    assert "tar_rc" in backup  # tar mã 1 (tệp thay đổi khi đọc) không phải lỗi chết


def test_restore_script_verifies_before_destroying():
    restore = (SCRIPTS / "restore.sh").read_text(encoding="utf-8")
    assert "pg_restore" in restore
    # kiểm tra cả hai tệp sao lưu TRƯỚC khi dừng dịch vụ / nạp lại dữ liệu
    assert "pg_restore --list" in restore and "tar tzf" in restore
    assert restore.index("pg_restore --list") < restore.index("dc stop app worker")
    # tự sao lưu hiện trạng để còn đường lùi, trước khi phá huỷ
    assert "backup.sh" in restore and restore.index("backup.sh") < restore.index("dc stop app worker")
    # không xoá thẳng media: giải nén ra thư mục tạm rồi đổi chỗ (và không bỏ sót tệp ẩn)
    assert "rm -rf /app/media/*" not in restore
    assert ".restore-new" in restore and "find /app/media -mindepth 1" in restore
    assert "trap bao_loi_khoi_phuc EXIT" in restore
    # người dùng huỷ ở bước xác nhận không phải lỗi: không in "dừng ở bước ..."
    assert "HUY=1" in restore and "Đã huỷ, chưa thay đổi gì." in restore
    assert "dc restart nginx" in restore


def test_upgrade_script_contract():
    upgrade = (SCRIPTS / "upgrade.sh").read_text(encoding="utf-8")
    assert "backup.sh" in upgrade and upgrade.index("backup.sh") < upgrade.index("migrate")
    assert "apply_db_grants" in upgrade
    # giữ ảnh cũ để lùi được, và in rõ đường lùi khi lỗi
    assert "trap bao_loi_nang_cap EXIT" in upgrade
    assert 'ANH_TOT="procurement-app:last-good"' in upgrade
    # thẻ last-good chỉ được dịch sang ảnh MỚI sau khi nâng cấp xong (ảnh đã thật sự chạy)
    assert upgrade.rindex('docker tag procurement-app:latest "$ANH_TOT"') > upgrade.index("collectstatic")
    # lần gieo thẻ ở đầu chỉ chạy khi thẻ CHƯA tồn tại
    assert 'if docker image inspect "$ANH_TOT"' in upgrade
    tag_block = upgrade[upgrade.index("BUOC=\"dựng ảnh mới\"") : upgrade.index("dc build")]
    assert "procurement-app:before-" in tag_block  # mỗi lần chạy giữ thêm một thẻ riêng
    assert "SO_THE_GIU" in upgrade and "docker rmi" in tag_block  # và dọn thẻ cũ
    assert 'printf \'  2. docker tag %s procurement-app:latest\\n\' "$ANH_TOT"' in upgrade
    assert "dc restart app worker nginx" not in upgrade  # `up -d` đã tạo lại container cần thiết


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
        # cú pháp lệnh phải đúng với lệnh thật (xem management/commands/*)
        "sync_hris --fake",
        "--commit",
        "docker compose cp",
        # lùi phiên bản mới dùng được: cần cả ảnh cũ, không chỉ bản sao lưu
        "procurement-app:last-good",
        # không được nói sai về quyền của role owner
        "superuser",
    ):
        assert needle in doc, f"Hướng dẫn cài đặt thiếu: {needle}"


def test_install_doc_command_syntax_matches_the_real_commands():
    """Hướng dẫn phải khớp tham số bắt buộc của lệnh (brief đợt 1: HRIS thật chưa có)."""
    doc = INSTALL_DOC.read_text(encoding="utf-8")
    assert "import_budget <tệp.xlsx> --unit" in doc
    assert "--year" in doc
    sync = (REPO / "src/apps/accounts/management/commands/sync_hris.py").read_text(encoding="utf-8")
    assert "--fake" in sync  # nếu lệnh đổi (nối HRIS thật) thì phải sửa lại hướng dẫn
    budget = (REPO / "src/apps/budget/management/commands/import_budget.py").read_text(encoding="utf-8")
    assert '"--unit", required=True' in budget and '"--year", required=True' in budget


def test_readme_explains_env_loading():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "Docker Compose" in readme and ".env" in readme
