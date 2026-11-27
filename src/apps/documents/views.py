from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from apps.audit.service import record
from apps.budget_changes.models import BudgetChangeRequest
from apps.core.text import strip_accents
from apps.requisitions.models import Requisition

from . import search as doc_search
from .models import Document
from .permissions import can_view_object
from .storage import absolute_path

INLINE_MIMES = {"application/pdf", "image/png", "image/jpeg"}


def _serve(request, pk, inline: bool):
    doc = get_object_or_404(Document, pk=pk)
    if not can_view_object(request.user, doc.attached_to):
        return HttpResponseForbidden("Bạn không có quyền xem chứng từ này")
    path = absolute_path(doc.stored_path).resolve()
    if not path.is_relative_to(Path(settings.MEDIA_ROOT).resolve()) or not path.is_file():
        raise Http404
    as_attachment = not (inline and doc.mime in INLINE_MIMES)
    response = FileResponse(
        open(path, "rb"),
        as_attachment=as_attachment,
        filename=doc.original_name,
        content_type=doc.mime,
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox"
    response["Cache-Control"] = "private, no-store"
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


@login_required
@require_GET
def search(request):
    """Tìm chứng từ (toàn văn, không phân biệt dấu) và hồ sơ (số / tiêu đề) mà người dùng được xem."""
    query = (request.GET.get("q") or "").strip()
    documents, requisitions, budget_changes = [], [], []
    if query:
        documents = list(doc_search.search_documents(request.user, query)[:50])
        requisitions = list(
            Requisition.objects.visible_to(request.user)
            .filter(Q(number__unaccent__icontains=strip_accents(query))
                    | Q(title__unaccent__icontains=strip_accents(query)))[:50]
        )
        budget_changes = list(
            BudgetChangeRequest.objects.visible_to(request.user)
            .filter(Q(number__unaccent__icontains=strip_accents(query))
                    | Q(reason__unaccent__icontains=strip_accents(query)))[:50]
        )
    return render(request, "documents/search.html", {
        "heading": "Tìm kiếm chứng từ và hồ sơ",
        "q": query,
        "documents": documents,
        "requisitions": requisitions,
        "budget_changes": budget_changes,
    })
