import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts import roles
from apps.audit.models import AuditEvent
from apps.core.services import set_setting
from apps.documents.extract import extract_text
from apps.documents.models import CONTRACT, OTHER, Document
from apps.documents.permissions import can_view_object
from apps.documents.search import search_documents
from apps.documents.storage import InvalidUpload, store_upload, supersede
from apps.accounts.auth import AUTH_METHOD_KEY, AUTH_OIDC
from tests.documents.helpers import ooxml_bytes, pdf_with_text


def upload(name, data, content_type="application/octet-stream"):
    return SimpleUploadedFile(name, data, content_type=content_type)


def login(client, user):
    client.force_login(user)
    s = client.session
    s[AUTH_METHOD_KEY] = AUTH_OIDC
    s.save()


def test_rejects_disallowed_extension_and_spoofed_pdf(db, owner, req):
    with pytest.raises(InvalidUpload):
        store_upload(upload("x.exe", b"MZ.."), attach_to=req, doc_type=OTHER, user=owner)
    with pytest.raises(InvalidUpload):
        store_upload(upload("x.pdf", b"PK\x03\x04"), attach_to=req, doc_type=OTHER, user=owner)
    assert Document.objects.count() == 0


def test_extension_case_insensitive_and_png_jpeg_signatures(db, owner, req):
    d = store_upload(upload("A.PNG", b"\x89PNG\r\n\x1a\n" + b"0" * 10), attach_to=req, doc_type=OTHER, user=owner)
    assert d.mime == "image/png"
    d = store_upload(upload("a.jpg", b"\xff\xd8\xff\xe0" + b"0" * 10, "text/html"), attach_to=req, doc_type=OTHER, user=owner)
    assert d.mime == "image/jpeg"
    with pytest.raises(InvalidUpload):
        store_upload(upload("a.png", b"\xff\xd8\xff\xe0"), attach_to=req, doc_type=OTHER, user=owner)


def test_ooxml_requires_content_types(db, owner, req):
    d = store_upload(upload("a.xlsx", ooxml_bytes()), attach_to=req, doc_type=OTHER, user=owner)
    assert d.mime.endswith("spreadsheetml.sheet")
    with pytest.raises(InvalidUpload):
        store_upload(upload("a.docx", ooxml_bytes(False)), attach_to=req, doc_type=OTHER, user=owner)
    with pytest.raises(InvalidUpload):
        store_upload(upload("a.docx", b"PK\x03\x04junk"), attach_to=req, doc_type=OTHER, user=owner)


def test_rejects_oversize(db, owner, req):
    big = upload("a.pdf", b"%PDF-" + b"0" * (25 * 1024 * 1024))
    with pytest.raises(InvalidUpload) as e:
        store_upload(big, attach_to=req, doc_type=OTHER, user=owner)
    assert str(e.value) == "Tệp vượt quá 25 MB"


def test_oversize_uses_setting(db, owner, req):
    set_setting("max_upload_mb", 1, actor=owner)
    with pytest.raises(InvalidUpload) as e:
        store_upload(upload("a.pdf", b"%PDF-" + b"0" * 1024 * 1024), attach_to=req, doc_type=OTHER, user=owner)
    assert str(e.value) == "Tệp vượt quá 1 MB"


def test_stored_outside_web_root_with_random_name(db, owner, req, settings):
    d = store_upload(upload("Hợp đồng thuê kho.pdf", pdf_with_text("Hop dong")), attach_to=req, doc_type=CONTRACT, user=owner)
    assert "Hợp đồng" not in d.stored_path and not d.stored_path.startswith(str(settings.STATIC_ROOT))
    assert d.stored_path.endswith(".pdf") and d.stored_path.count("/") == 2
    assert (settings.MEDIA_ROOT / d.stored_path).is_file()
    assert len(d.sha256) == 64
    assert d.original_name == "Hợp đồng thuê kho.pdf"
    assert AuditEvent.objects.filter(action="document.uploaded", object_id=str(d.pk)).exists()


def test_extract_text_pdf_only(db, owner, req):
    d = store_upload(upload("a.pdf", pdf_with_text("Hello kho Chuong Duong")), attach_to=req, doc_type=OTHER, user=owner)
    assert "Chuong Duong" in d.text_content
    assert extract_text(d) == d.text_content
    png = store_upload(upload("a.png", b"\x89PNG\r\n\x1a\n"), attach_to=req, doc_type=OTHER, user=owner)
    assert extract_text(png) == ""


