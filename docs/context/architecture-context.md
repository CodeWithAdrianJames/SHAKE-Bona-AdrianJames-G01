# Architecture Context

## Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Framework | Django (Python 3.x) | Server-rendered full-stack web application, ORM, and REST endpoints |
| UI | Tabler 1.7.5 (Bootstrap 5) + Tabler Icons 3.53.0 + Django Templates | Offline-bundled responsive workspace (`static/vendor/tabler/`) themed by the SHAKE "Settle" identity in `static/css/shake-theme.css` with locally bundled Manrope / Inter / JetBrains Mono WOFF2 fonts (`static/fonts/`); forms and data-dense inspection tables |
| Auth | Custom Django Auth (`accounts.CustomUser`) | Email-based login, role assignment (`ADMIN`, `ENCODER`), and session/token guards |
| Database | PostgreSQL (`DATABASE_URL`) / SQLite (`db.sqlite3`) | Normalized 3NF persistence with native `UNIQUE`, `CHECK`, and `FK` constraints |
| PDF Engine | PyMuPDF (`fitz`) + OpenDataLoader Java AST | 100% offline vector text/coordinate extraction and cross-page table stitching |
| Exporters | Python `json`, `csv`, and `openpyxl` | Deterministic canonical `JSON`, multi-sheet `.xlsx`, and `CSV` artifact generation |
| File Storage | Local Filesystem (`media/`) | Local storage for uploaded contract PDFs and exported datasets |

## System Boundaries

- `shake/` — Core project configuration (`settings.py` with dual SQLite/PostgreSQL database resolution and the `SHAKE_API_LOOPBACK_*` settings) and root URL routing (`urls.py`, mounting `contracts.api_urls` at `/api/v1/`).
- `accounts/` — Custom user model (`CustomUser`), per-user loopback API Bearer tokens (`APIToken`), case-insensitive email authentication backend (`accounts/backends.py` `EmailBackend`), authentication views, self-only profile management, password change (`/accounts/password/`), API token generate/revoke (`/accounts/profile/api-tokens/`), and the shared `BootstrapFormMixin` (`accounts/forms.py`).
- `dashboard/` — Role guards (`RoleRequiredMixin` and `@role_required` in `dashboard/views.py`) and role-aware workspace dashboards (`/dashboard/encoder/`, `/dashboard/admin/`) aggregating live database KPIs, recent batches, processing jobs, and export logs.
- `contracts/` — Primary domain application containing models, forms, views, URL routes, services, and the offline extraction engine:
  - `contracts/engine/` — Pure offline document processing modules (`ingestion.py`, `extraction.py`, `mapping.py`, `exporter.py`, `models.py`, `errors.py`) decoupled from HTTP request/response objects.
  - `contracts/services/` — Transactional ORM pipeline orchestration (`pipeline.py`), export artifact + `ExportRecord` audit logging, and the API contract payload builder (`exporter.py`).
  - `contracts/api_views.py`, `contracts/api_urls.py` — Local loopback REST API (`F-11`): loopback guard, Bearer/session authentication, `POST /api/v1/ingest`, `GET /api/v1/contracts/<pk>`.
