CALLS = []


def good_job(now):
    CALLS.append(now)


def bad_job(now):
    raise RuntimeError("job hỏng")
