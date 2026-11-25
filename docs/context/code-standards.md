# Code Standards

## General

- Keep modules small, deterministic, and single-purpose.
- Fix root causes — do not layer workarounds or swallow exceptions silently.
- Keep pure PDF parsing/mapping/export logic inside `contracts/engine/` decoupled from Django HTTP request/response handling.
- Respect the system boundaries and invariants defined in `architecture-context.md`.

## Python and Django

- Execute all Python and Django commands through the project virtual environment: `.\.venv\Scripts\python.exe manage.py ...`.
- Protect all authenticated web views with `LoginRequiredMixin`.
- Enforce resource ownership on every contract, rate, document, and export view via `ContractOwnershipMixin` (`ENCODER` scoped to own `BatchUpload.user`; `ADMIN` unrestricted) to prevent Insecure Direct Object Reference (IDOR).
- Enforce administrative routes (`/contracts/carriers/*`, `/dashboard/admin/`) with `RoleRequiredMixin(allowed_roles=[CustomUser.Role.ADMIN])`.
- Keep state-mutating actions without dedicated confirmation pages (`rate_delete`, `document_delete`, `contract_archive`, `carrier_toggle`) strictly `POST`-only (`http_method_names = ["post"]` or `@require_POST`) with CSRF protection.

## Forms and Validation

- Every Django `Form` and `ModelForm` must inherit `BootstrapFormMixin` so fields automatically render Bootstrap 5 styling and `is-invalid` error feedback.
- Normalize string codes (`carrier_code`, `origin_port_code`, `destination_port_code`, `currency_code`, `equipment_type`) to stripped uppercase inside form `clean_*` methods.
- Never let public or self-service forms set privileged fields (`role`, `is_staff`, `is_superuser`, `is_active`); assign `role` server-side (`ENCODER` for public registration).
- Enforce critical business rules (`BR-01`–`BR-13`) at both the Django form layer (clear user-facing validation errors) and database constraint layer (`UniqueConstraint`, `CheckConstraint`, `ForeignKey(on_delete=...)`).

## Templates and Styling

- Render forms through `templates/includes/form_fields.html` so label, help text, checkbox, and validation error markup stay uniform.
- Format contract numbers, UN/LOCODE port codes, SHA-256 hashes, and monetary amounts using `font-monospace` (and `text-end` for numeric columns).
- Keep templates self-contained and offline-safe without external runtime dependencies that fail without internet access.

## API Routes (Loopback REST API — F-11)

- Expose local programmatic endpoints under `/api/v1/` (`ingest`, `contracts/<int:pk>`, no trailing slash) intended strictly for localhost loopback use; subclass `LoopbackAPIView` (`contracts/api_views.py`) so the loopback guard, authentication, CSRF rule, and JSON `405` apply uniformly.
- Validate authentication credentials and enforce ownership through `scope_contracts_to_user()` (the helper behind `ContractOwnershipMixin`) before processing uploads or returning contract JSON payloads.
- Validate uploaded PDFs through the exact same ingestion/deduplication pipeline (`BR-06`–`BR-08`) used by the web UI.
- Return consistent, predictable JSON response structures with explicit HTTP status codes (`200`, `201`, `400`, `401`, `403`, `404`, `405`, `409`, `422`); errors always carry a `detail` field.

## Data and Storage

- Wrap multi-table ingestion (`BatchUpload`, `DocumentFile`, `ProcessingJob`, `ContractMetadata`, `FreightRate`, `ArbitraryCharge`) in `transaction.atomic()`.
- Never edit or delete already-applied migration files (`accounts/migrations/0001_initial.py`, `contracts/migrations/0001_initial.py`, `contracts/migrations/0002_seed_default_carriers.py`).
- Maintain full compatibility across both default SQLite (`db.sqlite3` when `DATABASE_URL` is unset) and PostgreSQL (`DATABASE_URL` configured in `.env`).

## File Organization & GitFlow

- `accounts/` — custom user model, authentication, profile views, and `BootstrapFormMixin`.
- `contracts/` — domain models, forms, views, URLs, `engine/` (pure parsing/mapping/export), and `services/` (atomic pipeline & export audit).
- `dashboard/` — role guards (`RoleRequiredMixin`, `@role_required`) and role-based metrics and monitoring dashboards.
- `templates/` — Bootstrap 5 HTML templates grouped by application.
- Follow GitFlow strictly: work on `feature/*` branches, merge into `develop` via PR, and release `develop` -> `main` via PR. Never commit directly to `main`, never delete feature branches after merging, and never include AI agent names or co-author trailers in commit messages.
