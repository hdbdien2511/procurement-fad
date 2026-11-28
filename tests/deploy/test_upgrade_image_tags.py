"""`upgrade.sh`: thẻ `procurement-app:last-good` phải luôn trỏ vào ảnh ĐÃ chạy được.

Chạy thật `deploy/scripts/upgrade.sh` với một lệnh `docker` giả (môi trường kiểm thử không có Docker
daemon). Lệnh giả giữ một "sổ thẻ ảnh" trong tệp, nên kiểm tra được chuỗi sự kiện mà một máy chủ thật
sẽ gặp: nâng cấp lỗi → lỗi → thành công.

Kịch bản này là lý do thẻ tồn tại: nếu con trỏ được dịch ở ĐẦU mỗi lần chạy (hoặc dịch sang ảnh của
lần chạy trước), thì sau hai lần lỗi nó trỏ vào ảnh hỏng và bước lùi in ra sẽ phục hồi sai ảnh.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy"

# `docker` giả: sổ thẻ ảnh là tệp "thẻ<TAB>id". `compose build` sinh id mới cho :latest, mô phỏng
# việc dựng ảnh. FAIL_AT=<chuỗi> làm `compose run` (bước migrate) thất bại.
FAKE_DOCKER = r"""#!/usr/bin/env bash
store="$DOCKER_STORE"
touch "$store"
lay_id() { awk -F'\t' -v t="$1" '$1==t {print $2; exit}' "$store"; }
dat_the() {
	awk -F'\t' -v t="$1" '$1!=t' "$store" >"$store.tmp"
	mv "$store.tmp" "$store"
	printf '%s\t%s\n' "$1" "$2" >>"$store"
}
bo_the() {
	awk -F'\t' -v t="$1" '$1!=t' "$store" >"$store.tmp"
	mv "$store.tmp" "$store"
}
case "$1" in
info) exit 0 ;;
tag)
	id=$(lay_id "$2")
	[ -n "$id" ] || id="$2"
	dat_the "$3" "$id"
	exit 0
	;;
rmi)
	bo_the "$2"
	exit 0
	;;
inspect)
	ref="${!#}"
	if [ "$ref" = "fake-container-id" ]; then
		printf '%s\n' "${HEALTH:-healthy}"
		exit 0
	fi
	id=$(lay_id "$ref")
	[ -n "$id" ] || exit 1
	printf '%s\n' "$id"
	exit 0
	;;
image)
	shift
	case "$1" in
	inspect)
		ref="${!#}"
		id=$(lay_id "$ref")
		[ -n "$id" ] || exit 1
		printf '%s\n' "$id"
		exit 0
		;;
	ls)
		# chỉ cần hỗ trợ dạng --filter reference=procurement-app:before-* --format {{.Tag}}
		awk -F'\t' '$1 ~ /^procurement-app:before-/ {sub(/^procurement-app:/, "", $1); print $1}' "$store"
		exit 0
		;;
	esac
	exit 0
	;;
compose)
	shift
	while [ "${1:-}" = "-f" ]; do shift 2; done
	case "${1:-}" in
	version) printf 'v2.99.0\n'; exit 0 ;;
	ps) printf 'fake-container-id\n'; exit 0 ;;
	build)
		dat_the procurement-app:latest "sha256:$(date +%s%N)"
		exit 0
		;;
	exec) printf 'FAKE-DUMP\n'; exit 0 ;;
	run)
		if [ -n "${FAIL_AT:-}" ] && printf '%s' "$*" | grep -q -- "$FAIL_AT"; then
			printf 'loi gia lap o buoc %s\n' "$FAIL_AT" >&2
			exit 1
		fi
		printf 'FAKE-TAR\n'
		exit 0
		;;
	*) exit 0 ;;
	esac
	;;
