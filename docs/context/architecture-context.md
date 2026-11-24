# Architecture Context

## Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Framework | Django (Python 3.x) | Server-rendered full-stack web application, ORM, and REST endpoints |
| UI | Bootstrap 5 + Django Templates | Responsive local workspace, forms, and interactive inspection tables |
| Auth | Custom Django Auth (`accounts.CustomUser`) | Email-based login, role assignment (`ADMIN`, `ENCODER`), and session/token guards |
| Database | PostgreSQL (`DATABASE_URL`) / SQLite (`db.sqlite3`) | Normalized 3NF persistence with native `UNIQUE`, `CHECK`, and `FK` constraints |
| PDF Engine | PyMuPDF (`fitz`) + OpenDataLoader Java AST | 100% offline vector text/coordinate extraction and cross-page table stitching |
| Exporters | Python `json`, `csv`, and `openpyxl` | Deterministic canonical `JSON`, multi-sheet `.xlsx`, and `CSV` artifact generation |
| File Storage | Local Filesystem (`media/`) | Local storage for uploaded contract PDFs and exported datasets |

## System Boundaries

- `shake/` — Core project configuration (`settings.py` with dual SQLite/PostgreSQL database resolution) and root URL routing (`urls.py`).
- `accounts/` — Custom user model (`CustomUser`), case-insensitive email authentication backend (`accounts/backends.py` `EmailBackend`), authentication views, self-only profile management and password change (`/accounts/password/`), and the shared `BootstrapFormMixin` (`accounts/forms.py`).
- `dashboard/` — Role guards (`RoleRequiredMixin` and `@role_required` in `dashboard/views.py`) and role-aware workspace dashboards (`/dashboard/encoder/`, `/dashboard/admin/`) aggregating live database KPIs, recent batches, processing jobs, and export logs.
- `contracts/` — Primary domain application containing models, forms, views, URL routes, services, and the offline extraction engine:
  - `contracts/engine/` — Pure offline document processing modules (`ingestion.py`, `extraction.py`, `mapping.py`, `exporter.py`, `models.py`, `errors.py`) decoupled from HTTP request/response objects.
  - `contracts/services/` — Transactional ORM pipeline orchestration (`pipeline.py`) and export artifact + `ExportRecord` audit logging (`exporter.py`).
- `templates/` — Bootstrap 5 HTML templates (`base.html`, `accounts/`, `contracts/`, `dashboard/`, `includes/`).
- `media/` — Runtime directory for local uploaded PDFs and exported files (git-ignored).

## Storage Model

- **Relational Database (9 Normalized Entities):**
  - `accounts_customuser` (SDD `app_users`): Registered operators (`ENCODER`) and administrators (`ADMIN`).
  - `carrier_profiles`: Master carrier definitions (`carrier_code`, `carrier_name`, `template_version`, `is_active`).
  - `batch_uploads`: Logical batch grouping (`batch_number`, `total_files`, `status`, `user` FK as uploader).
  - `document_files`: Physical PDF metadata (`original_file_name`, `file_hash_sha256`, `file_size_bytes`, `page_count`, `status`).
  - `processing_jobs`: Execution diagnostics (`job_type`, `status`, `error_message`, `started_at`, `completed_at`).
  - `contract_metadata`: Context-aware parent contract record (`contract_number`, `trade_scope`, `commodity_desc`, `effective_date`, `expiration_date`, 1:1 with `DocumentFile`, M:1 with `CarrierProfile`).
  - `freight_rates`: Line-item base ocean freight rates (`origin_port_code`, `destination_port_code`, `equipment_type`, `currency_code`, `rate_amount`, `source_page_start`, `source_page_end`, `confidence_score`).
  - `arbitrary_charges`: Origin/destination inland surcharges (`charge_type`, `location_code`, `via_gateway_port`, `equipment_type`, `currency_code`, `charge_amount`, `transport_mode`).
  - `export_records`: Immutable export audit history (`user_id`, `contract_id`, `export_format`, `file_path`, `exported_at`).
- **Local Artifact Storage:** Uploaded PDFs and generated export files reside on the local filesystem under `media/`, with relative paths stored in `DocumentFile.uploaded_file` and `ExportRecord.file_path`.

## Auth and Access Control Model

