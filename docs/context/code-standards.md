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
- Keep state-mutating actions (`rate_delete`, `document_delete`, `contract_archive`, `carrier_toggle`, `api_token_create`, `api_token_revoke`, `logout`) strictly `POST`-only (`http_method_names = ["post"]` or `@require_POST`) with CSRF protection.
- Give every destructive form a `data-confirm="..."` message (handled by the shared listener in `static/js/shake-ui.js`); the prompt is a UX guard, never a replacement for server-side checks.
- Resolve every object lookup with `get_object_or_404` on a user-scoped queryset; resolve child rows (`FreightRate`, `ArbitraryCharge`) through their scoped parent contract.
- Wrap multi-step writes (read-then-insert, delete-plus-file-cleanup) in `transaction.atomic()`; defer filesystem side effects to `transaction.on_commit`.
- Log unexpected exceptions with `logger.exception`; never `except Exception: pass`, and never show raw exception or database text to users.
- Never build SQL from user input (no `.raw()`, `.extra()`, or `cursor.execute` with request data) and never apply `|safe` to user-supplied values.

## Forms and Validation

- Every Django `Form` and `ModelForm` must inherit `BootstrapFormMixin` so fields automatically render Bootstrap 5 styling and `is-invalid` error feedback. Accessibility attributes come from Django itself: `BoundField` adds `aria-invalid="true"` to invalid widgets and `aria-describedby="<id>_helptext <id>_error"` whenever a widget has no `aria-describedby` of its own, so forms must not set `aria-describedby` in widget attrs. Style widgets with classes (e.g. `"class": "shake-input-code"` for code fields), never a `style` attribute.
- Normalize string codes (`carrier_code`, `origin_port_code`, `destination_port_code`, `currency_code`, `equipment_type`) to stripped uppercase inside form `clean_*` methods.
- Never let public or self-service forms set privileged fields (`role`, `is_staff`, `is_superuser`, `is_active`); assign `role` server-side (`ENCODER` for public registration).
- Enforce critical business rules (`BR-01`–`BR-13`) at both the Django validation layer (field validators and `Model.clean()`, which ModelForms always run, plus form `clean_*` normalization) and the database constraint layer (`UniqueConstraint`, `CheckConstraint`, `ForeignKey(on_delete=...)`). Put cross-field rules in `Model.clean()` instead of repeating them in the form.

## Templates and Styling

- Render every visible field through `templates/includes/form_field.html` (label, control, then `includes/field_feedback.html`), and render non-field errors and hidden fields with `includes/form_errors.html`. `field_feedback.html` gives the error container `id="<auto_id>_error"` and the help text `id="<auto_id>_helptext"`, the targets of Django's `aria-describedby`; a template that renders a widget outside `form_field.html` (e.g. the upload dropzone) must still include `field_feedback.html` for it. Short forms loop `{% for field in form.visible_fields %}`; longer forms group fields in `<fieldset class="shake-form-block">` sections. The protected `templates/includes/form_fields.html` is kept unchanged but is no longer included by any template.
- Use JetBrains Mono only for extracted/structured values: `.font-mono-data` (contract and batch numbers, SHA-256 hashes), `.shake-chip-*` (UN/LOCODE ports, ISO equipment, carrier codes, export formats), and `.shake-amount` (right-aligned rates with a `.shake-currency` prefix). Tables and counters use `tabular-nums`. Inline technical text (API paths, tokens) uses `<code>`.
- Load front-end assets only through `{% static %}` from `static/vendor/tabler/`, `static/css/shake-theme.css`, `static/fonts/`, and `static/img/`; never add CDN `<link>`/`<script>` tags, Google Fonts, or remote fonts. Use Tabler Icons (`ti ti-*`), the `--shake-*` tokens, and the brand classes in `shake-theme.css` instead of inline colors or inline styles.
- Render the brand mark only through `templates/partials/shake_mark.html` / `shake_lockup.html` / `shake_state.html` (inline SVG). Never place Sea Glass (`#7FD8C3`) on a light surface, never add symbols (anchors, ships, padlocks, sparkles, stars) to the mark, and never rotate, stretch, or animate its strokes upward.
- Put front-end behavior in `static/js/shake-ui.js` (no inline `<script>` blocks or `on*=` handler attributes, no CDN libraries) and wire it with `data-shake-*` attributes. Scripts are progressive enhancement: they must never be required to submit a form, must not rename or drop form fields, and must insert user-controlled text with `textContent`, never `innerHTML`.
- Start every signed-in page with the two-part `.shake-page-head` (breadcrumb + H1 + one-line `.shake-page-head-sub` | `.shake-page-head-actions`). Sectioned forms render fields one by one with `includes/form_field.html` inside `<fieldset class="shake-form-block">` groups (plus `includes/form_errors.html` for non-field errors) and must render every field of the form.
- Render `DocumentFile`/`ProcessingJob` status pills with `{% include "includes/status_badge.html" with status=... %}`.
- Keep templates self-contained and offline-safe without external runtime dependencies that fail without internet access.
- `templates/404.html` and `templates/500.html` must stay standalone (inline CSS and the inline SVG Settle mark, no `{% extends %}`, no `{% static %}`). `500.html` must not reverse URLs or read `user`/`request`/`messages`, because Django renders it with an empty context.

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