- `templates/` — Tabler (Bootstrap 5) HTML templates (`base.html`, `accounts/`, `registration/`, `contracts/`, `dashboard/`, `includes/` incl. the `status_badge.html` partial and the sectioned-form partials `form_field.html` / `form_errors.html`) plus the error pages `403.html`, `404.html`, and `500.html`.
- `static/` — Local front-end assets served by `django.contrib.staticfiles` (`STATICFILES_DIRS`): `vendor/tabler/` (Tabler `css/tabler.min.css`, `js/tabler.min.js` with the bundled Bootstrap JS, and `icons/tabler-icons.min.css` + `icons/fonts/*.woff2`; MIT), `css/shake-theme.css` (the official SHAKE "Settle" brand theme: color tokens, type scale, `@font-face` rules, the navigation rail, and the page/ledger/upload layout components), `js/shake-ui.js` (the only first-party script: rail pin + mobile drawer, `data-confirm` prompts, clipboard copy, `/` search shortcut, live table filters, upload dropzone; dependency-free, no network requests), `fonts/` (SIL OFL 1.1 WOFF2 subsets, latin + latin-ext, of Manrope 500/700/800, Inter 400/500/600, and JetBrains Mono 400/500 from Fontsource 5.3.0, with their `OFL-*.txt` licenses), and `img/` (the Settle mark on the 64-unit grid: `shake-mark.svg` on light, `shake-mark-hull.svg` on Deep Hull, `shake-mark-tide.svg` reversed on Tide, `favicon.svg` with the <= 32 px two-stroke simplification, and the `shake-state-raw.svg` / `shake-state-structured.svg` extraction-state glyphs). No template references a CDN, Google Fonts, or any remote font.
- `templates/partials/` — Inline-SVG brand partials: `shake_mark.html` (the mark, `tone` light/hull/tide), `shake_lockup.html` (horizontal mark + Manrope 800 wordmark), `shake_state.html` (`1 · Raw` / `2 · SHAKE` / `3 · Structured` glyphs), and `empty_state.html` (empty state on the Structured glyph).
- `media/` — Runtime directory for local uploaded PDFs and exported files (git-ignored). Only `media/profile_photos/` is ever served as static files (and only when `DEBUG=True`); uploaded contract PDFs and export files are never URL-addressable.

## Storage Model

- **Relational Database (9 Normalized Entities):**
  - `accounts_customuser` (SDD `app_users`): Registered operators (`ENCODER`) and administrators (`ADMIN`).
  - `accounts_apitoken`: Per-user loopback API Bearer tokens (`name`, unique 64-hex `key` from `secrets.token_hex(32)`, `is_active`, `created_at`, `last_used_at`; `user` FK `ON DELETE CASCADE`). Revocation sets `is_active = False`. Added by `accounts/migrations/0003_apitoken.py`.
  - `carrier_profiles`: Master carrier definitions (`carrier_code`, `carrier_name`, `template_version`, `is_active`).
  - `batch_uploads`: Logical batch grouping (`batch_number`, `total_files`, `status`, `user` FK as uploader).
  - `document_files`: Physical PDF metadata (`original_file_name`, `file_hash_sha256`, `file_size_bytes`, `page_count`, `status`).
  - `processing_jobs`: Execution diagnostics (`job_type`, `status`, `error_message`, `started_at`, `completed_at`).
  - `contract_metadata`: Context-aware parent contract record (`contract_number`, `trade_scope`, `commodity_desc`, `effective_date`, `expiration_date`, 1:1 with `DocumentFile`, M:1 with `CarrierProfile`).
  - `freight_rates`: Line-item base ocean freight rates (`origin_port_code`, `destination_port_code`, `equipment_type`, `currency_code`, `rate_amount`, `source_page_start`, `source_page_end`, `confidence_score`).
  - `arbitrary_charges`: Origin/destination inland surcharges (`charge_type`, `location_code`, `via_gateway_port`, `equipment_type`, `currency_code`, `charge_amount`, `transport_mode`).
  - `export_records`: Immutable export audit history (`user_id`, `contract_id`, `export_format`, `file_path`, `exported_at`). `contract` FK is `ON DELETE RESTRICT` (`contracts/migrations/0003_hardening_field_validators.py`), so a contract with export history cannot be hard-deleted.
- **Local Artifact Storage:** Uploaded PDFs and generated export files reside on the local filesystem under `media/`, with relative paths stored in `DocumentFile.uploaded_file` and `ExportRecord.file_path`.

## Auth and Access Control Model