def test_fulltext_search_ignores_diacritics_and_permissions(db, owner, outsider, req):
    store_upload(upload("Hợp đồng thuê kho Chương Dương.pdf", pdf_with_text("noi dung bao gia")), attach_to=req, doc_type=CONTRACT, user=owner)
    assert search_documents(owner, "chuong duong").count() == 1
    assert search_documents(owner, "Chương Dương").count() == 1
    assert search_documents(owner, "HOP DONG").count() == 1
    assert search_documents(owner, "bao gia").count() == 1  # chữ trong PDF
    assert search_documents(owner, "khong co").count() == 0
    assert search_documents(owner, "").count() == 0
    assert search_documents(outsider, "chuong duong").count() == 0


def test_search_d_stroke_both_ways(db, owner, req):
    store_upload(upload("Đồng.pdf", pdf_with_text("x")), attach_to=req, doc_type=OTHER, user=owner)
    store_upload(upload("dong cua.pdf", pdf_with_text("x")), attach_to=req, doc_type=OTHER, user=owner)
    assert search_documents(owner, "dong").count() == 2
    assert search_documents(owner, "Đồng").count() == 2


def test_search_visible_to_auditor_and_fad(db, outsider, req, pdf_doc):
    assert search_documents(outsider, "chuong").count() == 0
    roles.assign(outsider, roles.AUDITOR)
    assert search_documents(outsider, "chuong").count() == 1


def test_can_view_object_rules(db, owner, outsider, req):
    assert can_view_object(owner, req)
    assert not can_view_object(outsider, req)
    assert not can_view_object(outsider, object())  # không có visible_to -> từ chối
    roles.assign(outsider, roles.FAD_PRECHECK)
    assert can_view_object(outsider, req)


def test_documents_cannot_be_deleted_or_edited(db, pdf_doc):
    with pytest.raises(PermissionError):
        pdf_doc.delete()
    with pytest.raises(PermissionError):
        Document.objects.all().delete()
    pdf_doc.original_name = "khac.pdf"
    with pytest.raises(PermissionError):
        pdf_doc.save()
    assert Document.objects.count() == 1


def test_supersede(db, owner, req, pdf_doc):
    new = supersede(pdf_doc, upload("v2.pdf", pdf_with_text("ban hai")), owner)
    pdf_doc.refresh_from_db()
    assert pdf_doc.superseded_by_id == new.pk
    assert new.attached_to == req and new.doc_type == CONTRACT
    assert AuditEvent.objects.filter(action="document.superseded", object_id=str(pdf_doc.pk)).exists()
    with pytest.raises(InvalidUpload):
        supersede(pdf_doc, upload("v3.pdf", pdf_with_text("x")), owner)


def test_download_requires_permission(client, outsider, pdf_doc):
    login(client, outsider)
    assert client.get(f"/chung-tu/{pdf_doc.pk}/tai-ve/").status_code == 403
    assert client.get(f"/chung-tu/{pdf_doc.pk}/xem/").status_code == 403
    assert not AuditEvent.objects.filter(action="document.downloaded").exists()


def test_download_requires_login(client, pdf_doc):
    assert client.get(f"/chung-tu/{pdf_doc.pk}/tai-ve/").status_code == 302


def test_download_and_inline(client, owner, pdf_doc):
    login(client, owner)
    r = client.get(f"/chung-tu/{pdf_doc.pk}/tai-ve/")
    assert r.status_code == 200
    assert r["Content-Disposition"].startswith("attachment")
    assert r["X-Content-Type-Options"] == "nosniff"
    assert r["Content-Security-Policy"] == "sandbox"
    assert r["Cache-Control"] == "private, no-store"
    assert b"".join(r.streaming_content).startswith(b"%PDF-")
    r = client.get(f"/chung-tu/{pdf_doc.pk}/xem/")
    b"".join(r.streaming_content)
    assert r["Content-Disposition"].startswith("inline")
    assert r["Content-Type"] == "application/pdf"
    assert AuditEvent.objects.filter(action="document.downloaded", object_id=str(pdf_doc.pk)).count() == 2


def test_inline_forces_attachment_for_office_files(client, owner, req):
    d = store_upload(upload("a.xlsx", ooxml_bytes()), attach_to=req, doc_type=OTHER, user=owner)
    login(client, owner)
    r = client.get(f"/chung-tu/{d.pk}/xem/")
    b"".join(r.streaming_content)
    assert r["Content-Disposition"].startswith("attachment")


def test_path_outside_media_root_is_404(client, owner, pdf_doc, settings):
    (settings.MEDIA_ROOT.parent / "x").write_bytes(b"%PDF-secret")
    Document.objects.filter(pk=pdf_doc.pk).update(stored_path="../x")
    login(client, owner)
    assert client.get(f"/chung-tu/{pdf_doc.pk}/tai-ve/").status_code == 404
