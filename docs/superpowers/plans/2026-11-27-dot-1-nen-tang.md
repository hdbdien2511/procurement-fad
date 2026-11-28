# Đợt 1 – Nền tảng Procurement HSC: Kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng nền tảng chạy được: một tờ trình (nhiều đơn vị ngân sách, ngoại tệ) đi từ lập → xác nhận ngân sách → tham vấn → FAD tiền kiểm → duyệt đủ lớp theo cấu hình, có duyệt thay, email, audit trail không sửa được, kho chứng từ, giữ chỗ ngân sách theo chi phí phân bổ; đóng gói Docker cho Ubuntu 26.04.

**Architecture:** Một dự án Django (render phía máy chủ + HTMX) chia theo app nghiệp vụ trong `src/apps/`. PostgreSQL giữ toàn bộ trạng thái: audit trail và sổ ngân sách là bảng chỉ-ghi-thêm có trigger chặn sửa/xoá; việc nền (email, nhắc việc) đi qua bảng outbox và một tiến trình worker. Mọi tích hợp ngoài (Entra ID, HRIS, PAS, IMS, SUN) nằm sau interface trong `apps/integrations` với bản giả lập.

**Tech Stack:** Python 3.12, Django 5.2 LTS, PostgreSQL 16, psycopg 3, django-htmx, django-otp (TOTP), django-axes, django-csp, mozilla-django-oidc, openpyxl, pypdf, cryptography (Fernet), gunicorn, Nginx, Docker Compose; kiểm thử: pytest, pytest-django, factory-boy, freezegun; CI: pip-audit, bandit, gitleaks.

**Spec:** `docs/superpowers/specs/2026-11-27-procurement-platform-design.md` (đọc kèm; mã R1…R89 là tiêu chí RFP).

## Global Constraints

- Python 3.12; Django 5.2 LTS; PostgreSQL 16. Phụ thuộc khai báo trong `pyproject.toml`, khoá phiên bản bằng `uv pip compile` ra `requirements.lock`; không thêm hạ tầng mới (không Redis, không Celery, không Elasticsearch).
- Tiền: `Decimal`, VND lưu `DecimalField(max_digits=18, decimal_places=0)`; nguyên tệ `max_digits=18, decimal_places=2`; tỷ giá `max_digits=12, decimal_places=4`. Làm tròn `ROUND_HALF_UP` về đồng. Không dùng `float` cho tiền ở bất kỳ đâu.
- Giao diện, nhãn, thông báo lỗi, email: **tiếng Việt**. Tên biến/hàm/bảng: tiếng Anh.
- Thư viện CSS/JS đóng gói trong `src/static/vendor/`; không gọi CDN.
- Năm tài chính = năm dương lịch. Kỳ ngân sách = ngày đầu tháng (`date(y, m, 1)`).
- Kiểm soát ngân sách theo **chi phí phân bổ theo tháng** (spec 7.3).
- Không có chức năng xoá đối với: `AuditEvent`, `BudgetEntry`, `Document` (lưu vĩnh viễn).
- Phân tách nhiệm vụ cứng trong code: người nộp/người tạo không hành động trên bước duyệt của hồ sơ mình; quản trị kỹ thuật (`SYS_ADMIN`) không duyệt nghiệp vụ.
- Phiên đăng nhập hết hạn sau 1800 giây không thao tác; khoá tạm sau 5 lần sai trong 15 phút; mật khẩu tối thiểu 12 ký tự.
- Repo không chứa dữ liệu thật; `sample-data/` chỉ chứa dữ liệu giả sinh bằng script.
- Kiểm thử chạy trên PostgreSQL thật (trigger, full-text): biến `DATABASE_URL`, mặc định `postgres://procurement:procurement@localhost:5432/procurement_test`.
- Mọi thay đổi trạng thái nghiệp vụ gọi `audit.record(...)` trong cùng transaction.

## Review Focus

1. **Hai người duyệt cùng lúc / bấm hai lần** trên cùng một bước → chỉ một hành động có hiệu lực, lần sau báo "Bước này đã được xử lý". Test ở Task 9.
2. **Hai tờ trình được duyệt cùng lúc trên cùng dòng ngân sách** → giữ chỗ không vượt số dư (khoá dòng ngân sách khi ghi). Test ở Task 6.
3. **Làm tròn**: chia 100.000.000 đ cho 3 tháng, quy đổi 1.234,56 USD → tổng các kỳ đúng bằng tổng gốc, chênh lệch dồn vào kỳ cuối. Test ở Task 4 và Task 6.
4. **Excel nhập liệu bẩn** (mã có dấu cách thừa, " VND ", ô trống, mã trùng, ngày dạng chuỗi) → chuẩn hoá được thì chuẩn hoá, không được thì vào báo cáo làm sạch, không nhập nửa vời. Test ở Task 7.
5. **Sửa chính sách duyệt khi hồ sơ đang chạy** → hồ sơ đang chạy giữ nguyên các bước đã chụp lúc nộp. Test ở Task 9.

---

## Cấu trúc file

```
pyproject.toml, requirements.lock, pytest.ini, .gitignore, .env.example, README.md
src/manage.py
src/config/{__init__,urls,wsgi}.py
src/config/settings/{__init__,base,dev,test,prod}.py
src/apps/core/        models.py (Setting, ExchangeRate), crypto.py, money.py, fx.py, numbering.py, views.py (healthz, settings UI)
src/apps/audit/       models.py, service.py (record, verify_chain), middleware.py, migrations/0002_triggers.py, management/commands/audit_verify.py, views.py
src/apps/accounts/    models.py (OrgUnit, User, Role, RoleAssignment), roles.py, services.py, auth.py (OIDC), management/commands/sync_hris.py
src/apps/documents/   models.py, storage.py, extract.py, search.py, permissions.py, views.py
src/apps/budget/      models.py, ledger.py, allocation.py, importer.py, views.py
src/apps/vendors/     models.py, validators.py, importer.py, views.py
src/apps/workflow/    models.py, engine.py, resolver.py, delegation.py, sla.py, splitting.py, views.py
src/apps/requisitions/ models.py, services.py, forms.py, views.py
src/apps/budget_changes/ models.py, services.py, views.py
src/apps/notifications/ models.py, outbox.py, mailer.py, management/commands/run_worker.py, views.py
src/apps/integrations/ interfaces.py, fakes.py, hris.py
src/apps/ui/          tables.py, export.py, templatetags/vn.py
src/templates/, src/static/
tests/<app>/test_*.py, tests/conftest.py, tests/factories.py, tests/e2e/test_dot1_scenario.py
scripts/make_sample_data.py
sample-data/            (sinh ra bởi script)
deploy/Dockerfile, deploy/docker-compose.yml, deploy/nginx/nginx.conf, deploy/postgres/init.sql
deploy/scripts/{install,upgrade,backup,restore}.sh
docs/05-ban-giao-it/huong-dan-cai-dat.md
.github/workflows/ci.yml
```

---

### Task 1: Khung dự án, cấu hình bảo mật, CI

**Files:**
- Create: `pyproject.toml`, `requirements.lock`, `pytest.ini`, `.gitignore`, `.env.example`, `README.md`, `src/manage.py`, `src/config/**`, `src/apps/core/{__init__,apps,views}.py`, `.github/workflows/ci.yml`
- Test: `tests/core/test_health_and_settings.py`, `tests/conftest.py`

**Interfaces:**
- Produces: `config.settings.base` đọc env qua `env(name, default=None)`; URL `GET /healthz` trả `{"status": "ok", "db": "ok"}`; `INSTALLED_APPS` chứa các app `apps.<name>`; `AUTH_USER_MODEL = "accounts.User"` (khai báo ngay, model ở Task 3 — Task 1 tạo app `accounts` rỗng với `User(AbstractUser)` tối thiểu để migrate được).

- [ ] **Step 1: Viết test**

```python
def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok", "db": "ok"}

def test_prod_security_flags(settings_module=None):
    from config.settings import prod
    assert prod.DEBUG is False
    assert prod.SESSION_COOKIE_SECURE and prod.CSRF_COOKIE_SECURE
    assert prod.SESSION_COOKIE_AGE == 1800 and prod.SESSION_SAVE_EVERY_REQUEST
    assert prod.SECURE_HSTS_SECONDS >= 31536000
    assert prod.X_FRAME_OPTIONS == "DENY"
    assert prod.LANGUAGE_CODE == "vi" and prod.TIME_ZONE == "Asia/Ho_Chi_Minh"
```
`.gitignore` phải chặn: `.env`, `media/`, `*.xlsx` ngoài `sample-data/`, `*.docx`/`*.pdf` ngoài `docs/`, `__pycache__/`.

