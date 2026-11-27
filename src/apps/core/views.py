import logging

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render

logger = logging.getLogger(__name__)


def healthz(request):
    try:
        connection.ensure_connection()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:
        logger.exception("healthz: database check failed")
        return JsonResponse({"status": "error", "db": "error"}, status=503)
    return JsonResponse({"status": "ok", "db": "ok"})


@login_required
def home(request):
    return render(request, "home.html")
