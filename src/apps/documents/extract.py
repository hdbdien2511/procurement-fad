import logging

from pypdf import PdfReader

log = logging.getLogger(__name__)


def extract_text(doc) -> str:
    """Trích chữ từ PDF (OCR thuộc đợt 2); loại khác hoặc PDF lỗi/ảnh quét trả về chuỗi rỗng."""
    from .storage import absolute_path

    if doc.mime != "application/pdf":
        return ""
    try:
        reader = PdfReader(str(absolute_path(doc.stored_path)))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # PDF hỏng/mã hoá: vẫn lưu tệp, chỉ không có chữ
        log.warning("Không trích được chữ từ chứng từ %s", doc.pk, exc_info=True)
        return ""
    return text.replace("\x00", "")
