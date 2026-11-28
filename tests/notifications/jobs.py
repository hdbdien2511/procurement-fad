CALLS = []


def good_job(now):
    CALLS.append(now)


def bad_job(now):
    raise RuntimeError("job hỏng")


def db_down_job(now):
    from django.db import OperationalError

    raise OperationalError("connection lost")
