# SHAKE — Structured Handling and Automated Knowledge Extraction

**From Paper to Data:** An offline-first logistics automation web platform designed to convert unstructured ocean freight contract PDFs from shipping carriers (**MSC, CMA CGM, COSCO**, etc.) into structured, machine-readable **Excel (`.xlsx`), CSV (`.csv`), and JSON AST (`.json`)** data.

---

## Student & Course Information

| Field | Details |
|---|---|
| **Student** | Adrian James F. Bona |
| **Course & Section** | CSIT327 (Information Management 2) — Section G1 |
| **Phase** | Project Development 3 — Loopback REST API (`F-11`), Validation/Error-Page/Security Hardening & Final Documentation |
| **Tech Stack** | Full Stack Django (Django Backend + Django Templates + Bootstrap 5.3 CDN), PyMuPDF / OpenDataLoader / pandas / openpyxl, & SQLite (default) / PostgreSQL (optional via `DATABASE_URL`) |

---

## Project Documentation

| Document | Description |
|---|---|
| [`docs/traceability-matrix.md`](docs/traceability-matrix.md) | End-to-end traceability: `F-01`–`F-11` → specs, modules, routes, migrations & test classes; `BR-01`–`BR-13` → enforcement layer & tests; PD3 hardening → files & tests |
| [`docs/SHAKE-Bona-AdrianJames-G01-PD3.pdf`](docs/SHAKE-Bona-AdrianJames-G01-PD3.pdf) | Project Development 3 report |
| [`docs/SHAKE-Bona-AdrianJames-G1-PD2.pdf`](docs/SHAKE-Bona-AdrianJames-G1-PD2.pdf) | Project Development 2 report (incl. outstanding issues `ISS-01`, `ISS-02`) |
| [`docs/feature-specs/`](docs/feature-specs/) | Spec-driven feature specifications `01`–`11` |
| [`docs/context/`](docs/context/) | Project overview, architecture, UI, code standards, workflow rules & progress tracker |

---

## Implemented Account Feature Modules

### 1. Custom User Model & Dual Database Foundation (`accounts.CustomUser`)
- Extends `AbstractUser` with role-based access control (`Role.ADMIN` = **Operations Admin**, `Role.ENCODER` = **Freight Analyst / Encoder**), `department`, `contact_number`, and `profile_photo` (`ImageField` with automatic initials avatar fallback).
- Custom `CustomUserManager` ensures superusers created via `createsuperuser` automatically receive the `ADMIN` role.
- Dual-database configuration in `shake/settings.py`: defaults cleanly to local SQLite (`db.sqlite3`) when `DATABASE_URL` is unset or empty, and switches to PostgreSQL (`dj-database-url` + `psycopg[binary]`) whenever `DATABASE_URL` is provided in `.env` or the environment.

### 2. User Registration, Login & CSRF-Protected Logout (`accounts`)
- **Account Registration (`/accounts/register/`, `/accounts/signup/`)**: `CustomUserCreationForm` (with `BootstrapFormMixin`) enforces required fields (`first_name`, `last_name`, `username`, `email`), valid email format, case-insensitive username & email uniqueness, and PBKDF2 password hashing before redirecting to `/accounts/login/` with a Bootstrap success alert.
- **Role-Aware Login (`/accounts/login/`)**: `CustomLoginView` authenticates credentials via `BootstrapAuthenticationForm`, displays clear validation errors on invalid login attempts, and routes users directly to their role-specific workspace.
- **POST-Only Logout (`/accounts/logout/`)**: `CustomLogoutView` restricts logout to `POST` requests with `{% csrf_token %}` to prevent CSRF-based forced logouts.

