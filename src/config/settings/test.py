from .base import *  # noqa: F401,F403
from .base import env

import dj_database_url

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", "postgres://procurement:procurement@localhost:5432/procurement_test")
    )
}
ALLOWED_HOSTS = ["testserver", "localhost"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
AXES_ENABLED = False

# Khoá Fernet cố định chỉ dùng cho kiểm thử (không phải bí mật).
APP_ENCRYPTION_KEY = "1mpev1ghrQ6g_-Q8bTzrAbjwftD6uXDs3922QU1KYGY="

# Ứng dụng thử nghiệm chỉ có trong kiểm thử (model Dummy)
INSTALLED_APPS = [*INSTALLED_APPS, "tests.testapp"]  # noqa: F405
