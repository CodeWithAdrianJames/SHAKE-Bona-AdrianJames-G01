# Progress Tracker

Update this file whenever the current phase, active feature, or implementation state changes.

## Current Phase

- **Project Development 2 (Core Feature Vertical Slice):** Completed and merged into `main`.
- **Project Development 3 (Loopback REST API `F-11` & SDD Polish):** Ready to begin — spec-driven context files are synced into the repository.

## Current Goal

- Begin PD3 with `F-11` (Lightweight Local Loopback REST API) once its authentication open question is resolved.

## Completed

- **PD1 — Authentication, RBAC & Base Dashboards (`F-01`, `BR-01`, `BR-02`):**
  - Implemented `accounts.CustomUser` with `ADMIN` and `ENCODER` roles, email login, registration, CSRF-safe `POST` logout, self-only profile management, and `RoleRequiredMixin`.
- **PD2 Slice 01 — Normalized Schema & Offline Vector Extraction Engine (`F-02`–`F-08`, `BR-03`–`BR-08`, `BR-11`):**
  - Implemented 8 normalized domain models in `contracts/models.py` (`CarrierProfile`, `BatchUpload`, `DocumentFile`, `ProcessingJob`, `ContractMetadata`, `FreightRate`, `ArbitraryCharge`, `ExportRecord`) plus initial migration `0001_initial.py` and carrier seed migration `0002_seed_default_carriers.py` (`CMDU`, `COSU`, `MAEU`, `MSCU`, `UNKN`).
  - Ported offline vector PDF ingestion, OpenDataLoader Java AST + PyMuPDF extraction, cross-page table stitching, canonical mapping, and SHA-256 duplicate prevention (`contracts/engine/*`, `contracts/services/pipeline.py`).
  - Implemented single/batch upload (`/contracts/upload/`), contract list (`/contracts/`), and contract detail inspection (`/contracts/<pk>/`) guarded by `ContractOwnershipMixin`.
- **PD2 Slice 02 — Contract/Rate CRUD, Non-Destructive Archiving, Multi-Format Exports, Carrier Admin & Live Dashboards (`F-02`, `F-08`–`F-10`, `BR-03`, `BR-09`–`BR-13`):**
  - Implemented `ContractMetadataUpdateView` (`/contracts/<pk>/edit/`), `FreightRateCreateView` (`/contracts/<pk>/rates/add/`), `FreightRateUpdateView` (`/contracts/<pk>/rates/<rate_id>/edit/`), and `POST`-only `FreightRateDeleteView`.
  - Implemented `POST`-only `DocumentFileDeleteView` (blocking deletion of extracted contracts) and `POST`-only `ContractArchiveView` (`/contracts/<pk>/archive/` setting `DocumentFile.status = 'ARCHIVED'`).
  - Implemented canonical `JSON`, multi-sheet `.xlsx`, and `CSV` exporters (`/contracts/<pk>/export/<fmt>/`) with persistent `ExportRecord` audit logging.
  - Implemented `RoleRequiredMixin(ADMIN)`-guarded `CarrierProfile` list/create/edit/toggle views (`/contracts/carriers/*`).
  - Wired live database metrics and activity tables into `/dashboard/encoder/`, `/dashboard/admin/`, and `templates/base.html`.
  - Configured automatic local SQLite (`db.sqlite3`) default fallback in `shake/settings.py` alongside optional PostgreSQL (`DATABASE_URL`).
- **Verification & Documentation:**
  - Verified 45/45 automated tests passing on PostgreSQL (44 passed, 1 external-fixture skipped on SQLite).
  - Re-verified 45 tests on SQLite (44 passed, 1 skipped) in a freshly created `.venv` during the context sync.
  - Merged `feature/contract-ingestion-engine` and `feature/contract-crud-and-exports` into `develop`, released `develop` -> `main`, and committed `docs/SHAKE-Bona-AdrianJames-G1-PD2.pdf` to `main`.
- **PD3 — F-01 Auth Hardening (`F-01`, `BR-01`, `BR-02`) on `feature/f01-auth-hardening`:**
  - Removed the role selector from public registration; `CustomUserCreationForm.save()` always assigns `ENCODER` (crafted `role=ADMIN` POSTs are ignored).
  - Replaced username login with case-insensitive email login (`CustomLoginForm` + `accounts/backends.py` `EmailBackend`, set as the sole `AUTHENTICATION_BACKENDS` entry with username fallback for the Django admin site).
  - Added self-service password change (`ProfilePasswordChangeView`, `/accounts/password/`, `templates/accounts/password_change.html`) linked from `templates/accounts/profile.html`.
  - Added `accounts/migrations/0002_user_constraints.py`: normalizes existing rows (trim/lowercase emails, replace blank/duplicate emails with `user-<pk>@users.shake.invalid` placeholders, reset invalid roles to `ENCODER`), then adds `UNIQUE (email)` and `CHECK (role IN ('ADMIN', 'ENCODER'))`. Runs non-atomically so the data fix commits before the schema change.
  - Expanded `accounts/tests.py` (email login, case-insensitivity, username rejection, inactive users, encoder-only registration, DB-level duplicate email / invalid role rejection, migration normalization, password change) and switched `dashboard/tests.py` login posts to email.
  - Verified 63 tests on SQLite (62 passed, 1 external-fixture skipped). PostgreSQL run not yet verified on this workstation: psycopg's `pq` DLL is blocked by a Windows Application Control policy.