### 3. Live Role-Based Dashboards & Access Control (`dashboard`)
- **Reusable Access Guards**: `RoleRequiredMixin` (for CBVs) and `@role_required` (for FBVs) enforce both authentication (`LoginRequiredMixin`) and strict role matching. Cross-role URL tampering queues an `"Unauthorized access"` Bootstrap danger alert and redirects the user to their permitted dashboard.
- **Operations Admin Dashboard (`/dashboard/admin/`)**: Displays live PostgreSQL system metrics (`Total Users`, `Total Batches`, `Extracted Contracts`, `Total Rate Rows`, `Active Carriers`), the registered user roster table with batch counts, live `CarrierProfile` summary with quick management links, recent `ProcessingJob` and `ExportRecord` activity, and Offline OpenDataLoader AST Engine health status.
- **Freight Analyst / Encoder Dashboard (`/dashboard/encoder/`)**: Displays live personal KPIs (`My Batches`, `Extracted Contracts`, `Total Rate Rows`, `Exports Generated`), direct upload and contract management CTAs, recent extraction jobs with **Inspect** and **Export** actions, and standardized `.xlsx` / `.csv` / `.json` output schema cards.

### 4. Self-Only User Profile View & Update (`accounts`)
- **Profile Detail View (`/accounts/profile/`)**: `ProfileDetailView` displays the authenticated user's uploaded `profile_photo` (or initials badge fallback), full name, username, work email, role badge, operational department, contact number, and member-since date.
- **Profile Update View (`/accounts/profile/edit/`)**: `ProfileUpdateView` and `UserProfileUpdateForm` allow users to update `first_name`, `last_name`, `email`, `contact_number`, `department`, and upload a `profile_photo` (`enctype="multipart/form-data"`), validating case-insensitive email uniqueness while excluding the current user (`exclude(pk=self.instance.pk)`).
- **IDOR Prevention**: Profile URLs never expose user IDs or usernames; `get_object()` resolves strictly from `self.request.user`.

---

## Implemented Core Feature Modules (`contracts`)

