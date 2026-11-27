import hashlib
import uuid
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from apps.audit.service import record
from apps.core.services import get_setting

from . import extract, search
from .models import DOC_TYPES, Document

CHUNK = 64 * 1024

# phần mở rộng -> mime (không tin content_type do client gửi)
ALLOWED = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
SIGNATURES = {
    ".pdf": b"%PDF-",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".xlsx": b"PK\x03\x04",
    ".docx": b"PK\x03\x04",
}
OOXML = {".xlsx", ".docx"}


class InvalidUpload(Exception):
    """Tệp tải lên không hợp lệ; `args[0]` là thông báo tiếng Việt."""


def _check_zip(f) -> bool:
    try:
        f.seek(0)
        with zipfile.ZipFile(f) as z:
            return "[Content_Types].xml" in z.namelist()
    except zipfile.BadZipFile:
        return False
    finally:
        f.seek(0)


def validate_upload(f) -> tuple[str, str]:
    """Trả về (phần mở rộng, mime) hoặc ném InvalidUpload."""
    name = Path(f.name or "").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED:
        raise InvalidUpload("Định dạng tệp không được phép (chỉ nhận PDF, PNG, JPG, XLSX, DOCX)")
    max_mb = get_setting("max_upload_mb")
    if f.size > max_mb * 1024 * 1024:
        raise InvalidUpload(f"Tệp vượt quá {max_mb} MB")
    f.seek(0)
    head = f.read(len(SIGNATURES[ext]))
    f.seek(0)
    if head != SIGNATURES[ext]:
        raise InvalidUpload("Nội dung tệp không khớp với định dạng khai báo")
    if ext in OOXML and not _check_zip(f):
        raise InvalidUpload("Nội dung tệp không khớp với định dạng khai báo")
    return ext, ALLOWED[ext]


def absolute_path(stored_path: str) -> Path:
    return Path(settings.MEDIA_ROOT) / stored_path


def _write(f, ext: str) -> tuple[str, int, str]:
    now = timezone.now()
    rel = f"{now:%Y/%m}/{uuid.uuid4().hex}{ext}"
    dest = absolute_path(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    sha, size = hashlib.sha256(), 0
    f.seek(0)
    with open(dest, "wb") as out:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            sha.update(chunk)
            size += len(chunk)
            out.write(chunk)
    return rel, size, sha.hexdigest()


def _create(f, *, attach_to, doc_type, user) -> Document:
    if doc_type not in dict(DOC_TYPES):
        raise InvalidUpload("Loại chứng từ không hợp lệ")
    ext, mime = validate_upload(f)
    rel, size, digest = _write(f, ext)
    try:
        doc = Document.objects.create(
            content_type=ContentType.objects.get_for_model(attach_to),
            object_id=str(attach_to.pk),
            doc_type=doc_type,
            original_name=Path(f.name).name[:255],
            stored_path=rel,
            size=size,
            mime=mime,
            sha256=digest,
            uploaded_by=user,
        )
        doc.text_content = extract.extract_text(doc)
        doc.save(update_fields=["text_content"])
        search.refresh_search_vector(doc)
    except Exception:
        absolute_path(rel).unlink(missing_ok=True)
        raise
    return doc


def store_upload(f, *, attach_to, doc_type: str, user) -> Document:
    with transaction.atomic():
        doc = _create(f, attach_to=attach_to, doc_type=doc_type, user=user)
        record(
            "document.uploaded",
            doc,
            actor=user,
            changes={
                "name": doc.original_name,
                "doc_type": doc_type,
                "sha256": doc.sha256,
                "size": doc.size,
                "attached_to": f"{doc.content_type.model}:{doc.object_id}",
            },
        )
    return doc


def supersede(old: Document, new_file, user) -> Document:
    with transaction.atomic():
        old = Document.objects.select_for_update().get(pk=old.pk)
        if old.superseded_by_id is not None:
            raise InvalidUpload("Chứng từ đã được thay thế bằng phiên bản khác")
        new = _create(new_file, attach_to=old.attached_to, doc_type=old.doc_type, user=user)
        old.superseded_by = new
        old.save(update_fields=["superseded_by"])
        record(
            "document.superseded",
            old,
            actor=user,
            changes={"superseded_by": str(new.pk), "new_sha256": new.sha256},
        )
    return new
