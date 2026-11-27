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