- Every user authenticates via unique email (`CustomUser`) with role `ENCODER` (SDD `OPERATOR`) or `ADMIN`. The public login form (`CustomLoginForm`) accepts email only; `EmailBackend` matches it case-insensitively and falls back to username lookups only for the Django admin site.
- Emails are stored trimmed and lowercased (`CustomUser.save()`), and the database enforces `UNIQUE (email)` and `CHECK (role IN ('ADMIN', 'ENCODER'))` via `accounts/migrations/0002_user_constraints.py`.
- Public registration (`CustomUserCreationForm`) exposes no role selector and always assigns `ENCODER` server-side; `ADMIN` accounts are provisioned only through the Django admin or `createsuperuser`.
- All authenticated routes enforce `LoginRequiredMixin`.
- `ContractOwnershipMixin` enforces data isolation across all contract, rate, document, and export endpoints: `ENCODER` users can read or mutate **only** records linked to batches they uploaded; `ADMIN` users can inspect and manage all records across the system.
- Administrative management views (`/contracts/carriers/*`, `/dashboard/admin/`) require `RoleRequiredMixin(allowed_roles=[CustomUser.Role.ADMIN])`.
- Local Loopback REST API endpoints (`/api/v1/ingest`, `/api/v1/contracts/{id}`) bind strictly to localhost (`127.0.0.1`) and verify authentication credentials + ownership rules before executing ingestion or returning JSON data.

## Offline Extraction & Export Pipeline

### Ingestion & Vector Extraction (`contracts/engine/ingestion.py`, `extraction.py`)

- Input: Uploaded `.pdf` file stream and filename.
- Execution: Validates `.pdf` header, positive byte size, and selectable vector text density (`BR-07`, `BR-08`), then parses vector coordinates via local OpenDataLoader Java AST with automatic PyMuPDF fallback (`F-04`).
- Output: Structured raw pages, stitched cross-page tables (with repeated headers pruned), and diagnostic metadata.

### Canonical Mapping & Atomic Persistence (`contracts/engine/mapping.py`, `contracts/services/pipeline.py`)

- Input: Extracted text/tables and `BatchUpload` context.
- Execution: Computes SHA-256 hash (`BR-06`), extracts global contract headers (`F-05`), normalizes UN/LOCODE port pairs, ISO container codes, currencies, base rates (`F-06`), and arbitrary charges (`F-07`), and persists all records inside `transaction.atomic()`.
- Output: Saved `DocumentFile`, `ProcessingJob`, `ContractMetadata`, `FreightRate`, and `ArbitraryCharge` rows.

### Canonical Export & Audit (`contracts/engine/exporter.py`, `contracts/services/exporter.py`)

- Input: `ContractMetadata` instance and requested format (`json`, `xlsx`, `csv`).
- Execution: Reconstructs canonical `MappingResult` from database rows, renders the output file, and writes an `ExportRecord` audit row (`F-09`, `F-10`).
- Output: Downloadable file response and persisted audit entry.

## Invariants

1. **Zero Cloud Egress:** All PDF parsing, table stitching, database storage, and exports run 100% locally; never invoke external cloud OCR or third-party LLM APIs.
2. **Identity & Role Integrity (`BR-01`, `BR-02`):** Unique email addresses and strict role enforcement (`ADMIN`, `ENCODER`) across web views and API endpoints.
3. **Unique Carrier Definitions (`BR-03`):** `carrier_code` and `carrier_name` must remain unique at both form validation and database constraint levels.
4. **Batch & Document Integrity (`BR-04`–`BR-08`):** Batch file counts `>= 1`, positive `file_size_bytes` and `page_count`, strict lifecycle status states, and SHA-256 duplicate rejection.
5. **Non-Destructive Archiving (`BR-09`):** `ContractMetadata.document` uses `ON DELETE RESTRICT`. Documents that have produced `ContractMetadata` must never be hard-deleted; they transition to `DocumentFile.Status.ARCHIVED`.
6. **Contract & Rate Validity (`BR-10`–`BR-13`):** `expiration_date >= effective_date`, mandatory `CarrierProfile` FK (`ON DELETE RESTRICT`), `rate_amount > 0`, distinct origin/destination UN/LOCODE ports, and valid ISO equipment codes (`20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, `SPECIAL`).
7. **Immutable Applied Migrations:** Already-applied migrations (`accounts/migrations/0001_initial.py`, `contracts/migrations/0001_initial.py`, `contracts/migrations/0002_seed_default_carriers.py`) must never be altered or deleted.