esac
exit 0
"""

ENV_FILE = """DJANGO_SETTINGS_MODULE=config.settings.prod
SECRET_KEY=khong-bi-mat-trong-kiem-thu
ALLOWED_HOSTS=localhost,127.0.0.1
SITE_URL=https://mua-sam.test
APP_ENCRYPTION_KEY=khong-dung-den-trong-kiem-thu
TRUSTED_PROXY_COUNT=1
SECURE_SSL_REDIRECT=1
POSTGRES_DB=procurement
DB_OWNER_USER=procurement_owner
DB_OWNER_PASSWORD=khong-bi-mat
DB_APP_USER=procurement_app
DB_APP_PASSWORD=khong-bi-mat
DATABASE_URL=postgres://procurement_app:khong-bi-mat@db:5432/procurement
DATABASE_URL_OWNER=postgres://procurement_owner:khong-bi-mat@db:5432/procurement
BACKUP_KEEP=30
"""


@pytest.fixture
def may_chu_gia(tmp_path):
    """Bản sao thư mục deploy/ + `docker` giả; trả về hàm chạy upgrade.sh và hàm đọc sổ thẻ ảnh."""
    if shutil.which("bash") is None:  # pragma: no cover
        pytest.skip("cần bash")
    deploy = tmp_path / "repo" / "deploy"
    shutil.copytree(DEPLOY, deploy)
    (deploy / "certs").mkdir(exist_ok=True)
    (deploy / "certs" / "fullchain.pem").write_text("")
    (deploy / "certs" / "privkey.pem").write_text("")
    (deploy / ".env").write_text(ENV_FILE + f"BACKUP_DIR={deploy / 'backups'}\n", encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER, encoding="utf-8")
    fake.chmod(0o755)
    store = tmp_path / "the-anh.tsv"
    # hệ thống đang chạy ảnh "v1" trước lần nâng cấp đầu tiên
    store.write_text("procurement-app:latest\tsha256:v1\n", encoding="utf-8")

    def chay(fail_at=None):
        env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "DOCKER_STORE": str(store),
        }
        if fail_at:
            env["FAIL_AT"] = fail_at
        return subprocess.run(
            [str(deploy / "scripts" / "upgrade.sh")],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(tmp_path),
            timeout=120,
        )

    def the_anh():
        return dict(
            line.split("\t", 1)
            for line in store.read_text(encoding="utf-8").splitlines()
            if "\t" in line
        )

    def them_the(tag, image_id):
        with store.open("a", encoding="utf-8") as fh:
            fh.write(f"{tag}\t{image_id}\n")

    return chay, the_anh, them_the


def test_last_good_survives_failed_upgrades_and_follows_the_successful_one(may_chu_gia):
    chay, the_anh, _ = may_chu_gia

    # Lần 1: lỗi ở bước migrate (ảnh mới ĐÃ được dựng → :latest là ảnh chưa chạy được)
    r1 = chay(fail_at="migrate")
    assert r1.returncode != 0
    anh = the_anh()
    assert anh["procurement-app:last-good"] == "sha256:v1", "lần đầu phải gieo last-good từ ảnh đang chạy"
    assert anh["procurement-app:latest"] != "sha256:v1", "ảnh mới đã được dựng"
    assert "docker tag procurement-app:last-good procurement-app:latest" in r1.stderr
    hong_1 = anh["procurement-app:latest"]

    # Lần 2: lỗi lần nữa → last-good KHÔNG được chạm tới (đây là lỗi mà review chỉ ra)
    r2 = chay(fail_at="migrate")
    assert r2.returncode != 0
    anh = the_anh()
    assert anh["procurement-app:last-good"] == "sha256:v1"
    assert anh["procurement-app:latest"] not in ("sha256:v1", hong_1)

    # Lần 3: thành công → last-good phải là ảnh VỪA chạy được, không phải ảnh hỏng của lần 2
    r3 = chay()
    assert r3.returncode == 0, r3.stderr
    anh = the_anh()
    tot = anh["procurement-app:last-good"]
    assert tot == anh["procurement-app:latest"]
    assert tot not in ("sha256:v1", hong_1)


def test_before_tags_are_pruned_to_the_newest_five(may_chu_gia):
    """Thẻ `before-*` không được tích lại mãi: giữ 5 thẻ MỚI nhất, bỏ các thẻ cũ hơn.

    Các thẻ cũ được đặt sẵn (dấu thời gian theo giây nên chạy lại nhiều lần trong cùng một giây sẽ
    cho trùng thẻ, không kiểm tra được gì).
    """
    chay, the_anh, them_the = may_chu_gia
    cu = [f"20260101-00000{i}" for i in range(1, 7)]  # 6 thẻ cũ
    for i, ts in enumerate(cu):
        them_the(f"procurement-app:before-{ts}", f"sha256:cu{i}")

    r = chay()
    assert r.returncode == 0, r.stderr
    assert "Bỏ thẻ ảnh cũ" in r.stdout, "vòng dọn thẻ chưa chạy"

    before = sorted(t for t in the_anh() if t.startswith("procurement-app:before-"))
    assert len(before) == 5, before
    # thẻ bị bỏ phải là thẻ cũ nhất, và thẻ của lần chạy này (dấu thời gian hôm nay) phải còn
    assert f"procurement-app:before-{cu[0]}" not in before
    assert f"procurement-app:before-{cu[-1]}" in before
    assert any(not t.startswith("procurement-app:before-2026010") for t in before)