### 1. Normalized 3NF Relational Schema (`contracts/models.py`)
Eight domain tables enforce business rules `BR-03` through `BR-13` via explicit `UNIQUE`, `CHECK`, and `FOREIGN KEY` (`ON DELETE RESTRICT` / `CASCADE`) constraints:
- `CarrierProfile` (`carrier_profiles`) — Seeded default shipping lines (`MSCU`, `CMDU`, `COSU`, `MAEU`, `UNKN`) with unique SCAC code and carrier name (`BR-03`).
- `BatchUpload` (`batch_uploads`) — Logical single/batch upload records owned by `request.user` (`BR-04`, `BR-05`).
- `DocumentFile` (`document_files`) — Physical PDFs tracked by unique 64-char `file_hash_sha256` (`BR-06`), positive size/page counts (`BR-08`), and lifecycle status (`BR-07`, `BR-09`).
- `ProcessingJob` (`processing_jobs`) — Execution audit trail for offline vector parsing and extraction runs.
- `ContractMetadata` (`contract_metadata`) — 1:1 extracted contract header linked to `DocumentFile` (`ON DELETE RESTRICT`, `BR-09`) and `CarrierProfile` (`ON DELETE RESTRICT`, `BR-11`), enforcing `expiration_date >= effective_date` (`BR-10`).
- `FreightRate` (`freight_rates`) — Normalized base ocean freight rows (`20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, `SPECIAL`) enforcing positive rates (`BR-12`) and distinct origin/destination ports (`BR-13`).
- `ArbitraryCharge` (`arbitrary_charges`) — Normalized origin/destination inland arbitrary surcharges (`RAIL`, `TRUCK`, `BARGE`, `FEEDER`, `INTERMODAL`).
- `ExportRecord` (`export_records`) — Audit log recording every JSON, XLSX, and CSV export download and triggering user.

### 2. Offline PDF Ingestion & Extraction Engine (`contracts/engine/`, `contracts/services/pipeline.py`)
- **Strict Offline Boundary**: Validates `.pdf` extension, non-zero byte size (`BR-08`), PyMuPDF selectable vector text (rejecting scanned/low-text PDFs), and SHA-256 uniqueness (`BR-06`) with zero external cloud OCR/LLM calls.
- **Deterministic Pipeline**: Runs `ingest_file()` (with graceful PyMuPDF fallback if Java runtime is absent) -> `extract()` -> `map_payload()` -> atomic unpivoting into PostgreSQL `ContractMetadata`, `FreightRate`, and `ArbitraryCharge` rows inside `transaction.atomic()`.

### 3. Contract & Freight Rate CRUD, Non-Destructive Archiving & Exports (`contracts/views.py`)
- **Ownership Isolation**: `ContractOwnershipMixin` restricts `ENCODER` users to their own uploaded batches/contracts (`404` on others' records), while `ADMIN` users can inspect and manage all contracts.
- **Metadata & Rate Management**: Edit contract metadata (`/contracts/<pk>/edit/`), add new base freight rate rows (`/contracts/<pk>/rates/add/` with auto-assigned `line_item_sequence = max + 1`), edit rates (`/contracts/<pk>/rates/<rate_id>/edit/`), and `POST`-delete individual rate rows.
- **Non-Destructive Archiving (`BR-09`)**: `DocumentFileDeleteView` allows `POST` hard deletion only for `PENDING`/`FAILED` documents without `ContractMetadata` and blocks deletion of `EXTRACTED` documents; `ContractArchiveView` transitions extracted contracts to `DocumentFile.status = 'ARCHIVED'`.
- **Canonical Multi-Format Exporter (`F-09`, `F-10`)**: `/contracts/<pk>/export/<fmt>/` (`json`, `xlsx`, `csv`) reconstructs `MappingResult` from PostgreSQL records, generates standardized files via `contracts.engine.exporter.export_result()` (`csv` uses `write_csv_export()` to emit freight rates and origin/destination arbitrary charges in one file, keyed by a `record_type` column), logs an `ExportRecord`, and streams the file attachment.
- **Admin Carrier Profile CRUD (`F-02`)**: `/contracts/carriers/*` views restricted strictly to `CustomUser.Role.ADMIN` via `RoleRequiredMixin`.

### 4. Local Loopback REST API (`F-11`, `contracts/api_views.py`)
- **Endpoints**: `POST /api/v1/ingest` (multipart PDF upload through the same offline pipeline as `/contracts/upload/`) and `GET /api/v1/contracts/<pk>` (contract JSON with metadata, normalized rates/arbitraries, and the canonical `F-09` export structure under `canonical`). Paths have no trailing slash; the trailing-slash form is accepted too.
- **Loopback only**: requests whose socket address (`REMOTE_ADDR`) is not `127.0.0.1` or `::1` get `403`, even with a valid token and even when `runserver` is bound to `0.0.0.0`. `X-Forwarded-For` is ignored.
- **Authentication**: `Authorization: Bearer <token>` using a per-user `APIToken` generated under **Local API Tokens** on `/accounts/profile/` (the raw token is shown once; revoke it there at any time). A signed-in browser session also works; session `POST`s must carry a CSRF token. Missing, malformed, or revoked credentials get `401` JSON.
- **Ownership**: `ENCODER` tokens see only contracts from their own uploads (including archived ones, `BR-09`); `ADMIN` tokens see all. Anything else is `404`.
- **Status codes**: `201` created, `400` invalid upload (missing `file`, non-PDF, empty, corrupt, scanned/image-only — `BR-07`, `BR-08`), `401`, `403`, `404`, `405`, `409` duplicate SHA-256 (`BR-06`), `422` valid PDF whose extraction failed (a `FAILED` document is recorded). All bodies are JSON with a `detail` field on errors.

#### `curl` examples

Generate a token on `/accounts/profile/`, then from the same machine (PowerShell: use `curl.exe`):

```bash
export SHAKE_TOKEN=<paste-your-64-char-token>

# Ingest one contract PDF (201 on success)
curl -X POST http://127.0.0.1:8000/api/v1/ingest \
  -H "Authorization: Bearer $SHAKE_TOKEN" \
  -F "file=@./maersk_tp_2026.pdf;type=application/pdf"
# {"contract_id": 15, "batch_id": 12, "batch_number": "BATCH-...", "document_id": 18,
#  "contract_number": "MAEU-TP-88412", "carrier_code": "MAEU", "status": "EXTRACTED",
#  "rates_count": 24, "arbitraries_count": 6, "detail_url": "/api/v1/contracts/15", ...}

# Uploading the same file again -> 409 {"detail": "Duplicate PDF blocked (BR-06): ...", "rule": "BR-06"}

# Fetch the contract JSON (200)
curl http://127.0.0.1:8000/api/v1/contracts/15 \
  -H "Authorization: Bearer $SHAKE_TOKEN"

# No token -> 401; another encoder's contract -> 404; called from another host -> 403
```

---

## Application Route Map

| Route | URL Name | Access Policy | Description |
|---|---|---|---|
| `/` or `/dashboard/` | `dashboard_root` / `dashboard` | Authenticated | Role-aware entry redirect to Admin or Encoder dashboard |
| `/dashboard/admin/` | `admin_dashboard` | `Role.ADMIN` only | Operations Admin live control center |
| `/dashboard/encoder/` | `encoder_dashboard` | `Role.ENCODER` only | Freight Analyst & Encoder live workspace |
| `/accounts/register/` | `register` (`signup`) | Public | New SHAKE account registration |
| `/accounts/login/` | `login` | Public | User sign-in with role-based redirect |
| `/accounts/logout/` | `logout` | Authenticated (`POST`) | CSRF-protected session termination |
| `/accounts/profile/` | `profile` | Authenticated (Self-only) | Logged-in user's profile detail page |
| `/accounts/profile/edit/` | `profile_edit` | Authenticated (Self-only) | Logged-in user's profile & avatar update form |
| `/accounts/profile/api-tokens/` | `api_token_create` | Authenticated (Self-only, `POST`) | Generate a local loopback API Bearer token (`F-11`) |
| `/accounts/profile/api-tokens/<pk>/revoke/` | `api_token_revoke` | Authenticated (own tokens, `POST`) | Revoke a local API token (`F-11`) |
| `/contracts/` | `contract_list` | `ENCODER` (own) / `ADMIN` (all) | Searchable, filterable contract & batch list |
| `/contracts/upload/` | `contract_upload` | `ENCODER`, `ADMIN` | Single or batch digital contract PDF upload |
| `/contracts/<pk>/` | `contract_detail` | `ENCODER` (own) / `ADMIN` (all) | Contract inspection grid, rates, arbitraries, jobs & export log |
| `/contracts/<pk>/edit/` | `contract_edit` | `ENCODER` (own) / `ADMIN` (all) | Update `ContractMetadata` (`BR-10`, `BR-11`) |
| `/contracts/<pk>/archive/` | `contract_archive` | `ENCODER` (own) / `ADMIN` (all) (`POST`) | Non-destructive archive (`status = 'ARCHIVED'`, `BR-09`) |
| `/contracts/<pk>/rates/add/` | `rate_create` | `ENCODER` (own) / `ADMIN` (all) | Add normalized `FreightRate` row (`BR-12`, `BR-13`) |
| `/contracts/<pk>/rates/<rate_id>/edit/` | `rate_edit` | `ENCODER` (own) / `ADMIN` (all) | Edit normalized `FreightRate` row |
| `/contracts/<pk>/rates/<rate_id>/delete/` | `rate_delete` | `ENCODER` (own) / `ADMIN` (all) (`POST`) | Delete individual `FreightRate` row |
| `/contracts/documents/<doc_id>/delete/` | `document_delete` | `ENCODER` (own) / `ADMIN` (all) (`POST`) | Delete unextracted `PENDING`/`FAILED` document (`BR-09`) |
| `/contracts/<pk>/export/<fmt>/` | `contract_export` | `ENCODER` (own) / `ADMIN` (all) | Download `json`, `xlsx`, or `csv` & log `ExportRecord` |
| `/contracts/carriers/` | `carrier_list` | `Role.ADMIN` only | List registered shipping carrier profiles |
| `/contracts/carriers/create/` | `carrier_create` | `Role.ADMIN` only | Create `CarrierProfile` (`BR-03`) |
| `/contracts/carriers/<pk>/edit/` | `carrier_edit` | `Role.ADMIN` only | Update `CarrierProfile` |
| `/contracts/carriers/<pk>/toggle/` | `carrier_toggle` | `Role.ADMIN` only (`POST`) | Activate or deactivate `CarrierProfile` |
| `/api/v1/ingest` | `api_contract_ingest` | Loopback + Bearer token / session (`POST`) | Ingest one contract PDF; JSON `201`/`400`/`409`/`422` (`F-11`) |
| `/api/v1/contracts/<pk>` | `api_contract_detail` | Loopback + Bearer token / session; `ENCODER` (own) / `ADMIN` (all) | Contract JSON incl. canonical `F-09` structure (`F-11`) |

---

## Quick Start (SQLite — Default)

Run SHAKE locally with zero external database setup (`db.sqlite3` is created automatically when `DATABASE_URL` is unset):

1. **Clone the repository and enter the project directory**
   ```bash
   git clone <repository-url>
   cd SHAKE-Bona-AdrianJames-G01
   ```

2. **Create and activate a virtual environment**
   - **Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - **WSL / Linux / macOS:**
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **Install dependencies and create `.env`**
   ```bash
   pip install -r requirements.txt
   cp .env.example .env
   ```
   `DEBUG` defaults to `False` when it is not set, and with `DEBUG=False` SHAKE refuses to start unless `SECRET_KEY` is set. For local development keep `DEBUG=True` from `.env.example` and replace `SECRET_KEY` with your own value (`python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"`). `.env` is git-ignored; never commit it.

4. **Apply database migrations (creates `db.sqlite3` and seeds default carriers)**
   ```bash
   python manage.py migrate
   ```

5. **Create test accounts (optional)**
   - Create an **Operations Admin** (`Role.ADMIN`) via `createsuperuser`:
     ```bash
     python manage.py createsuperuser
     ```
     *(Suggested evaluator credentials: username `admin`, email `admin@shake.local`)*
   - Register a **Freight Analyst / Encoder** (`Role.ENCODER`) directly in the web UI at `/accounts/register/` *(e.g., `encoder@shake.local`)*.

6. **Start the development server**
   ```bash
   python manage.py runserver
   ```
   Open `http://127.0.0.1:8000/` in your browser.

7. **Run the automated test suite** — see [Running the Automated Test Suite](#running-the-automated-test-suite) below.

---

## Running the Automated Test Suite

The suite has **218 tests, all passing on local SQLite** (0 skipped when Java is on `PATH`; otherwise the OpenDataLoader end-to-end test skips). Django's default `test*.py` pattern discovers every module:

| Module | Tests | Covers |
|---|---:|---|
| `accounts/tests.py` | 46 | Users, registration, email login, profile, password change, API tokens |
| `contracts/tests.py` | 66 | Schema constraints (`BR-03`–`BR-13`), ingestion, cross-page stitching, CRUD, archiving, exports, carrier admin, loopback API |
| `contracts/test_hardening.py` | 35 | Hardening pass: error pages, settings, access control, template audit, validation, integrity, query counts |
| `contracts/tests_pd3_hardening.py` | 62 | Dedicated PD3 verification suite: `PD3ErrorPageTests`, `PD3ServerSideValidationTests`, `PD3MessagesAndPRGTests`, `PD3AuthenticationGuardTests`, `PD3IDORIsolationTests`, `PD3RequestSafetyTests`, and the `PD1*` feature tests |
| `dashboard/tests.py` | 9 | Role dashboards, role guards, live metrics |

Test runs never need a real `SECRET_KEY`: `manage.py test` uses a random per-process key when none is set.

**PostgreSQL** (uses `DATABASE_URL` from `.env`):

```bash
python manage.py test
```

**Local SQLite** (Windows PowerShell; the blank `DATABASE_URL` overrides `.env` and forces `db.sqlite3`):

```powershell
$env:DATABASE_URL=" "; .\.venv\Scripts\python.exe manage.py test -v 2
```

Bash / WSL equivalent: `DATABASE_URL="" python manage.py test -v 2`.

**Run one module or one class:**

```powershell
$env:DATABASE_URL=" "; .\.venv\Scripts\python.exe manage.py test contracts.tests_pd3_hardening -v 2
$env:DATABASE_URL=" "; .\.venv\Scripts\python.exe manage.py test contracts.tests_pd3_hardening.PD3IDORIsolationTests -v 2
```

> **Note (PD2 `ISS-01`):** on Windows workstations where Smart App Control blocks psycopg's `pq` DLL, use the SQLite command above, WSL, or the `test-postgres` job in `.github/workflows/ci-cd.yml`.

See [`docs/traceability-matrix.md`](docs/traceability-matrix.md) for which test class verifies each feature, business rule, and hardening requirement.

---

## PostgreSQL Setup (Optional `.env`)

To run SHAKE against **Neon**, **Supabase**, or a local **PostgreSQL** instance instead of `db.sqlite3`:

1. **Copy `.env.example` to `.env`**
   ```bash
   cp .env.example .env
   ```

2. **Uncomment and set `DATABASE_URL` in `.env`**
   ```ini
   SECRET_KEY=replace-with-a-secure-django-secret-key
   DEBUG=True
   ALLOWED_HOSTS=127.0.0.1,localhost

   DATABASE_URL=postgresql://user:password@ep-example.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   DB_SSL_REQUIRE=True
   ```

3. **Apply migrations, start the server, and run tests against PostgreSQL**
   ```bash
   python manage.py migrate
   python manage.py runserver
   python manage.py test
   ```
   (Add `--keepdb -v 2` to reuse the test database between runs on a remote PostgreSQL host.)

> **Tip:** Even when `.env` defines `DATABASE_URL`, you can temporarily force SQLite in bash (`DATABASE_URL="" python manage.py test -v 2`) or PowerShell (`$env:DATABASE_URL=" "; python manage.py test -v 2`).

---

## GitFlow Branching Workflow

SHAKE follows a protected **GitFlow** workflow across Project Development 2:

- **`main`**: Production-ready stable code only (no direct commits).
- **`develop`**: Integration branch created from `main`.
- **`feature/contract-ingestion-engine`**: Feature Branch 1 implementing the `contracts` app, normalized PostgreSQL schema (`BR-03`–`BR-13`), ported offline extraction engine, and upload/list/inspection views -> merged into `develop` (PR #1).
- **`feature/contract-crud-and-exports`**: Feature Branch 2 implementing contract/rate CRUD, non-destructive archiving (`BR-09`), canonical JSON/XLSX/CSV exports + `ExportRecord`, Admin `CarrierProfile` CRUD, and live role dashboards -> merged into `develop` (PR #2), followed by `develop` -> `main` (PR #3).
- **Project Development 3** branches merged into `develop`: `feature/f01-auth-hardening`, `feature/f04-cross-page-stitching`, `feature/f09-csv-arbitrary-export`, `feature/f11-local-loopback-api`, `hardening/validation-errors-and-security`, and `test/pd3-hardening-verification`. `fix/pd3-docs-and-report` adds the traceability matrix and final PD3 documentation.
- All merged feature branches are preserved in the repository history.
