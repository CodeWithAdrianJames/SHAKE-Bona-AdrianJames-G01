# SHAKE — Structured Handling and Automated Knowledge Extraction

**From Paper to Data:** An offline-first logistics automation web platform designed to convert unstructured ocean freight contract PDFs from shipping carriers (**MSC, CMA CGM, COSCO**, etc.) into structured, machine-readable **Excel (`.xlsx`), CSV (`.csv`), and JSON AST (`.json`)** data.

---

## Student & Course Information

| Field | Details |
|---|---|
| **Student** | Adrian James F. Bona |
| **Course & Section** | CSIT327 (Information Management 2) — Section G1 |
| **Phase** | Phase 1 — Project Setup & Account Feature (Stages 1–4 Complete) |
| **Tech Stack** | Full Stack Django (Django Backend + Django Templates + Bootstrap 5.3 CDN) & PostgreSQL (Neon / Supabase / Local) |

---

## Implemented Account Feature Modules

### 1. Custom User Model & PostgreSQL Foundation (`accounts.CustomUser`)
- Extends `AbstractUser` with role-based access control (`Role.ADMIN` = **Operations Admin**, `Role.ENCODER` = **Freight Analyst / Encoder**), `department`, `contact_number`, and `profile_photo` (`ImageField` with automatic initials avatar fallback).
- Custom `CustomUserManager` ensures superusers created via `createsuperuser` automatically receive the `ADMIN` role.
- Strict PostgreSQL-only database configuration (`dj-database-url` + `psycopg[binary]`) driven via `.env` variables (supports Neon, Supabase, or local PostgreSQL instances).

### 2. User Registration, Login & CSRF-Protected Logout (`accounts`)
- **Account Registration (`/accounts/register/`, `/accounts/signup/`)**: `CustomUserCreationForm` (with `BootstrapFormMixin`) enforces required fields (`first_name`, `last_name`, `username`, `email`), valid email format, case-insensitive username & email uniqueness, and PBKDF2 password hashing before redirecting to `/accounts/login/` with a Bootstrap success alert.
- **Role-Aware Login (`/accounts/login/`)**: `CustomLoginView` authenticates credentials via `BootstrapAuthenticationForm`, displays clear validation errors on invalid login attempts, and routes users directly to their role-specific workspace.
- **POST-Only Logout (`/accounts/logout/`)**: `CustomLogoutView` restricts logout to `POST` requests with `{% csrf_token %}` to prevent CSRF-based forced logouts.

### 3. Role-Based Dashboards & Access Control (`dashboard`)
- **Reusable Access Guards**: `RoleRequiredMixin` (for CBVs) and `@role_required` (for FBVs) enforce both authentication (`LoginRequiredMixin`) and strict role matching. Cross-role URL tampering queues an `"Unauthorized access"` Bootstrap danger alert and redirects the user to their permitted dashboard.
- **Operations Admin Dashboard (`/dashboard/admin/`)**: Displays live PostgreSQL user metrics (`Total Users`, `Operations Admins`, `Freight Encoders`, `Active Carrier Parsers`), the registered user roster table, deterministic carrier AST parser profiles (**MSC**, **CMA CGM**, **COSCO**), and Offline OpenDataLoader AST Engine health status.
- **Freight Analyst / Encoder Dashboard (`/dashboard/encoder/`)**: Features the interactive Ocean Freight Contract PDF drag-and-drop upload workspace, carrier template & output bundle selectors, recent extraction jobs queue, and standardized `.xlsx` / `.csv` / `.json` output schema cards.

### 4. Self-Only User Profile View & Update (`accounts`)
- **Profile Detail View (`/accounts/profile/`)**: `ProfileDetailView` displays the authenticated user's uploaded `profile_photo` (or initials badge fallback), full name, username, work email, role badge, operational department, contact number, and member-since date.
- **Profile Update View (`/accounts/profile/edit/`)**: `ProfileUpdateView` and `UserProfileUpdateForm` allow users to update `first_name`, `last_name`, `email`, `contact_number`, `department`, and upload a `profile_photo` (`enctype="multipart/form-data"`), validating case-insensitive email uniqueness while excluding the current user (`exclude(pk=self.instance.pk)`).
- **IDOR Prevention**: Profile URLs never expose user IDs or usernames; `get_object()` resolves strictly from `self.request.user`.

---

## Application Route Map

| Route | URL Name | Access Policy | Description |
|---|---|---|---|
| `/` or `/dashboard/` | `dashboard_root` / `dashboard` | Authenticated | Role-aware entry redirect to Admin or Encoder dashboard |
| `/dashboard/admin/` | `admin_dashboard` | `Role.ADMIN` only | Operations Admin Control Center |
| `/dashboard/encoder/` | `encoder_dashboard` | `Role.ENCODER` only | Freight Analyst & Contract Encoder Workspace |
| `/accounts/register/` | `register` (`signup`) | Public | New SHAKE account registration |
| `/accounts/login/` | `login` | Public | User sign-in with role-based redirect |
| `/accounts/logout/` | `logout` | Authenticated (`POST`) | CSRF-protected session termination |
| `/accounts/profile/` | `profile` | Authenticated (Self-only) | Logged-in user's profile detail page |
| `/accounts/profile/edit/` | `profile_edit` | Authenticated (Self-only) | Logged-in user's profile & avatar update form |

---

## Local Setup Instructions (PostgreSQL / Neon / Supabase)

1. **Create and activate a virtual environment**
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

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment variables (`.env`)**
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Configure either a single PostgreSQL connection string (`DATABASE_URL` — recommended for **Neon** or **Supabase**) or individual `DB_*` variables in `.env`:
   ```ini
   SECRET_KEY=replace-with-a-secure-django-secret-key
   DEBUG=True
   ALLOWED_HOSTS=127.0.0.1,localhost

   # Option A: Neon / Supabase / PostgreSQL URI
   DATABASE_URL=postgresql://user:password@ep-example.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   DB_SSL_REQUIRE=True

   # Option B: Individual PostgreSQL Variables (used when DATABASE_URL is blank)
   DB_NAME=postgres
   DB_USER=postgres
   DB_PASSWORD=your_password
   DB_HOST=localhost
   DB_PORT=5432
   DB_SSLMODE=prefer
   ```

4. **Apply database migrations & start the development server**
   ```bash
   python manage.py migrate
   python manage.py runserver
   ```

5. **Run the automated test suite**
   ```bash
   python manage.py test
   ```
