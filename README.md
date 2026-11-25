# SHAKE — Structured Handling and Automated Knowledge Extraction

**From Paper to Data:** An offline-first logistics automation web platform designed to convert unstructured ocean freight contract PDFs from shipping carriers (**MSC, CMA CGM, COSCO**, etc.) into structured, machine-readable **Excel (`.xlsx`), CSV (`.csv`), and JSON AST (`.json`)** data.

---

## Student & Course Information

| Field | Details |
|---|---|
| **Student** | Adrian James F. Bona |
| **Course & Section** | CSIT327 (Information Management 2) — Section G1 |
| **Phase** | Phase 2 — Core Feature Vertical Slice (PDF Ingestion, Extraction, CRUD & Exports) |
| **Tech Stack** | Full Stack Django (Django Backend + Django Templates + Bootstrap 5.3 CDN), PyMuPDF / OpenDataLoader / pandas / openpyxl, & SQLite (default) / PostgreSQL (optional via `DATABASE_URL`) |

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

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

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

7. **Run the automated test suite (SQLite)**
   ```bash
   python manage.py test -v 2
   ```

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
   python manage.py test --keepdb -v 2
   ```

> **Tip:** Even when `.env` defines `DATABASE_URL`, you can temporarily force SQLite in bash (`DATABASE_URL="" python manage.py test -v 2`) or PowerShell (`$env:DATABASE_URL=" "; python manage.py test -v 2`).

---

## GitFlow Branching Workflow

SHAKE follows a protected **GitFlow** workflow across Project Development 2:

- **`main`**: Production-ready stable code only (no direct commits).
- **`develop`**: Integration branch created from `main`.
- **`feature/contract-ingestion-engine`**: Feature Branch 1 implementing the `contracts` app, normalized PostgreSQL schema (`BR-03`–`BR-13`), ported offline extraction engine, and upload/list/inspection views -> merged into `develop` (PR #1).
- **`feature/contract-crud-and-exports`**: Feature Branch 2 implementing contract/rate CRUD, non-destructive archiving (`BR-09`), canonical JSON/XLSX/CSV exports + `ExportRecord`, Admin `CarrierProfile` CRUD, and live role dashboards -> merged into `develop` (PR #2), followed by `develop` -> `main` (PR #3).
- All merged feature branches are preserved in the repository history.