- [ ] **Step 2: Chạy, xác nhận FAIL**
Run: `pytest tests/core -v` → FAIL (chưa có project).

- [ ] **Step 3: Tạo khung** theo cấu trúc trên. `prod.py` bắt buộc `SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL`, `APP_ENCRYPTION_KEY` từ env (thiếu thì raise `ImproperlyConfigured`). Password validators: MinimumLength 12 + các validator mặc định. CI: job Postgres 16 service → `pytest`, `pip-audit -r requirements.lock`, `bandit -r src -ll`, `gitleaks detect`.

- [ ] **Step 4: Chạy lại** `pytest tests/core -v` → PASS; `python src/manage.py check --deploy --settings=config.settings.prod` (với env giả) không có cảnh báo mức ERROR.

- [ ] **Step 5: Commit** `feat: project skeleton with security settings and CI`

---

### Task 2: Audit trail chỉ-ghi-thêm có chuỗi băm

**Files:**
- Create: `src/apps/audit/{models,service,middleware}.py`, `migrations/0001_initial.py`, `migrations/0002_triggers.py`, `management/commands/audit_verify.py`
- Test: `tests/audit/test_audit.py`

**Interfaces:**
- Produces:
  - `AuditEvent(id BigAutoField, occurred_at, actor FK User null, actor_label str, action str, object_type str, object_id str, ip str null, changes JSONField, prev_hash char(64), hash char(64))`
  - `record(action: str, obj: Model | None = None, *, actor: User | None = None, changes: dict | None = None) -> AuditEvent` — actor/ip mặc định lấy từ contextvar do `AuditContextMiddleware` đặt.
  - `diff(before: dict, after: dict) -> dict[str, list]` → `{"field": [old, new]}`
  - `verify_chain() -> list[int]` (id các bản ghi sai)
  - `install_append_only_trigger(table: str) -> str` (SQL dùng lại cho `BudgetEntry` ở Task 6)

- [ ] **Step 1: Viết test**

```python
def test_record_chains_hashes(db, user):
    a = record("requisition.created", actor=user, changes={"x": [None, 1]})
    b = record("requisition.submitted", actor=user)
    assert b.prev_hash == a.hash and len(b.hash) == 64

def test_update_and_delete_blocked_by_db(db, user):
    e = record("x", actor=user)
    with pytest.raises(django.db.InternalError):
        AuditEvent.objects.filter(pk=e.pk).update(action="y")
    with pytest.raises(django.db.InternalError):
        AuditEvent.objects.filter(pk=e.pk).delete()

def test_verify_chain_detects_tampering(db, user):
    e = record("x", actor=user); record("y", actor=user)
    with connection.cursor() as c:
        c.execute("ALTER TABLE audit_auditevent DISABLE TRIGGER USER")
        c.execute("UPDATE audit_auditevent SET action='z' WHERE id=%s", [e.pk])
        c.execute("ALTER TABLE audit_auditevent ENABLE TRIGGER USER")
    assert verify_chain() == [e.pk]
```

- [ ] **Step 2: Chạy** `pytest tests/audit -v` → FAIL.
- [ ] **Step 3: Cài đặt.** Hash = SHA-256 của JSON chuẩn hoá (`sort_keys=True`, `ensure_ascii=False`, `default=str`) gồm `occurred_at, actor_id, action, object_type, object_id, changes, prev_hash`. Lấy `prev_hash` dưới `pg_advisory_xact_lock(4242)` để chuỗi không rẽ nhánh khi ghi đồng thời. Trigger `BEFORE UPDATE OR DELETE` raise exception `'append-only table'`. Model `delete()`/`save()` khi đã có pk → raise `PermissionError`. Lệnh `audit_verify` in số bản ghi lỗi, exit code 1 nếu có lỗi.
- [ ] **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(audit): append-only hash-chained audit trail`

---

### Task 3: Tổ chức, người dùng, vai trò, đăng nhập

**Files:**
- Create/Modify: `src/apps/accounts/{models,roles,services,auth}.py`, `management/commands/sync_hris.py`, `src/apps/integrations/{interfaces,fakes,hris}.py`, templates đăng nhập + MFA
- Test: `tests/accounts/test_roles.py`, `tests/accounts/test_auth.py`, `tests/accounts/test_hris_sync.py`, `tests/factories.py`

**Interfaces:**
- Consumes: `audit.record`
- Produces:
  - `OrgUnit(code unique, name, kind: "KHOI"|"PHONG"|"CHI_NHANH", parent FK self null, head FK User null, is_active)`
  - `User(AbstractUser)` + `org_unit FK OrgUnit null, title str, employee_code unique null, entra_oid unique null`
  - `roles.py`: hằng số `REQUESTER, DEPT_HEAD, GDNV, GDDH, CEO, BMS_SECRETARY, BOARD_SECRETARY, FAD_PRECHECK, FAD_BUDGET_ADMIN, BUDGET_OWNER, CONSULTANT, SYS_ADMIN, AUDITOR`
  - `Role(code unique, name)`; `RoleAssignment(user, role, org_unit null, valid_from date, valid_to date null)`
  - `has_role(user, role_code, org_unit=None, on=None) -> bool`
  - `users_with_role(role_code, org_unit=None, on=None) -> QuerySet[User]` (org_unit=None nghĩa là vai trò toàn công ty)
  - `integrations.interfaces.HrisClient` (Protocol): `fetch_org_units() -> list[dict]`, `fetch_employees() -> list[dict]`; `FakeHrisClient(path)` đọc `sample-data/hris_fake.json`
  - `sync_hris(client: HrisClient) -> SyncReport(created:int, updated:int, deactivated:int)`

- [ ] **Step 1: Viết test**

```python
def test_role_scope_and_validity(db, user, unit_adm, unit_itd):
    assign(user, DEPT_HEAD, unit_adm, valid_from=date(2026,1,1), valid_to=date(2026,6,30))
    assert has_role(user, DEPT_HEAD, unit_adm, on=date(2026,3,1))
    assert not has_role(user, DEPT_HEAD, unit_itd, on=date(2026,3,1))
    assert not has_role(user, DEPT_HEAD, unit_adm, on=date(2026,7,1))

def test_lockout_after_5_failures(client, user):
    for _ in range(5): client.post("/dang-nhap/", {"username": user.username, "password": "sai"})
    r = client.post("/dang-nhap/", {"username": user.username, "password": "dung-mat-khau-123"})
    assert "tạm khoá" in r.content.decode()

def test_local_login_requires_totp(client, user_with_totp): ...  # đúng mật khẩu → chuyển tới /xac-thuc-otp/, chưa vào được /

def test_sync_hris_deactivates_missing(db, fake_hris):
    ...  # nhân viên không còn trong HRIS → is_active=False, ghi audit "user.deactivated"
```

- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Cài đặt.** django-axes (5 lần / 15 phút, khoá theo username+IP); django-otp TOTP bắt buộc với tài khoản đăng nhập bằng mật khẩu. OIDC Entra ID qua mozilla-django-oidc, **chỉ bật khi có** env `OIDC_RP_CLIENT_ID`, `OIDC_RP_CLIENT_SECRET`, `OIDC_OP_TENANT_ID`; ánh xạ user theo claim `oid` → `entra_oid`; không tự tạo user khi chưa có trong HRIS sync. Ghi audit `auth.login`, `auth.login_failed`, `auth.logout`.
- [ ] **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(accounts): org units, scoped roles, local+TOTP login, Entra OIDC hook, HRIS sync`

---

### Task 4: Cấu hình hệ thống, mã hoá bí mật, tỷ giá, định dạng tiền

**Files:**
- Create: `src/apps/core/{models,crypto,money,fx,numbering}.py`, `src/apps/ui/templatetags/vn.py`
- Test: `tests/core/test_money_fx.py`, `tests/core/test_crypto_settings.py`