- Every user authenticates via unique email (`CustomUser`) with role `ENCODER` (SDD `OPERATOR`) or `ADMIN`. The public login form (`CustomLoginForm`) accepts email only; `EmailBackend` matches it case-insensitively and falls back to username lookups only for the Django admin site.
- Emails are stored trimmed and lowercased (`CustomUser.save()`), and the database enforces `UNIQUE (email)` and `CHECK (role IN ('ADMIN', 'ENCODER'))` via `accounts/migrations/0002_user_constraints.py`.
- Public registration (`CustomUserCreationForm`) exposes no role selector and always assigns `ENCODER` server-side; `ADMIN` accounts are provisioned only through the Django admin or `createsuperuser`.
- All authenticated routes enforce `LoginRequiredMixin`.
- `ContractOwnershipMixin` enforces data isolation across all contract, rate, document, and export endpoints: `ENCODER` users can read or mutate **only** records linked to batches they uploaded; `ADMIN` users can inspect and manage all records across the system.
- Administrative management views (`/contracts/carriers/*`, `/dashboard/admin/`) require `RoleRequiredMixin(allowed_roles=[CustomUser.Role.ADMIN])`.
- `ContractOwnershipMixin.get_queryset()` delegates to `scope_contracts_to_user(queryset, user)` (`contracts/views.py`), which the REST API reuses so web and API visibility cannot drift.

## PD3 Hardening (Validation, Error Pages & Security)

### Configuration & Secrets (`shake/settings.py`)

- `DEBUG = env_bool('DEBUG', default=False)`: unset or blank `DEBUG` means `False`. It is enabled only by `DEBUG=True` in `.env` or the environment.
- `SECRET_KEY` is read only from `SECRET_KEY` / `DJANGO_SECRET_KEY`; no key is hardcoded in source. When it is missing, DEBUG and `manage.py test` runs use a random per-process key, and every other run raises `ImproperlyConfigured`.
- `.env` and `.env.*` are git-ignored (`!.env.example` is the committed template).
- Explicit cookie/header settings: `SESSION_COOKIE_HTTPONLY`, `SameSite=Lax` session and CSRF cookies, `SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY = 'same-origin'`, `X_FRAME_OPTIONS = 'DENY'`. `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE` are opt-in via `.env` because SHAKE runs on `http://127.0.0.1`.

### Error Pages

- `templates/404.html`: standalone page (inline CSS and the inline light-surface Settle mark, no `base.html`, no static files, no CDN assets) rendered by Django's default `page_not_found` handler whenever `DEBUG=False`. Every `get_object_or_404` miss, including out-of-scope IDs, lands here. It never echoes the requested path or the exception text. Links: `/dashboard/`, `/contracts/` (signed in) or `/accounts/login/` (anonymous).
- `templates/500.html`: fully standalone. Django's `server_error` handler renders it with an empty context, so it uses no context processors, no `user`/`messages`/`request`, no URL reversing, no `{% static %}` (the Settle mark is inline SVG), and runs zero database queries. Hardcoded links to `/dashboard/` and `/accounts/login/`; no exception details.

### Server-Side Validation

- Business rules live on the models so ModelForms, the Django admin, and `full_clean()` share them: `ContractMetadata.clean()` (`BR-10`, `expiration_date >= effective_date`) and `FreightRate.clean()` (`BR-13` distinct ports, compared case-insensitively; `source_page_end >= source_page_start`). The forms no longer repeat these checks, so each error is reported once.
- Field validators mirror the database `CHECK` constraints: `rate_amount >= 0.01` (`BR-12`), `charge_amount >= 0.00`, `confidence_score` in `[0.000, 1.000]`, page numbers `>= 1`. The validator-only migration `0003` emits no SQL.
- Form layer: required fields, strip/uppercase normalization, `[A-Z]{3}` currency codes, `EquipmentType` choices, `DecimalField` `max_digits`/`decimal_places` (rejects `NaN`, `Infinity`, and overflow), and a 5 MB server-side cap on profile photos (`UserProfileUpdateForm.clean_profile_photo`). HTML `required`/`min` attributes are hints only.
- Every mutation returns `django.contrib.messages` feedback: success after the redirect, error on invalid forms, and an error redirect if an export cannot be written to disk (`OSError`).

### Access Control & Request Safety

