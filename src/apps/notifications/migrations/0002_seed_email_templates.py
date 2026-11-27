"""Gieo 6 mẫu email mặc định (văn bản thuần, cú pháp Django template).

Biến cho từng mẫu (ngữ cảnh truyền vào `enqueue_email`/`notify`; `notify` tự thêm
`nguoi_nhan` và `duong_dan` nếu người gọi không đặt):

- OFFICIAL   (việc cần duyệt): ho_so, nguoi_nhan, duong_dan, han_xu_ly
- CONSULT    (xin ý kiến):     ho_so, nguoi_nhan, duong_dan, han_xu_ly, nguoi_gui
- REMINDER   (sắp đến hạn):    ho_so, nguoi_nhan, duong_dan, han_xu_ly
- OVERDUE    (quá hạn):        ho_so, nguoi_nhan, duong_dan, han_xu_ly
- ESCALATION (chuyển cấp):     ho_so, nguoi_nhan, duong_dan, han_xu_ly, cap_moi
- RESULT     (kết quả):        ho_so, nguoi_nhan, duong_dan, ket_qua

Giá trị biến là chuỗi/số đã định dạng sẵn (payload lưu JSON). Nội dung được render với
autoescape bật; tiêu đề tắt autoescape nhưng bị loại ký tự xuống dòng.
"""

from django.db import migrations

FOOTER = "\n\nTrân trọng,\nHệ thống mua sắm"

TEMPLATES = {
    "OFFICIAL": (
        "[Mua sắm] Hồ sơ {{ ho_so }} cần duyệt",
        "Kính gửi {{ nguoi_nhan }},\n\nHồ sơ {{ ho_so }} đang chờ anh/chị duyệt."
        "{% if han_xu_ly %} Hạn xử lý: {{ han_xu_ly }}.{% endif %}\nXem và xử lý tại: {{ duong_dan }}" + FOOTER,
    ),
    "CONSULT": (
        "[Mua sắm] Xin ý kiến về hồ sơ {{ ho_so }}",
        "Kính gửi {{ nguoi_nhan }},\n\n{% if nguoi_gui %}{{ nguoi_gui }} xin ý kiến anh/chị về hồ sơ {{ ho_so }}."
        "{% else %}Anh/chị được xin ý kiến về hồ sơ {{ ho_so }}.{% endif %}"
        "{% if han_xu_ly %} Hạn góp ý: {{ han_xu_ly }}.{% endif %}\nXem tại: {{ duong_dan }}" + FOOTER,
    ),
    "REMINDER": (
        "[Mua sắm] Hồ sơ {{ ho_so }} sắp đến hạn xử lý",
        "Kính gửi {{ nguoi_nhan }},\n\nHồ sơ {{ ho_so }} sắp đến hạn xử lý"
        "{% if han_xu_ly %} ({{ han_xu_ly }}){% endif %}.\nXử lý tại: {{ duong_dan }}" + FOOTER,
    ),
    "OVERDUE": (
        "[Mua sắm] Hồ sơ {{ ho_so }} đã quá hạn xử lý",
        "Kính gửi {{ nguoi_nhan }},\n\nHồ sơ {{ ho_so }} đã quá hạn xử lý"
        "{% if han_xu_ly %} (hạn: {{ han_xu_ly }}){% endif %}.\nVui lòng xử lý ngay tại: {{ duong_dan }}" + FOOTER,
    ),
    "ESCALATION": (
        "[Mua sắm] Hồ sơ {{ ho_so }} được chuyển cấp xử lý",
        "Kính gửi {{ nguoi_nhan }},\n\nHồ sơ {{ ho_so }} quá hạn và đã được chuyển lên"
        "{% if cap_moi %} {{ cap_moi }}{% else %} cấp trên{% endif %}.\nXem tại: {{ duong_dan }}" + FOOTER,
    ),
    "RESULT": (
        "[Mua sắm] Kết quả xử lý hồ sơ {{ ho_so }}",
        "Kính gửi {{ nguoi_nhan }},\n\nHồ sơ {{ ho_so }} đã có kết quả{% if ket_qua %}: {{ ket_qua }}{% endif %}."
        "\nXem chi tiết tại: {{ duong_dan }}" + FOOTER,
    ),
}


def seed(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for code, (subject, body) in TEMPLATES.items():
        EmailTemplate.objects.get_or_create(code=code, defaults={"subject": subject, "body": body})


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