- **Spec-Driven Context Sync:**
  - Committed `AGENTS.md` and `docs/context/*.md` on `develop` and released `develop` -> `main` via Pull Request.
  - Audited context files against the codebase and corrected drift: context paths now point to `docs/context/`, `BatchUpload` uploader FK documented as `user` (not `uploaded_by`), `RoleRequiredMixin` / `@role_required` documented in `dashboard/views.py`, and `BootstrapFormMixin` documented in `accounts/forms.py`.

## In Progress

- **CI/CD Pipeline (GitHub Actions) on `ci/github-actions-pipeline`:**
  - Added `.github/workflows/ci-cd.yml` (runs on push to `develop`, `main`, `feature/**`, `ci/**`, `docs/**` and on PRs into `develop`/`main`) with four jobs:
    - `test-sqlite`: `makemigrations --check --dry-run`, `check`, `migrate`, and the full test suite on SQLite (`DATABASE_URL=""`).
    - `test-postgres`: migrations + full test suite against a `postgres:16-alpine` service container (`DB_SSL_REQUIRE=False` because the service container does not serve SSL and `shake/settings.py` defaults `DB_SSL_REQUIRE` to `True`).
    - `privacy-and-security-guard`: AST scan rejecting cloud/network imports (`boto3`, `botocore`, `openai`, `anthropic`, `google.cloud`, `requests`, `httpx`, `aiohttp`) in `contracts/engine/` (Zero Cloud Egress invariant), plus `check --deploy --fail-level ERROR`.
    - `package-release` (CD): on pushes to `main` only, after all three CI jobs pass, builds a `git archive` zip + SHA-256 checksum and uploads it as a 30-day workflow artifact.
  - Locally verified with the CI environment values: YAML parses, `makemigrations --check` reports no changes, `check` is clean, `check --deploy` reports warnings only (W004, W008, W009, W012, W016), the privacy scan passes, and 45 SQLite tests run (44 passed, 1 external-fixture skipped). The PostgreSQL job has not been verified locally (psycopg `pq` DLL is blocked on this workstation) and will first be verified on GitHub Actions.

## Next Up

- **PD3 Feature Spec 03 — Lightweight Local Loopback REST API (`F-11`, SDD Should Have):**
  - Implement authenticated localhost endpoints `/api/v1/ingest` (accepting PDF uploads through the offline pipeline) and `/api/v1/contracts/{id}` (returning canonical JSON contract payloads) with automated API tests.
- **PD3 Optional Enhancements (SDD Could Have):**
  - Evaluate manual extraction boundary override UI for custom carrier layouts.
  - Evaluate user-configured currency converter presets and inland port synonym mappings.

## Open Questions

- Existing deployments: after `accounts.0002_user_constraints` runs, any account that had a blank or duplicate email now has a `user-<pk>@users.shake.invalid` placeholder and must have its real email set by an admin before it can sign in by email. Confirm whether the Neon PostgreSQL database has such rows before migrating it.
- For `F-11` (`/api/v1/ingest` and `/api/v1/contracts/{id}`), should authentication use a dedicated per-user `APIToken` model (`Authorization: Bearer <token>`) alongside Django session auth, or HTTP Basic / header token auth?
- Which SDD `Could Have` feature (manual extraction boundary override vs. custom port synonym/currency rules) should be prioritized after `F-11`?
- `ui-context.md` defines target design tokens (`--bg-base`, `--accent-primary` `#3f2870`, etc.) and `Varela Round` / `JetBrains Mono` fonts, but `templates/base.html` currently uses `--shake-*` variables with a system font stack. Should the templates be migrated to the documented tokens, or should `ui-context.md` be revised to match the shipped theme?
- `ui-context.md` and `code-standards.md` require offline-safe templates without external CDN dependencies, but `templates/base.html` loads Bootstrap 5.3.3 and Bootstrap Icons from `cdn.jsdelivr.net`. Should these assets be vendored into a local `static/` directory?
- `docs/feature-specs/01`–`10` exist locally but are not yet tracked in git; should they be committed alongside the context files?

## Architecture Decisions

- **Dual SQLite / PostgreSQL Runtime (`shake/settings.py`):** Defaults to local `db.sqlite3` when `DATABASE_URL` is unset so evaluators and offline workstations can run immediately, while supporting PostgreSQL via `dj-database-url` when `.env` is configured.
- **Offline Hybrid Extraction (`contracts/engine/extraction.py`):** Uses local OpenDataLoader Java AST table extraction when Java is available and falls back seamlessly to local PyMuPDF (`fitz`) vector block parsing with zero external cloud dependencies.
- **Strict Ownership & Non-Destructive Retention (`ContractOwnershipMixin`, `BR-09`):** Enforces per-uploader scoping for `ENCODER` users and preserves extracted contract audit trails via `ARCHIVED` status rather than hard deletion.

## Session Notes

- Repository: `https://github.com/CodeWithAdrianJames/SHAKE-Bona-AdrianJames-G01.git`
- Local test runner command (SQLite): `$env:DATABASE_URL=" "; .\.venv\Scripts\python.exe manage.py test -v 2`
- Local test runner command (PostgreSQL): `.\.venv\Scripts\python.exe manage.py test --keepdb -v 2`
- CI/CD: `.github/workflows/ci-cd.yml` runs SQLite tests, PostgreSQL tests, and the offline privacy/deploy audit on every push/PR; release bundles are packaged only on pushes to `main`.
- Always follow GitFlow (`feature/*` -> `develop` -> `main` via PR; never commit directly to `main`; keep feature branches undeleted; omit AI agent names/trailers from commit messages).
