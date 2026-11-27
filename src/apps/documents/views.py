from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from apps.audit.service import record

from .models import Document
from .permissions import can_view_object
from .storage import absolute_path

INLINE_MIMES = {"application/pdf", "image/png", "image/jpeg"}


def _serve(request, pk, inline: bool):
    doc = get_object_or_404(Document, pk=pk)
    if not can_view_object(request.user, doc.attached_to):
        return HttpResponseForbidden("Bạn không có quyền xem chứng từ này")
    path = absolute_path(doc.stored_path)
    if not path.is_file():
        raise Http404
    as_attachment = not (inline and doc.mime in INLINE_MIMES)
    response = FileResponse(
        open(path, "rb"),
        as_attachment=as_attachment,
        filename=doc.original_name,
        content_type=doc.mime,
    )
    response["X-Content-Type-Options"] = "nosniff"
    record(
        "document.downloaded",
        doc,
        actor=request.user,
        changes={"disposition": "attachment" if as_attachment else "inline"},
    )
    return response


@login_required
@require_GET
def download(request, pk):
    return _serve(request, pk, inline=False)


@login_required
@require_GET
def view_inline(request, pk):
    return _serve(request, pk, inline=True)