**Interfaces:**
- Produces:
  - `Setting(key unique, value JSONField)`; `get_setting(key, default)`, `set_setting(key, value, actor)` (ghi audit). Khoá dùng ở các task sau: `split_window_days` (mặc định 30), `annual_fixed_cost_vnd` (mặc định 0), `cumulative_scope` (`"COMPANY"`), `max_upload_mb` (25).
  - `crypto.encrypt(text: str) -> str`, `crypto.decrypt(token: str) -> str` (Fernet, khoá env `APP_ENCRYPTION_KEY`)
  - `ExchangeRate(currency char(3), date, rate)` unique (currency, date)
  - `fx.to_vnd(amount: Decimal, currency: str, on: date) -> tuple[Decimal, Decimal]` → (số VND đã làm tròn, tỷ giá dùng); dùng tỷ giá gần nhất `<= on`; `"VND"` → tỷ giá 1; không có → raise `MissingRate(currency, on)`
  - `money.round_vnd(x: Decimal) -> Decimal`; `money.format_vnd(x) -> str` (`"1.234.567"`); `money.amount_in_words_vi(x: Decimal) -> str`
  - `numbering.next_number(prefix: str, year: int) -> str` → `"TT-2026-00001"` (bảng `NumberSequence(prefix, year, last)` + `select_for_update`)
  - template filters `vnd`, `bang_chu`

- [ ] **Step 1: Viết test**

```python
def test_to_vnd_rounds_half_up(db):
    ExchangeRate.objects.create(currency="USD", date=date(2026,11,1), rate=Decimal("25460.5000"))
    vnd, rate = to_vnd(Decimal("1234.56"), "USD", date(2026,11,27))
    assert rate == Decimal("25460.5000") and vnd == Decimal("31432515")  # 31.432.514,88 → 31.432.515

def test_missing_rate(db):
    with pytest.raises(MissingRate): to_vnd(Decimal("1"), "HKD", date(2026,1,1))

def test_amount_in_words():
    assert amount_in_words_vi(Decimal("1250000")) == "Một triệu hai trăm năm mươi nghìn đồng"
    assert amount_in_words_vi(Decimal("2000000005")) == "Hai tỷ không trăm linh năm đồng"
    assert amount_in_words_vi(Decimal("0")) == "Không đồng"

def test_format_vnd():
    assert format_vnd(Decimal("-1234567")) == "-1.234.567"

def test_numbering_sequential(db):
    assert next_number("TT", 2026) == "TT-2026-00001"
    assert next_number("TT", 2026) == "TT-2026-00002"
    assert next_number("TT", 2027) == "TT-2027-00001"

def test_encrypt_roundtrip(settings):
    assert decrypt(encrypt("mat-khau-smtp")) == "mat-khau-smtp"
```

- [ ] **Step 2: Chạy** → FAIL. **Step 3: Cài đặt.** **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(core): settings, encryption, exchange rates, VND formatting, numbering`

---

### Task 5: Kho chứng từ, trích chữ PDF, tìm kiếm toàn văn

**Files:**
- Create: `src/apps/documents/{models,storage,extract,search,permissions,views}.py`, migration bật `unaccent`
- Test: `tests/documents/test_documents.py` (file mẫu tạo trong test: PDF có chữ bằng reportlab hoặc file nhỏ trong `tests/fixtures/`)

**Interfaces:**
- Consumes: `audit.record`, `get_setting("max_upload_mb")`
- Produces:
  - `Document(id UUID, content_type+object_id (GenericFK "attached_to"), doc_type str, original_name, stored_path, size, mime, sha256, text_content, search_vector SearchVectorField (GIN), uploaded_by, uploaded_at, superseded_by FK self null)`
  - Hằng `doc_type`: `QUOTE, PROPOSAL, MEETING_MINUTES, DELEGATION_LETTER, CONTRACT, OTHER`
  - `store_upload(f: UploadedFile, *, attach_to: Model, doc_type: str, user: User) -> Document` — raise `InvalidUpload(message_vi)`
  - `supersede(old: Document, new_file, user) -> Document`
  - `extract.extract_text(doc: Document) -> str` (PDF qua pypdf; loại khác trả `""`)
  - `search.search_documents(user, q: str) -> QuerySet[Document]` (chỉ trả tài liệu user được xem)
  - `permissions.can_view_object(user, obj) -> bool` — mỗi model nghiệp vụ hiện thực `visible_to(user) -> bool`; FAD và AUDITOR xem tất cả
  - `GET /chung-tu/<uuid>/tai-ve/` (kiểm quyền, `Content-Disposition: attachment`), `GET /chung-tu/<uuid>/xem/` (inline cho PDF/ảnh)

- [ ] **Step 1: Viết test**

```python
def test_rejects_disallowed_extension_and_spoofed_pdf(db, user, req):
    with pytest.raises(InvalidUpload): store_upload(upload("x.exe", b"MZ.."), attach_to=req, doc_type=OTHER, user=user)
    with pytest.raises(InvalidUpload): store_upload(upload("x.pdf", b"PK\x03\x04"), attach_to=req, doc_type=OTHER, user=user)

def test_rejects_oversize(db, user, req, settings): ...  # > max_upload_mb → InvalidUpload("Tệp vượt quá 25 MB")

def test_stored_outside_web_root_with_random_name(db, user, req):
    d = store_upload(pdf_with_text("Hợp đồng thuê kho"), attach_to=req, doc_type=CONTRACT, user=user)
    assert "Hợp đồng" not in d.stored_path and not d.stored_path.startswith(str(settings.STATIC_ROOT))
    assert len(d.sha256) == 64

def test_fulltext_search_ignores_diacritics_and_permissions(db, user, other_user, req):
    store_upload(pdf_with_text("Hợp đồng thuê kho Chương Dương"), attach_to=req, doc_type=CONTRACT, user=user)
    assert search_documents(user, "chuong duong").count() == 1
    assert search_documents(other_user, "chuong duong").count() == 0

def test_documents_cannot_be_deleted(db, user, req):
    d = store_upload(...); 
    with pytest.raises(PermissionError): d.delete()

def test_download_requires_permission(client, other_user, doc): ...  # 403
```

- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Cài đặt.** Danh sách cho phép: `.pdf .png .jpg .jpeg .xlsx .docx`; kiểm tra chữ ký đầu file (PDF `%PDF`, PNG, JPEG, ZIP cho xlsx/docx). Lưu tại `MEDIA_ROOT/YYYY/MM/<uuid><ext>`, `MEDIA_ROOT` ngoài thư mục static và không được Nginx phục vụ trực tiếp. `search_vector` = `to_tsvector('simple', unaccent(original_name || ' ' || text_content))`, cập nhật khi lưu. Trích chữ chạy đồng bộ khi tải lên (OCR thuộc đợt 2).
- [ ] **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(documents): permanent document store, PDF text extraction, full-text search`

---

### Task 6: Danh mục ngân sách, sổ bút toán, phân bổ, số dư

**Files:**
- Create: `src/apps/budget/{models,allocation,ledger}.py`, migration trigger chỉ-ghi-thêm cho `BudgetEntry`
- Test: `tests/budget/test_allocation.py`, `tests/budget/test_ledger.py`

**Interfaces:**
- Consumes: `install_append_only_trigger`, `audit.record`, `round_vnd`
- Produces:
  - `BudgetUnit(code unique e.g. "ADM", name, managing_org_unit FK OrgUnit, is_union_fund bool)`
  - `MainItem(code e.g. "02", name)`; `CostCode(code unique e.g. "AD_2.1.7D", name, budget_unit FK, is_capex bool)`; `CostCodeMainItem(cost_code, year, main_item)` unique (cost_code, year)
  - `Project(code unique, name, workstream, begin_year, budget_unit FK)`; `Location(code "HSC"|"HNB", name)`
  - `BudgetLine(year, budget_unit, cost_code, project, location)` unique theo 5 trường
  - `BudgetEntry(line FK, period date, kind, amount Decimal(18,0) có dấu, source_type str, source_id str, note, created_by, created_at)`; `kind` ∈ `ORIGINAL, ADJUST, TRANSFER, RESERVE, RELEASE, EXPENSE, ACCRUAL, REVERSAL, DEPRE, FORECAST`
  - Nhóm: `BUDGET_KINDS={ORIGINAL,ADJUST,TRANSFER}`, `RESERVED_KINDS={RESERVE,RELEASE}`, `EXPENSE_KINDS={EXPENSE,ACCRUAL,REVERSAL,DEPRE}`; RELEASE và REVERSAL lưu số âm
  - `allocation.allocate(amount: Decimal, start: date, months: int) -> list[tuple[date, Decimal]]` — chia đều theo tháng, làm tròn đồng, phần dư dồn kỳ cuối; `months=1` cho Once-off
  - `Balance(dataclass): budget, reserved, expensed, forecast, available` (tất cả Decimal)
  - `ledger.balance(line: BudgetLine, *, through: date | None = None) -> Balance` (through=None: cả năm của line)
  - `ledger.reserve(allocations: list[tuple[BudgetLine, Decimal]], *, start: date, months: int, source: Model, user) -> list[str]` — trả danh sách cảnh báo (kỳ thuộc năm sau chưa có ngân sách); raise `InsufficientBudget(shortfalls: list[tuple[BudgetLine, Decimal]])` nếu kỳ trong năm của line không đủ
  - `ledger.release(source: Model, user) -> None` (ghi RELEASE đối ứng toàn bộ RESERVE còn lại của source)
  - `ledger.post(line, period, kind, amount, *, source, user, note="") -> BudgetEntry`

