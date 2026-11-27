import re
import unicodedata

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import F, Func, TextField, Value
from django.db.models.functions import Concat

from .models import Document
from .permissions import can_view_object


def normalize(q: str) -> str:
    """Bỏ dấu tiếng Việt ở phía truy vấn (khớp với unaccent phía cơ sở dữ liệu)."""
    q = q.replace("đ", "d").replace("Đ", "D")
    q = unicodedata.normalize("NFD", q)
    q = "".join(c for c in q if unicodedata.category(c) != "Mn")
    # cùng quy tắc với phía chỉ mục: dấu câu thành khoảng trắng (tránh "ten.pdf" thành một từ)
    return re.sub(r"[\W_]+", " ", q)


def refresh_search_vector(doc: Document) -> None:
    Document.objects.filter(pk=doc.pk).update(
        search_vector=SearchVector(
            Func(
                Func(
                    Concat(F("original_name"), Value(" "), F("text_content"), output_field=TextField()),
                    function="unaccent",
                    output_field=TextField(),
                ),
                Value(r"[^[:alnum:]]+"),
                Value(" "),
                Value("g"),
                function="regexp_replace",
                output_field=TextField(),
            ),
            config="simple",
        )
    )


def search_documents(user, q: str):
    """Tìm toàn văn (không phân biệt dấu) trong các chứng từ mà `user` được xem.

    Lọc quyền bằng Python trên tập ứng viên (đủ cho quy mô đợt 1).
    """
    q = normalize(q or "").strip()
    if not q:
        return Document.objects.none()
    query = SearchQuery(q, config="simple", search_type="plain")
    candidates = (
        Document.objects.filter(search_vector=query)
        .prefetch_related("attached_to")
    )
    allowed, cache = [], {}
    for doc in candidates:
        key = (doc.content_type_id, doc.object_id)
        if key not in cache:
            cache[key] = can_view_object(user, doc.attached_to)
        if cache[key]:
            allowed.append(doc.pk)
    return (
        Document.objects.filter(pk__in=allowed)
        .annotate(rank=SearchRank(F("search_vector"), query))
        .order_by("-rank", "-uploaded_at")
    )