- Every core view is `LoginRequiredMixin` (via `ContractOwnershipMixin` / `RoleRequiredMixin`); `/contracts/carriers/*` and `/dashboard/admin/` require `ADMIN`.
- IDOR: parent contracts resolve through `get_scoped_contract()` (`get_object_or_404` on the user-scoped queryset), and child `FreightRate` rows resolve with `contract=<scoped contract>`, so a foreign contract ID or a foreign rate ID under the user's own contract returns `404`. This applies to detail, edit, rate add/edit/delete, archive, export, and document delete. No web UI edits or deletes `ArbitraryCharge` rows; they are read-only through detail, export, and the API, all of which use the same scope.
- State-changing views are POST-only (`http_method_names = ["post", "options"]`) with CSRF: `rate_delete`, `document_delete`, `contract_archive`, `carrier_toggle`, `api_token_create`, `api_token_revoke`, and `logout`. GET returns `405`.
- Destructive forms (rate delete, failed-document delete, archive, API token revoke) carry a `data-confirm` message. One delegated `submit` listener in `static/js/shake-ui.js` (loaded by `base.html` via `{% static %}`) shows a confirmation prompt; the server-side POST, CSRF, and ownership checks still apply when JavaScript is disabled.
- No raw SQL (`.raw()`, `.extra()`, `cursor.execute`) anywhere in the apps. `|safe` is used only on developer-defined `help_text` (Django's password rules list), never on user-supplied strings. `contracts/test_hardening.py` scans templates statically for both rules.
- Unexpected failures are logged with `logger.exception` instead of being swallowed. Users see a plain message without database internals (for example, an ingestion `IntegrityError`).

### Transactions & Queries

- `FreightRateCreateView` reads `MAX(line_item_sequence)` and inserts in one `transaction.atomic()` block while holding `select_for_update()` on the parent contract (a no-op on SQLite). A residual `IntegrityError` becomes a form error, not a `500`.
- `DocumentFileDeleteView` deletes the row and its `ProcessingJob`s atomically, then removes the PDF from disk in `transaction.on_commit`.
- `ContractDetailView` serves rates, arbitraries, jobs, and export records (with users) from `prefetch_related`; `ContractListView` uses `select_related` + annotations. Tests assert both pages keep a constant query count as rows grow.
- All POST handlers redirect on success (Post/Redirect/Get).

## UI Shell & Client-Side Enhancements (presentation only)

- **Navigation rail (`templates/base.html`, `.shake-rail` in `shake-theme.css`):** at `>= 992px` the Deep Hull rail is a fixed 72px column and the workspace keeps a constant 72px left margin, so wide rate tables never reflow when it opens. `:hover` / `:focus-within` widens it over the canvas to 252px (`width 220ms cubic-bezier(0.22, 1, 0.36, 1)`, shadow `12px 0 32px rgba(9, 27, 38, 0.24)`) and fades in the wordmark, group headings (Workspace / Administration [ADMIN] / Account), labels, and the Abyss tagline. A pin button stores `shake.sidebar.pinned` (`"1"`/`"0"`) in `localStorage`; `shake-ui.js` runs in `<head>` and sets `html.shake-rail-pinned` before first paint, which keeps the rail open and reserves 252px. Below `992px` the rail is a slide-over drawer (top-bar toggle, backdrop, Escape to close). Sign Out is the `POST` logout form inside the rail.
- **`static/js/shake-ui.js`:** progressive enhancement only; every link and form works without it, and the server still enforces `POST`, CSRF, and ownership. Hooks are data attributes: `data-shake-rail` / `data-shake-pin` / `data-shake-drawer-open|close`, `form[data-confirm]`, `data-shake-copy` (1.5 s Tide `Copied` state; Clipboard API with `execCommand` fallback), `data-shake-search-shortcut` (`/` focuses the field unless the user is typing), `data-shake-ledger` (client-side filtering of already-rendered rows: `data-filter-row` + `data-search`, `data-shake-filter-select="<attr>"`, `data-shake-pill="<attr>"`, live `data-shake-visible-count`), and `data-shake-upload` (drag-and-drop, selected-file cards rendered with `textContent`, per-file removal via `DataTransfer`, step highlight). It makes no network requests and never changes form field names.
- The contract list's server-side `q` / `status` `GET` filters are unchanged; the rate-ledger and carrier-directory filters work only on rows already on the page.

## Local Loopback REST API (`F-11`)

- Routes (`contracts/api_urls.py`, no trailing slash; trailing-slash aliases accepted): `POST /api/v1/ingest` (`api_contract_ingest`) and `GET /api/v1/contracts/<int:pk>` (`api_contract_detail`).
- Every request passes `LoopbackAPIView.dispatch` (`contracts/api_views.py`) in this order:
  1. **Loopback guard:** `REMOTE_ADDR` must be in `SHAKE_API_LOOPBACK_ADDRESSES` (`127.0.0.1`, `::1`; `testserver` only when `DEBUG` or under `manage.py test`), else `403`. This holds even when `runserver` is bound to `0.0.0.0`; `X-Forwarded-For` is ignored.
  2. **Authentication:** `Authorization: Bearer <key>` for an active `APIToken` of an active user (updates `last_used_at`), else an authenticated session. A present header is authoritative (a bad token is `401` even with a valid session). Failure is `401` JSON with `WWW-Authenticate: Bearer`, never a login redirect.
  3. **CSRF:** views are `csrf_exempt`; Bearer requests skip CSRF, session-authenticated unsafe requests are re-checked with Django's `CsrfViewMiddleware` logic (`403` JSON on failure).
  4. Method dispatch; unsupported methods return `405` JSON with an `Allow` header.
- `POST /api/v1/ingest` takes exactly one PDF in multipart field `file` and calls `ingest_uploaded_files(user=request.user, ...)`; `BatchIngestionOutcome.rejected_errors` maps `DuplicateDocumentError` to `409` (`BR-06`) and other validation errors to `400` (`BR-07`, `BR-08`). Extraction failures after validation return `422` and leave a `FAILED` document, as in the web UI. Success is `201` with `contract_id`, `batch_id`, `document_id`, `contract_number`, `status`, `rates_count`, `arbitraries_count`, and `detail_url`.
- `GET /api/v1/contracts/<pk>` scopes with `scope_contracts_to_user` (`404` outside scope; archived contracts stay readable, `BR-09`) and returns `build_contract_api_payload()` (`contracts/services/exporter.py`), whose `canonical` block is `build_canonical_payload()` from `contracts/engine/exporter.py`, the same structure the `F-09` JSON export writes.

## Offline Extraction & Export Pipeline

### Ingestion & Vector Extraction (`contracts/engine/ingestion.py`, `extraction.py`)

- Input: Uploaded `.pdf` file stream and filename.
- Execution: Validates `.pdf` header, positive byte size, and selectable vector text density (`BR-07`, `BR-08`), then parses vector coordinates via local OpenDataLoader Java AST with automatic PyMuPDF fallback (`F-04`).
- Output: Structured raw pages, stitched cross-page tables (with repeated headers pruned), and diagnostic metadata.
- PyMuPDF fallback AST (`contracts/services/pipeline.py` `_build_pymupdf_fallback_document`): emits text lines and tables in top-to-bottom reading order per page, excludes text inside detected tables, rebuilds cell text from positioned words, and records per-cell `bounding box` coordinates so it has the same shape as the OpenDataLoader AST.

### Cross-Page Table Stitching (`F-04`, `contracts/engine/extraction.py`)

- The leading table on page `P+1` continues the trailing table on page `P` only when: the section is unchanged, no recognized context line (scope, commodity, origin/via, section heading, validity dates) appears between them, the column count matches, and the horizontal column boundaries align (tolerance `max(4pt, 2%` of table width`)`; skipped when either side lacks cell coordinates).
- Header decision: a first row whose normalized signature equals the trailing header is a repeated header and is pruned; a header-like first row with a different signature (for example `Point | Via` vs. `Destination | Destination Via`) starts a distinct table; a data first row is a header-less continuation.
- Page furniture (`Page N of M`, `Confidential ...`, and short non-context lines repeated on two or more pages) is ignored as context and dropped from table bodies.
- An orphan continuation row (empty first/identifier column) at the top of page `P+1` is merged into the last row of page `P`.
- Each extracted table carries `source_page_start`/`source_page_end`, and each row carries its own span in `row_page_spans`; `mapping.py` copies the row span onto every mapped row, and `pipeline.py` persists it to `FreightRate.source_page_start`/`source_page_end` (`ArbitraryCharge.source_page_num` stores the start page).

### Canonical Mapping & Atomic Persistence (`contracts/engine/mapping.py`, `contracts/services/pipeline.py`)

- Input: Extracted text/tables and `BatchUpload` context.
- Execution: Computes SHA-256 hash (`BR-06`), extracts global contract headers (`F-05`), normalizes UN/LOCODE port pairs, ISO container codes, currencies, base rates (`F-06`), and arbitrary charges (`F-07`), and persists all records inside `transaction.atomic()`.
- Output: Saved `DocumentFile`, `ProcessingJob`, `ContractMetadata`, `FreightRate`, and `ArbitraryCharge` rows.

### Canonical Export & Audit (`contracts/engine/exporter.py`, `contracts/services/exporter.py`)

- Input: `ContractMetadata` instance and requested format (`json`, `xlsx`, `csv`).
- Execution: For `json`/`xlsx`, reconstructs a canonical `MappingResult` from database rows and renders it with `export_result()`. For `csv`, flattens every `FreightRate` and `ArbitraryCharge` row into one unified file through `write_csv_export()`, with a `record_type` discriminator (`FREIGHT_RATE` / `ARBITRARY_CHARGE`) and the shared `COLUMNS_CSV_EXPORT` header. Every format then writes an `ExportRecord` audit row (`F-09`, `F-10`).
- Output: Downloadable file response and persisted audit entry.

## Invariants

1. **Zero Cloud Egress:** All PDF parsing, table stitching, database storage, and exports run 100% locally; never invoke external cloud OCR or third-party LLM APIs. The UI is offline too: CSS, JS, icon fonts, the bundled WOFF2 text fonts, and brand images load only from `static/` (no CDN `<link>`/`<script>` tags, no Google Fonts, no remote fonts).
2. **Identity & Role Integrity (`BR-01`, `BR-02`):** Unique email addresses and strict role enforcement (`ADMIN`, `ENCODER`) across web views and API endpoints.
3. **Unique Carrier Definitions (`BR-03`):** `carrier_code` and `carrier_name` must remain unique at both form validation and database constraint levels.
4. **Batch & Document Integrity (`BR-04`–`BR-08`):** Batch file counts `>= 1`, positive `file_size_bytes` and `page_count`, strict lifecycle status states, and SHA-256 duplicate rejection.
5. **Non-Destructive Archiving (`BR-09`):** `ContractMetadata.document` and `ExportRecord.contract` use `ON DELETE RESTRICT`. Documents that have produced `ContractMetadata` must never be hard-deleted; they transition to `DocumentFile.Status.ARCHIVED`.
6. **Contract & Rate Validity (`BR-10`–`BR-13`):** `expiration_date >= effective_date`, mandatory `CarrierProfile` FK (`ON DELETE RESTRICT`), `rate_amount > 0`, distinct origin/destination UN/LOCODE ports, and valid ISO equipment codes (`20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, `SPECIAL`).
7. **Secure Defaults:** `DEBUG` is `False` unless explicitly enabled, `SECRET_KEY` never lives in source, and error pages never expose stack traces or exception text.
8. **Immutable Applied Migrations:** Already-applied migrations (`accounts/migrations/0001_initial.py`, `contracts/migrations/0001_initial.py`, `contracts/migrations/0002_seed_default_carriers.py`) must never be altered or deleted.