- [ ] **Step 1: Viết test**

```python
def test_allocate_remainder_to_last():
    assert allocate(Decimal("100000000"), date(2026,1,1), 3) == [
        (date(2026,1,1), Decimal("33333333")), (date(2026,2,1), Decimal("33333333")),
        (date(2026,3,1), Decimal("33333334"))]

def test_allocate_crosses_year():
    rows = allocate(Decimal("1200"), date(2026,11,1), 4)
    assert [p for p, _ in rows] == [date(2026,11,1), date(2026,12,1), date(2027,1,1), date(2027,2,1)]

def test_balance_and_reserve(db, line_2026, user, req):
    post(line_2026, date(2026,1,1), ORIGINAL, Decimal("120000000"), source=None, user=user)
    reserve([(line_2026, Decimal("30000000"))], start=date(2026,1,1), months=1, source=req, user=user)
    b = balance(line_2026)
    assert (b.budget, b.reserved, b.available) == (Decimal("120000000"), Decimal("30000000"), Decimal("90000000"))
    release(req, user); assert balance(line_2026).reserved == 0

def test_forecast_not_deducted(db, line_2026, user): ...  # FORECAST 50tr → available không đổi

def test_insufficient_budget_lists_shortfall(db, line_2026, user, req):
    post(line_2026, date(2026,1,1), ORIGINAL, Decimal("10000000"), source=None, user=user)
    with pytest.raises(InsufficientBudget) as e:
        reserve([(line_2026, Decimal("15000000"))], start=date(2026,1,1), months=1, source=req, user=user)
    assert e.value.shortfalls == [(line_2026, Decimal("5000000"))]

def test_next_year_periods_warn_not_block(db, line_2026, user, req): ...
    # 24 tháng từ 2026-01: phần 2027 ghi vào BudgetLine 2027 cùng chiều (tự tạo nếu chưa có), trả 1 cảnh báo

def test_concurrent_reserve_cannot_overspend(transactional_db, line_2026, user):
    # ngân sách 100tr; 2 luồng cùng reserve 60tr → đúng 1 thành công, 1 InsufficientBudget

def test_budget_entry_append_only(db, entry):
    with pytest.raises(django.db.InternalError): BudgetEntry.objects.filter(pk=entry.pk).update(amount=0)
```

- [ ] **Step 2: Chạy** → FAIL.
- [ ] **Step 3: Cài đặt.** `reserve` khoá các `BudgetLine` liên quan bằng `select_for_update()` theo thứ tự pk tăng dần (tránh deadlock) trước khi tính số dư. Kiểm tra đủ ngân sách tính trên **luỹ kế cả năm** của line (không theo từng tháng). Mọi `post` ghi audit `budget.entry_posted`.
- [ ] **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(budget): budget dimensions, append-only ledger, monthly allocation, balances`

---

### Task 7: Nhập Excel Budget Control, báo cáo làm sạch, dữ liệu giả

**Files:**
- Create: `src/apps/budget/importer.py`, `scripts/make_sample_data.py`, `sample-data/README.md`
- Test: `tests/budget/test_importer.py`

**Interfaces:**
- Consumes: models Task 6, `vendors.importer.import_vendors_from_rows` (Task 8 — nếu làm Task 7 trước, bỏ qua sheet L9 và để Task 8 nối vào)
- Produces:
  - `ImportIssue(sheet: str, row: int, column: str, message: str)`
  - `ImportReport(issues: list[ImportIssue], created: dict[str,int], ok: bool)`
  - `import_budget_workbook(path, *, budget_unit_code: str, year: int, user, dry_run: bool = True) -> ImportReport` — đọc các sheet và tiêu đề **đúng như file thật**: `L8_Code` (`L8_Code, L8_name, Capex/Opex, Main_2025, Main_2026, Main_2027`), `L10_Code` (`Project_Code, Project Name, Work streams, Begin_Year, Dept`), `Budget_Expense` (`L8_Code, L8_name, Date, Original, Adjust, L10_Code, Location, Note`), `Budget_Capex` (thêm cột `Group`). `Original` → bút toán `ORIGINAL`, `Adjust` → `ADJUST`, kỳ = ngày đầu tháng của `Date`; `L10_Code` trống → project `BAU_<unit>`.
  - `scripts/make_sample_data.py --out sample-data/` sinh `Budget Control - DEMO.xlsx` (cùng sheet/tiêu đề, số giả, 2 địa điểm), `hris_fake.json` (đơn vị và người giả, đủ các vai trò của kịch bản Task 16)

- [ ] **Step 1: Viết test**

```python
def test_dry_run_writes_nothing(db, demo_xlsx, user):
    r = import_budget_workbook(demo_xlsx, budget_unit_code="DEMO", year=2026, user=user, dry_run=True)
    assert r.ok and BudgetEntry.objects.count() == 0

def test_import_totals_match_sheet(db, demo_xlsx, user):
    import_budget_workbook(demo_xlsx, budget_unit_code="DEMO", year=2026, user=user, dry_run=False)
    assert sum_budget(year=2026) == expected_total_from_sheet(demo_xlsx)

def test_dirty_rows_reported_and_import_aborted(db, dirty_xlsx, user):
    # dirty: " AD_26.1 " (chuẩn hoá được), mã L8 không tồn tại, Date trống, Original="abc", trùng L8_Code trong sheet L8_Code
    r = import_budget_workbook(dirty_xlsx, budget_unit_code="DEMO", year=2026, user=user, dry_run=False)
    assert not r.ok and BudgetEntry.objects.count() == 0
    assert {(i.sheet, i.column) for i in r.issues} >= {("Budget_Expense","L8_Code"), ("Budget_Expense","Date"),
                                                        ("Budget_Expense","Original"), ("L8_Code","L8_Code")}

def test_float_noise_rounded(db, xlsx_with_6250000_000000001, user): ...  # → 6250000
```

- [ ] **Step 2: Chạy** → FAIL. **Step 3: Cài đặt** (openpyxl `read_only=True, data_only=True`; có bất kỳ issue nào thì không ghi gì — một transaction). **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(budget): Budget Control workbook importer with cleaning report; fake sample data`

---

### Task 8: Danh mục nhà cung cấp

**Files:**
- Create: `src/apps/vendors/{models,validators,importer}.py`
- Test: `tests/vendors/test_vendors.py`

**Interfaces:**
- Produces:
  - `Vendor(code unique, tax_code unique, name, kind "ORG"|"INDIVIDUAL", status "ACTIVE"|"PENDING"|"SUSPENDED"|"BLACKLISTED", bank_account, bank_name, categories M2M VendorCategory)`; `VendorCategory(code, name)`
  - `validators.validate_tax_code(s)` — `^\d{10}(-\d{3})?$` (cá nhân cho phép 12 số CCCD: `^\d{12}$`); `validate_bank_account(s)` — `^\d{6,20}$`
  - `import_vendors_from_rows(rows: list[dict], user, dry_run=True) -> ImportReport` (cột sheet `L9_Code`: `Loại hình, Mã số thuế, Tên nhà cung cấp`; `Tổ chức`→ORG, khác→INDIVIDUAL; MST trùng → issue)
  - `Vendor.is_selectable() -> bool` (chỉ ACTIVE)

