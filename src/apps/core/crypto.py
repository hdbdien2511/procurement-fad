from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class DecryptionError(Exception):
    """Không giải mã được: token bị sửa đổi hoặc sai khoá."""


def _fernet() -> Fernet:
    return Fernet(settings.APP_ENCRYPTION_KEY)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise DecryptionError("Không giải mã được dữ liệu (sai khoá hoặc dữ liệu bị thay đổi).") from exc
