import logging
import signal
import threading
import time
from importlib import import_module

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import InterfaceError, OperationalError, close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)

TICK_SECONDS = 30


def _load(path):
    module, _, name = path.rpartition(".")
    return getattr(import_module(module), name)


def run_job(path, now):
    """Chạy một job; lỗi chỉ được ghi log để không làm chết worker."""
    close_old_connections()  # worker sống lâu: bỏ kết nối DB đã chết/quá hạn trước mỗi job
    try:
        _load(path)(now)
    except (OperationalError, InterfaceError):
        logger.exception("Job worker %s mất kết nối DB; thoát để container khởi động lại", path)
        raise
    except Exception:  # noqa: BLE001
        logger.exception("Job worker %s lỗi", path)


class Command(BaseCommand):
    help = "Chạy worker: các job định kỳ trong settings.WORKER_PERIODIC_JOBS (outbox email, SLA...)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Chạy mỗi job đúng một lần rồi thoát (cron/kiểm thử).")

    def handle(self, *args, **options):
        jobs = list(settings.WORKER_PERIODIC_JOBS)
        if options["once"]:
            for path, _interval in jobs:
                run_job(path, timezone.now())
            return

        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        next_run = {path: 0.0 for path, _ in jobs}
        self.stdout.write("Worker đã khởi động.")
        while not stop.is_set():
            mono = time.monotonic()
            for path, interval in jobs:
                if stop.is_set():
                    break
                if mono >= next_run[path]:
                    run_job(path, timezone.now())
                    next_run[path] = time.monotonic() + interval
            stop.wait(TICK_SECONDS)
        self.stdout.write("Worker đã dừng.")