- [ ] **Step 1: Test:** `validate_tax_code("0300481551-006")` hợp lệ; `"03004815"` raise `ValidationError("Mã số thuế không hợp lệ")`; nhập 2 dòng cùng MST → 1 issue; vendor `BLACKLISTED` → `is_selectable() is False`; đổi `status` ghi audit `vendor.status_changed` với diff.
- [ ] **Step 2–4:** FAIL → cài đặt → PASS. **Step 5: Commit** `feat(vendors): vendor master with tax-code validation and import`

---

### Task 9: Bộ máy luồng duyệt

**Files:**
- Create: `src/apps/workflow/{models,resolver,engine}.py`
- Test: `tests/workflow/test_rule_selection.py`, `tests/workflow/test_engine.py`

**Interfaces:**
- Consumes: `has_role`, `users_with_role`, `audit.record`, `get_setting`
- Produces:
  - `ApprovalPolicy(code, subject_kind "requisition"|"budget_change", version int, effective_from date, is_active)`; unique (code, version); policy đã có instance dùng thì không sửa được (`save` raise) — muốn đổi phải tạo version mới
  - `PolicyRule(policy, priority int, max_amount Decimal null (≤, bao gồm), cumulative_cap Decimal null (< nghiêm ngặt), cumulative_cap_pct Decimal null (< nghiêm ngặt, % của `annual_fixed_cost_vnd`), label)`
  - `RuleStep(rule, seq int, kind, role_code, scope, fixed_org_unit null, mandatory bool, sla_hours int, escalate_role_code str null, requires_doc_type str null)`; `kind` ∈ `PROPOSE, BUDGET_OWNER, CONSULT, FAD_PRECHECK, APPROVE, MEETING`; `scope` ∈ `REQUESTER_UNIT, BUDGET_UNIT, FIXED_UNIT, SELECTED_UNITS, COMPANY`
  - `WorkflowInstance(subject GenericFK, policy, rule, snapshot JSONField, submitted_by, status "RUNNING"|"APPROVED"|"REJECTED"|"RETURNED"|"CANCELLED", started_at, finished_at)`
  - `WorkflowTask(instance, seq, branch_key str, kind, role_code, org_unit null, mandatory, status "WAITING"|"PENDING"|"APPROVED"|"REJECTED"|"RETURNED"|"COMMENTED"|"SKIPPED", due_at, acted_by null, on_behalf_of null, comment, acted_at)`
  - Subject protocol (model nghiệp vụ hiện thực): `workflow_context() -> dict` với khoá `amount_vnd: Decimal, budget_unit_ids: list[int], consult_unit_ids: list[int], requester_unit_id: int, created_by_id: int`; `cumulative_amount_vnd(scope: str) -> Decimal` (chỉ budget_change); callback `on_workflow_finished(status: str) -> None`
  - `engine.select_rule(policy, ctx: dict, cumulative_after: Decimal | None) -> PolicyRule` — duyệt theo `priority` tăng dần, rule đầu tiên thoả `amount ≤ max_amount` (hoặc null) **và** `cumulative_after < cap` (hoặc null) **và** `< pct × annual_fixed_cost` (hoặc null)
  - `engine.start(subject, subject_kind: str, submitted_by: User) -> WorkflowInstance` — lấy policy active có `effective_from ≤ hôm nay`, version cao nhất; chụp rule + steps vào `snapshot`; tạo task: bước cùng `seq` chạy song song; `BUDGET_OWNER` sinh một task cho mỗi budget unit; `CONSULT` sinh một task cho mỗi `consult_unit_ids`; seq đầu `PENDING`, còn lại `WAITING`
  - `engine.candidates(task) -> QuerySet[User]` (vai trò + phạm vi, xét tại thời điểm hành động)
  - `engine.act(task, user, decision: "APPROVE"|"REJECT"|"RETURN"|"COMMENT", comment: str = "", *, on_behalf_of: User | None = None) -> WorkflowTask` — raise `AlreadyProcessed`, `NotAllowed(message_vi)`
  - Quy tắc `act`: khoá task bằng `select_for_update`; người nộp/người tạo → `NotAllowed("Không được duyệt hồ sơ do chính mình lập")`; `SYS_ADMIN` thuần không có vai trò bước → `NotAllowed`; bước `mandatory=False` chỉ nhận `COMMENT` và không chặn chuyển seq; `REJECT`/`RETURN` cần comment; `MEETING` cần có `Document(requires_doc_type)` gắn vào subject trước khi `APPROVE`; `PROPOSE` tự `SKIPPED` nếu người nộp có đúng vai trò đó; hết task bắt buộc của một seq → mở seq kế; hết seq → instance `APPROVED` và gọi callback; `REJECT` → instance `REJECTED`; `RETURN` → `RETURNED`
  - Mọi chuyển trạng thái ghi audit `workflow.*`

- [ ] **Step 1: Viết test**

```python
# chính sách mẫu "Trong ngân sách" (spec mục 4): rule1 max 199_999_999, rule2 max 2_000_000_000, rule3 không max
@pytest.mark.parametrize("amount,label", [
    (199_999_999, "<200tr"), (200_000_000, "200tr-2ty"), (2_000_000_000, "200tr-2ty"), (2_000_000_001, ">2ty")])
def test_in_budget_rule_boundaries(db, in_budget_policy, amount, label):
    assert select_rule(in_budget_policy, {"amount_vnd": Decimal(amount)}, None).label == label

# chính sách "Ngoài ngân sách": A max 49_999_999 cap 200_000_000; B max 300_000_000 cap 2_000_000_000;
# C max 3_000_000_000 cap_pct 2; D catch-all
def test_cumulative_escalates(db, out_budget_policy, settings_fixed_cost_100ty):
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(10_000_000)}, Decimal(150_000_000)).label == "A"
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(10_000_000)}, Decimal(200_000_000)).label == "B"
    assert select_rule(out_budget_policy, {"amount_vnd": Decimal(400_000_000)}, Decimal(2_000_000_000)).label == "D"  # = 2% của 100 tỷ

def test_parallel_budget_owner_branches(db, req_two_units, requester):
    inst = start(req_two_units, "requisition", requester)
    owner_tasks = inst.tasks.filter(kind="BUDGET_OWNER")
    assert owner_tasks.count() == 2 and set(owner_tasks.values_list("status", flat=True)) == {"PENDING"}

def test_requester_cannot_approve_own(db, running_instance, requester):
    with pytest.raises(NotAllowed, match="chính mình lập"): act(first_task(running_instance), requester, "APPROVE")

def test_advisory_consult_does_not_block(db, ...): ...  # CONSULT mandatory=False: seq kế mở dù chưa có ý kiến

def test_double_act_rejected(transactional_db, ...): ...  # hai luồng act cùng task → một AlreadyProcessed

def test_snapshot_survives_policy_change(db, running_instance): ...
    # tạo policy version 2 với bước khác → running_instance vẫn theo snapshot cũ; hồ sơ mới theo version 2

def test_meeting_step_requires_minutes(db, ...): ...  # thiếu MEETING_MINUTES → NotAllowed

def test_return_requires_comment_and_sets_status(db, ...): ...
```

- [ ] **Step 2: Chạy** → FAIL. **Step 3: Cài đặt.** **Step 4: Chạy** → PASS.
- [ ] **Step 5: Commit** `feat(workflow): configurable versioned approval engine with parallel branches and SoD`

---

### Task 10: Thông báo: outbox, cấu hình SMTP, mẫu email, worker

**Files:**
- Create: `src/apps/notifications/{models,outbox,mailer}.py`, `management/commands/run_worker.py`, `views.py` (màn hình Cài đặt email + nút gửi thử)
- Test: `tests/notifications/test_outbox.py`

**Interfaces:**
- Consumes: `crypto`, `audit.record`
- Produces:
  - `EmailSettings` (singleton: host, port, use_tls, use_ssl, username, password_encrypted, from_address); chỉ `SYS_ADMIN` sửa; mật khẩu không bao giờ hiển thị lại (ô trống = giữ nguyên)
  - `EmailTemplate(code unique, subject, body)`; seed mã: `OFFICIAL` (việc cần duyệt), `CONSULT` (xin ý kiến), `REMINDER` (sắp đến hạn), `OVERDUE` (quá hạn), `ESCALATION` (chuyển cấp), `RESULT` (kết quả)
  - `Outbox(kind "EMAIL", payload JSON, status "PENDING"|"SENT"|"FAILED", attempts, next_attempt_at, last_error)`
  - `Notification(user, title, url, created_at, read_at null)`
  - `outbox.enqueue_email(to: list[str], template_code: str, context: dict) -> Outbox`
  - `outbox.notify(user, title, url, *, email_template: str | None = None, context: dict | None = None) -> None`
  - `outbox.process_due(now) -> int` (số đã gửi; lỗi → `attempts+1`, lùi `next_attempt_at` 2^attempts phút, quá 6 lần → FAILED)
  - Lệnh `run_worker` lặp mỗi 30 giây: `process_due`, và mỗi 5 phút gọi `workflow.sla.process_sla(now)` (Task 11)

