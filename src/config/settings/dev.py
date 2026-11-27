from .base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

# Khoá Fernet cố định chỉ dùng cho phát triển (không phải bí mật).
APP_ENCRYPTION_KEY = "1mpev1ghrQ6g_-Q8bTzrAbjwftD6uXDs3922QU1KYGY="
