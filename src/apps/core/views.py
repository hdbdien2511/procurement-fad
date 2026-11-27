from django.db import connection
from django.http import JsonResponse


def healthz(request):
    try:
        connection.ensure_connection()
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception:
        return JsonResponse({"status": "error", "db": "error"}, status=503)
    return JsonResponse({"status": "ok", "db": "ok"})