- [ ] **Step 1: Test:** mẫu render Django template có autoescape (`<script>` trong context bị escape); SMTP lỗi → attempts tăng và `next_attempt_at` lùi đúng; mật khẩu lưu trong DB khác chuỗi gốc; gửi thử dùng `locmem` backend; đổi cấu hình email ghi audit nhưng `changes` không chứa mật khẩu.
- [ ] **Step 2–4:** FAIL → cài đặt → PASS. **Step 5: Commit** `feat(notifications): outbox email with UI-configured SMTP, templates, worker`

---

### Task 11: Uỷ quyền duyệt thay, thời hạn xử lý và chuyển cấp

**Files:**
- Create: `src/apps/workflow/{delegation,sla}.py`; Modify: `engine.py` (candidates/act xét uỷ quyền), `engine.start` (gán `due_at`, gửi `OFFICIAL`/`CONSULT`)
- Test: `tests/workflow/test_delegation.py`, `tests/workflow/test_sla.py`

**Interfaces:**
- Consumes: `notify`, `engine`
- Produces:
  - `Delegation(delegator, delegate, start date, end date, max_amount_vnd null, subject_kinds JSON list, org_unit null, letter FK Document null, revoked_at null)`
  - `delegation.active_delegations_for(user, on: date) -> QuerySet[Delegation]` (người nhận)
  - `delegation.can_act_on_behalf(delegate, task) -> User | None` → trả người uỷ quyền nếu hợp lệ
  - Quy tắc: không bắc cầu (uỷ quyền của người nhận không được dùng tiếp); `amount_vnd` hồ sơ > `max_amount_vnd` → không hợp lệ; người nhận là người nộp/tạo hồ sơ → không hợp lệ; tạo Delegation với `delegate == delegator` → `ValidationError`
  - `sla.process_sla(now) -> SlaReport(reminded:int, overdue:int, escalated:int)` — `REMINDER` khi còn ≤ 24 giờ; `OVERDUE` khi quá `due_at`; quá `due_at + sla_hours` → `ESCALATION` gửi `users_with_role(escalate_role_code)`; mỗi loại chỉ gửi một lần cho mỗi task (đánh dấu trên task: `reminded_at`, `overdue_notified_at`, `escalated_at`)

- [ ] **Step 1: Test:** người nhận duyệt trong hạn → task `acted_by=delegate, on_behalf_of=delegator`, audit ghi "duyệt thay"; ngoài khoảng ngày → `NotAllowed`; vượt `max_amount_vnd` → `NotAllowed`; uỷ quyền bắc cầu A→B→C: C không duyệt được; `freezegun`: chạy `process_sla` hai lần liên tiếp chỉ gửi một email mỗi loại.
- [ ] **Step 2–4:** FAIL → cài đặt → PASS. **Step 5: Commit** `feat(workflow): delegation and SLA reminders/escalation`

---

### Task 12: Tờ trình mua sắm

**Files:**
- Create: `src/apps/requisitions/{models,services,forms}.py`, `src/apps/workflow/splitting.py`
- Test: `tests/requisitions/test_submit.py`, `tests/requisitions/test_lifecycle.py`, `tests/workflow/test_splitting.py`

**Interfaces:**
- Consumes: `next_number`, `to_vnd`, `ledger.balance/reserve/release`, `engine.start`, `Document`, `Vendor.is_selectable`
- Produces:
  - `Requisition(number unique null (cấp khi nộp), version int, previous FK self null, title, requester FK User, requester_unit FK OrgUnit, procurement_type "PROJECT"|"BAU"|"TRAVEL"|"OTHER", necessity text, currency, fx_rate, total_original Decimal(18,2), total_vnd Decimal(18,0), service_start date, months int ≥1, vendor FK null, quote_exception_reason text, consult_units M2M OrgUnit, status "DRAFT"|"IN_APPROVAL"|"RETURNED"|"APPROVED"|"BUDGET_BLOCKED"|"REJECTED"|"CANCELLED", created_by, created_at)`
  - `RequisitionLine(requisition, description, quantity Decimal(12,2), unit_price Decimal(18,2), vat_rate Decimal(5,2))` → `amount` tính
  - `RequisitionFunding(requisition, budget_line FK, amount_vnd Decimal(18,0))`
  - `services.validate_for_submit(req) -> list[str]` (thông báo tiếng Việt): có ít nhất 1 dòng; tổng funding = `total_vnd`; có 3 Document `QUOTE` **hoặc** `quote_exception_reason`; vendor (nếu có) `is_selectable()`; budget line cùng năm với `service_start`
  - `services.check_budget(req) -> BudgetCheck(ok: bool, shortfalls: list[tuple[BudgetLine, Decimal]], warnings: list[str])` (không ghi gì)
  - `services.submit(req, user) -> WorkflowInstance` — raise `SubmitBlocked(errors)` hoặc `InsufficientBudget`; cấp `number`; tính `total_vnd` theo tỷ giá ngày nộp; `engine.start(req, "requisition", user)`
  - `Requisition.on_workflow_finished("APPROVED")` → `ledger.reserve(...)` theo funding, `start=service_start, months=months`; nếu `InsufficientBudget` tại thời điểm này (ngân sách bị dùng hết trong lúc chờ duyệt) → tờ trình chuyển `BUDGET_BLOCKED`, không ghi giữ chỗ, thông báo người lập và FAD; người lập tạo đề nghị bổ sung ngân sách rồi FAD bấm "Giữ chỗ lại" (`services.retry_reserve(req, user)`) (không âm thầm vượt ngân sách)
  - `services.cancel(req, user, reason)` → APPROVED thì `ledger.release`
  - `services.revise(req, user) -> Requisition` (từ RETURNED: tạo bản `version+1`, `previous=req`, sao chép dòng/funding/chứng từ gắn lại bằng tham chiếu)
  - `services.copy_as_new(req, user) -> Requisition` (R78)
  - `Requisition.visible_to(user)`: người tạo, cùng phòng, người có task, đơn vị quản lý ngân sách liên quan, FAD, AUDITOR
  - `splitting.split_warnings(req) -> list[str]` — cùng `requester_unit` và (cùng vendor **hoặc** cùng cost_code) trong `split_window_days` ngày, tổng (kể cả hồ sơ này) > `max_amount` của rule mà hồ sơ này khớp → cảnh báo nêu số các tờ trình liên quan

- [ ] **Step 1: Viết test**

```python
def test_submit_blocked_without_quotes_or_reason(db, draft_req, requester):
    with pytest.raises(SubmitBlocked) as e: submit(draft_req, requester)
    assert "03 báo giá" in " ".join(e.value.errors)

def test_submit_blocked_when_no_budget_offers_change_request(db, draft_req_over_budget, requester):
    with pytest.raises(InsufficientBudget): submit(draft_req_over_budget, requester)

def test_usd_converted_at_submit_date(db, draft_req_usd, requester, usd_rate): ...

def test_approval_reserves_by_allocation(db, approved_req_12_months):
    # 120tr, 12 tháng từ 2026-01 → 12 bút toán RESERVE 10tr
    assert reserved_entries(approved_req_12_months) == [(date(2026, m, 1), Decimal("10000000")) for m in range(1, 13)]

def test_cancel_releases(db, approved_req, requester): ...
def test_revise_creates_new_version_keeps_history(db, returned_req, requester): ...
def test_split_warning(db, ...): ...  # 3 tờ trình 80tr cùng NCC trong 30 ngày, rule max 199_999_999 → 1 cảnh báo nêu 2 số tờ trình kia
```

- [ ] **Step 2–4:** FAIL → cài đặt → PASS. **Step 5: Commit** `feat(requisitions): requisition lifecycle with budget check, reservation, versions, split warnings`

