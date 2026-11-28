"""Lệnh `create_sys_admin`: tạo tài khoản quản trị kỹ thuật đầu tiên (dùng trong `install.sh`)."""

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts import roles as R
from apps.accounts.models import User
from apps.audit.models import AuditEvent
from tests.factories import UserFactory


def _run(password="Mat-Khau-Rat-Dai-1", **kwargs):
    """Chạy lệnh với mật khẩu đọc từ stdin (như `install.sh` làm)."""
    out = io.StringIO()
    call_command(
        "create_sys_admin", password_stdin=True, stdin=io.StringIO(password + "\n"), stdout=out, **kwargs
    )
    return out.getvalue()


def test_creates_user_with_sys_admin_role(db):
    out = _run(username="itadmin", email="it@hsc.example.vn")
    user = User.objects.get(username="itadmin")
    assert user.is_active and user.email == "it@hsc.example.vn"
    assert not user.is_superuser and not user.is_staff  # /quan-tri/ dựa vào vai trò, không dựa is_staff
    assert user.check_password("Mat-Khau-Rat-Dai-1")
    assert R.has_role(user, R.SYS_ADMIN)
    assert AuditEvent.objects.filter(action="role.assigned").exists()
    assert "itadmin" in out


def test_refuses_when_a_sys_admin_already_exists(db):
    existing = UserFactory(username="cu")
    R.assign(existing, R.SYS_ADMIN)
    with pytest.raises(CommandError, match="đã có"):
        _run(username="moi", email="m@hsc.example.vn")
    assert not User.objects.filter(username="moi").exists()


def test_refuses_duplicate_username(db):
    UserFactory(username="trung")
    with pytest.raises(CommandError, match="Đã có người dùng"):
        _run(username="trung", email="t@hsc.example.vn")


def test_refuses_weak_password(db):
    with pytest.raises(CommandError, match="Mật khẩu"):
        _run(username="itadmin", email="it@hsc.example.vn", password="ngan")
    assert not User.objects.filter(username="itadmin").exists()
