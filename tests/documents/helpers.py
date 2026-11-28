import io
import zipfile

from reportlab.pdfgen import canvas


def pdf_with_text(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 750, text)
    c.save()
    return buf.getvalue()


def ooxml_bytes(with_content_types: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml" if with_content_types else "other.xml", "<Types/>")
    return buf.getvalue()