---

### Task 13: Đề nghị bổ sung / điều chuyển ngân sách

**Files:**
- Create: `src/apps/budget_changes/{models,services}.py`
- Test: `tests/budget_changes/test_budget_changes.py`

**Interfaces:**
- Consumes: `engine.start`, `ledger.post`, `allocate`, `get_setting("cumulative_scope")`
- Produces:
  - `BudgetChangeRequest(number "NS-YYYY-NNNNN", kind "SUPPLEMENT"|"TRANSFER", from_line null, to_line, amount_vnd, start date, months, reason, requisition FK null, requester, requester_unit, status như Requisition)`
  - `services.prefill_from_shortfall(req: Requisition, shortfalls) -> list[BudgetChangeRequest]` (bản nháp, một đề nghị cho mỗi dòng thiếu)
  - `cumulative_amount_vnd(scope)` = tổng `SUPPLEMENT` đã APPROVED trong năm (scope `COMPANY` hoặc cùng `budget_unit` của `to_line`) + chính đề nghị này
  - `on_workflow_finished("APPROVED")`: `SUPPLEMENT` → `ADJUST` dương theo `allocate`; `TRANSFER` → cặp `TRANSFER` âm (from) / dương (to) cùng kỳ; `TRANSFER` kiểm tra `from_line` đủ số dư trước khi ghi
  - Subject kind `"budget_change"` dùng chính sách "Ngoài ngân sách" (Task 9)

- [ ] **Step 1: Test:** duyệt SUPPLEMENT 60tr/6 tháng → 6 bút toán ADJUST 10tr; TRANSFER vượt số dư from_line → `InsufficientBudget`; luỹ kế: đã duyệt 150tr, đề nghị mới 60tr → rule B (60tr vượt max của A); đề nghị 10tr khi đã duyệt 195tr → rule B (luỹ kế 205tr không < 200tr); tờ trình bị chặn → `prefill_from_shortfall` tạo đúng số tiền thiếu.
- [ ] **Step 2–4:** FAIL → cài đặt → PASS. **Step 5: Commit** `feat(budget_changes): supplement/transfer requests with cumulative out-of-budget routing`

---

### Task 14: Khung giao diện và bảng dữ liệu dùng chung

**Files:**
- Create: `src/apps/ui/{tables,export}.py`, `src/templates/base.html`, `src/templates/ui/table.html`, `src/static/{css/app.css,js/app.js}`, `src/static/vendor/htmx.min.js` (đóng gói, ghi phiên bản trong `src/static/vendor/VERSIONS.txt`)
- Test: `tests/ui/test_tables.py`

**Interfaces:**
- Consumes: `format_vnd`
- Produces:
  - `Column(key: str, label: str, sortable=True, money=False, sum=False)`; `TableSpec(key: str, columns: list[Column], filters: dict[str, str] (tham số → lookup ORM), search_fields: list[str], default_sort: list[str], group_by: str | None = None, page_size: int = 50)`
  - `apply_table(request, qs, spec) -> TablePage(rows, page_obj, totals: dict, group_totals: dict, sort: list[str], params: dict)` — `?sort=a,-b` (chỉ cột `sortable`, tham số lạ bị bỏ qua), `?q=` tìm trên `search_fields` không dấu, filter từ whitelist `filters`
  - `SavedFilter(user, table_key, name, params JSON)`
  - `export.to_xlsx(spec, qs) -> bytes` (đúng bộ lọc đang xem; tiền xuất dạng số, định dạng `#,##0`); in/lưu PDF qua stylesheet `@media print` (quyết định: không thêm thư viện PDF ở đợt 1)
  - Template: tiêu đề cột cố định khi cuộn (`position: sticky`), chọn nhiều dòng (checkbox + `name="ids"`)

- [ ] **Step 1: Test:** sort nhiều cột đúng thứ tự; `?sort=password` bị bỏ qua; tổng cột tiền và tổng phụ theo `group_by` đúng; `q="chuong duong"` khớp "Chương Dương"; xuất xlsx có đúng số dòng của bộ lọc.
- [ ] **Step 2–4:** FAIL → cài đặt → PASS. **Step 5: Commit** `feat(ui): base layout and reusable data tables with filter/sort/subtotal/export`

---

### Task 15: Màn hình nghiệp vụ đợt 1

**Files:**
- Create: views/templates/urls trong từng app; `src/config/urls.py` gom route tiếng Việt
- Test: `tests/views/test_pages.py`

**Interfaces:**
- Consumes: tất cả service ở trên; `apply_table`
- Produces (URL, quyền):
  - `/` "Việc chờ tôi": task `PENDING` mà user là candidate hoặc duyệt thay; chọn nhiều → `POST /viec/xu-ly-hang-loat/` (`ids`, `decision`, `comment`) trả kết quả từng hồ sơ (thành công / lý do lỗi)
  - `/to-trinh/` danh sách; `/to-trinh/tao/`, `/to-trinh/<id>/` (chi tiết: dòng, funding với số dư khả dụng từng dòng ngân sách, chứng từ, lịch sử duyệt từ audit, nút hành động theo quyền), `/to-trinh/<id>/nop/`, `/to-trinh/<id>/sao-chep/`
  - `/to-trinh/<id>/tien-kiem/` (chỉ `FAD_PRECHECK`): số dư từng funding, rule thẩm quyền đã chọn + snapshot các bước, cảnh báo chia nhỏ, ý kiến tham vấn, checklist chứng từ, ô ý kiến tiền kiểm, nút đạt / trả lại
  - `/ngan-sach/` dòng ngân sách + số dư (đơn vị quản lý thấy phần mình, FAD thấy tất cả); `/ngan-sach/<line>/so-cai/`; `/ngan-sach/nhap-excel/` (`FAD_BUDGET_ADMIN`: tải lên → xem báo cáo làm sạch → xác nhận nhập)
  - `/ngan-sach/de-nghi/` đề nghị bổ sung/điều chuyển (tạo từ tờ trình bị chặn bằng tham số `?tu_to_trinh=<id>`)
  - `/nha-cung-cap/`, `/nha-cung-cap/nhap-excel/`
  - `/uy-quyen/` tạo/thu hồi uỷ quyền của chính mình (đính kèm văn bản)
  - `/tim-kiem/?q=` tìm chứng từ + hồ sơ
  - `/nhat-ky/` tra cứu audit (`AUDITOR`, FAD), xuất xlsx
  - `/cai-dat/` (`SYS_ADMIN`): email, tỷ giá, tham số (`split_window_days`, `annual_fixed_cost_vnd`, `cumulative_scope`, `max_upload_mb`); chính sách duyệt quản trị qua Django admin tại `/quan-tri/` (chỉ `SYS_ADMIN`, chỉ tạo version mới)

- [ ] **Step 1: Test:** mỗi URL: chưa đăng nhập → chuyển `/dang-nhap/`; sai vai trò → 403; người khác phòng mở `/to-trinh/<id>/` → 403; xử lý hàng loạt 3 task trong đó 1 task là hồ sơ của chính user → 2 thành công, 1 lỗi "Không được duyệt hồ sơ do chính mình lập"; mọi form POST có CSRF; trang chi tiết hiển thị số tiền dạng `1.234.567` và số tiền bằng chữ.
- [ ] **Step 2–4:** FAIL → cài đặt → PASS. Dùng skill `impeccable`/`ui-ux-pro-max` cho bố cục; ưu tiên rõ ràng cho người dùng kế toán (bảng dày thông tin, chữ ≥ 14px).
- [ ] **Step 5: Commit** `feat: phase-1 business screens`

---

### Task 16: Dữ liệu demo và kịch bản nghiệm thu đợt 1

**Files:**
- Create: `src/apps/core/management/commands/seed_demo.py`, `tests/e2e/test_dot1_scenario.py`, `docs/04-kiem-thu/kich-ban-dot-1.md`

**Interfaces:**
- Consumes: mọi service; `sample-data/` từ Task 7
- Produces: lệnh `seed_demo` tạo: đơn vị và người giả (requester phòng DEMO-A, TP, GĐĐH, đơn vị quản lý ngân sách ITD-DEMO và ADM-DEMO, FAD tiền kiểm, thư ký BMS, CEO), ngân sách giả 2026, tỷ giá USD, 2 chính sách mẫu (Trong ngân sách, Ngoài ngân sách) theo bảng thẩm quyền spec mục 4, tham vấn mặc định `mandatory=False`, FAD tiền kiểm `mandatory=True`, SLA 48 giờ. Các bước (seq: kind/role/scope):
  - Trong ngân sách `<200tr`: 1 BUDGET_OWNER/BUDGET_OWNER/BUDGET_UNIT · 2 CONSULT/CONSULTANT/SELECTED_UNITS · 3 FAD_PRECHECK/FAD_PRECHECK/COMPANY · 4 APPROVE/DEPT_HEAD (GĐNV/TP)/REQUESTER_UNIT
  - `200tr-2ty`: 1 PROPOSE/DEPT_HEAD/REQUESTER_UNIT · 2 BUDGET_OWNER · 3 CONSULT · 4 FAD_PRECHECK · 5 APPROVE/GDDH/COMPANY
  - `>2ty`: 1 PROPOSE/GDDH/COMPANY · 2 BUDGET_OWNER · 3 CONSULT · 4 FAD_PRECHECK · 5 MEETING/BMS_SECRETARY/COMPANY (`requires_doc_type=MEETING_MINUTES`)
  - Ngoài ngân sách A/B/C/D: 1 PROPOSE (A: DEPT_HEAD; B, C: GDDH; D: CEO) · 2 FAD_PRECHECK · 3 duyệt (A: APPROVE/GDDH; B: MEETING/BMS_SECRETARY; C: APPROVE/CEO; D: MEETING/BOARD_SECRETARY)

- [ ] **Step 1: Viết test kịch bản (spec mục 10, kết quả kiểm chứng đợt 1)**

```python
def test_dot1_end_to_end(db, seeded, mailoutbox):
    req = create_requisition(requester, currency="USD", lines=[("Thiết bị", 1, Decimal("100000"))],
                             funding=[(line_itd, 60%), (line_adm, 40%)], quotes=3, consult=[unit_dti],
                             service_start=date(2026,12,1), months=1)
    inst = submit(req, requester)                         # ~2,546 tỷ VND → rule ">2ty" → BMS (MEETING)
    with pytest.raises(NotAllowed): act(task(inst, "PROPOSE"), requester, "APPROVE")  # người lập không tự duyệt
    delegate(gddh, to=deputy, days=3); act(task(inst, "PROPOSE"), deputy, "APPROVE")  # duyệt thay GĐĐH
    assert task(inst, "PROPOSE").on_behalf_of == gddh
    act_all(inst, "BUDGET_OWNER")                         # 2 nhánh song song
    comment(inst, "CONSULT", dti_user)                    # ý kiến tham vấn hiển thị ở màn hình tiền kiểm
    act(task(inst, "FAD_PRECHECK"), fad_user, "APPROVE")
    attach(req, MEETING_MINUTES); act(task(inst, "MEETING"), bms_secretary, "APPROVE")
    req.refresh_from_db(); assert req.status == "APPROVED"
    assert balance(line_itd).reserved + balance(line_adm).reserved == req.total_vnd
    assert verify_chain() == [] and audit_actions(req) >= {"requisition.submitted", "workflow.approved", "budget.entry_posted"}
    assert any("cần duyệt" in m.subject for m in mailoutbox)
```
`docs/04-kiem-thu/kich-ban-dot-1.md`: cùng kịch bản viết dạng các bước bấm trên giao diện cho người dùng tự kiểm tra (cột: bước, thao tác, kết quả mong đợi, đạt/không).

- [ ] **Step 2–4:** FAIL → bổ sung chỗ thiếu → PASS. **Step 5: Commit** `test: phase-1 acceptance scenario and demo seed`

---

### Task 17: Bộ cài đặt Docker cho Ubuntu 26.04

**Files:**
- Create: `deploy/Dockerfile`, `deploy/docker-compose.yml`, `deploy/nginx/nginx.conf`, `deploy/postgres/init.sql`, `deploy/scripts/{install,upgrade,backup,restore}.sh`, `src/apps/core/management/commands/apply_db_grants.py`, `docs/05-ban-giao-it/huong-dan-cai-dat.md`
- Test: `tests/deploy/test_deploy_files.py`

**Interfaces:**
- Produces:
  - Image: `python:3.12-slim`, user không phải root, `gunicorn config.wsgi -w 3 -b 0.0.0.0:8000`, `collectstatic` lúc build
  - Compose services: `db` (postgres:16, volume `pgdata`), `app`, `worker` (`run_worker`), `nginx` (cổng 443, chứng chỉ mount từ `deploy/certs/`; phục vụ `/static/`; **không** phục vụ `MEDIA_ROOT`); volume `media` dùng chung app/worker
  - Hai user DB: `procurement_owner` (chạy migrate) và `procurement_app` (runtime); `apply_db_grants` cấp quyền DML cho app và `REVOKE UPDATE, DELETE, TRUNCATE` trên `audit_auditevent`, `budget_budgetentry`
  - `install.sh`: kiểm tra Docker/Compose; sinh `.env` với `SECRET_KEY`, `APP_ENCRYPTION_KEY`, mật khẩu DB ngẫu nhiên (không ghi đè `.env` đã có); `docker compose up -d`; `migrate` (owner); `apply_db_grants`; tạo tài khoản `SYS_ADMIN` đầu tiên (hỏi tương tác)
  - `upgrade.sh`: `backup.sh` trước → pull/build → migrate → grants → restart
  - `backup.sh`: `pg_dump -Fc` + `tar` media vào `BACKUP_DIR` có dấu thời gian; `restore.sh <file>` ngược lại (hỏi xác nhận)
  - Nginx: chỉ TLS 1.2+, header `Strict-Transport-Security`, `X-Content-Type-Options nosniff`, `Referrer-Policy same-origin`, `client_max_body_size 26m`, `limit_req` cho `/dang-nhap/`
  - Hướng dẫn cài đặt (tiếng Việt) cho IT: yêu cầu máy chủ, các bước, biến môi trường, cấu hình Entra ID (redirect URI), sao lưu/khôi phục, nâng cấp, kiểm tra `GET /healthz`

- [ ] **Step 1: Test:** `docker compose -f deploy/docker-compose.yml config` thoát mã 0; `shellcheck deploy/scripts/*.sh` không lỗi; nginx.conf không có `location /media`; `.env.example` liệt kê đủ biến mà `prod.py` đọc (test so khớp danh sách).
- [ ] **Step 2–3:** FAIL → cài đặt.
- [ ] **Step 4: Chạy smoke test** (nếu môi trường có Docker): `cd deploy && ./scripts/install.sh --non-interactive --admin-user admin --admin-email admin@example.com` rồi `curl -k https://localhost/healthz` → `{"status": "ok", "db": "ok"}`; thử `UPDATE audit_auditevent ...` bằng user `procurement_app` → bị từ chối.
- [ ] **Step 5: Commit** `feat(deploy): Docker installer for Ubuntu 26.04 with backup/restore and DB grants`

---

## Truy vết spec → task

| Spec | Task |
|---|---|
| 6 Kiến trúc, bộ cài đặt, cấu hình qua giao diện, tỷ giá | 1, 4, 10, 17 |
| 7 `accounts` (Entra ID, HRIS) | 3 |
| 7 `audit`, 8.3 | 2 |
| 7 `documents`, 7.4 (đợt 1: trích chữ PDF, tìm kiếm, lưu vĩnh viễn) | 5 |
| 7.1 luồng duyệt; 7.2 uỷ quyền; SLA | 9, 11 |
| 7.3 sổ ngân sách, chi phí phân bổ, nhiều đơn vị, hợp đồng nhiều năm | 6, 12 |
| 7.5 nhập Budget Control, báo cáo làm sạch | 7 |
| `vendors` | 8 |
| `requisitions`, chặn khi thiếu ngân sách, 4.1 | 12, 13 |
| `notifications` (R62, R83) | 10, 11 |
| `ui` (R65–R81, R88) | 14, 15 |
| 8.1–8.5 bảo mật | 1, 2, 3, 5, 9, 17 |
| 10 Kết quả kiểm chứng đợt 1 | 16 |

Ngoài đợt 1 (không làm trong kế hoạch này): OCR bản scan, XML hoá đơn, ký số FPT, PAS/IMS/SUN thật, báo cáo Budget 2026/Reconcile BI, chuyển lịch sử `Data new`, phần dành cho NCC.
