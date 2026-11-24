# Spec 01: User Authentication & Access Management

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-01`  
**Enforced Business Rules:** `BR-01`, `BR-02`  
**Implementation Status:** Complete

---

## Overview

Provide secure, local email-and-password authentication, role assignment (`ADMIN` and `ENCODER`), session lifecycle management, self-only profile maintenance, and object-level ownership enforcement across the SHAKE web application.

## Goals

1. Authenticate users using a unique, valid email address rather than a generic username (`BR-01`).
2. Enforce strict role separation between logistics operators (`ENCODER`, corresponding to SDD `OPERATOR`) and operations administrators (`ADMIN`) (`BR-02`).
3. Prevent Insecure Direct Object Reference (IDOR) vulnerabilities by isolating `ENCODER` access to their own uploaded batches and contracts while granting `ADMIN` users full operational visibility.
4. Ensure state-changing logout actions require CSRF-protected `POST` requests.

## Functional Requirements

### User Registration & Login (`accounts/views.py`, `accounts/forms.py`)

- Registration (`/accounts/register/`) creates an active `CustomUser` record with validated unique email, full name, password confirmation, and default `ENCODER` role.
- Login (`/accounts/login/`) authenticates email/password credentials and redirects authenticated users to their role-appropriate dashboard (`/dashboard/encoder/` or `/dashboard/admin/`).
- Logout (`/accounts/logout/`) accepts `POST` requests only and terminates the active Django session cleanly.

### Profile Management (`/accounts/profile/`)

- Authenticated users can view and update only their own `full_name`, `email`, and password.
- Role escalation via profile forms is prohibited; `role` and `is_active` are excluded from self-service edits.

### Route & Ownership Guards (`accounts/mixins.py`, `contracts/views.py`)

- All protected endpoints inherit `LoginRequiredMixin`.
- `RoleRequiredMixin(allowed_roles=[CustomUser.Role.ADMIN])` restricts administrative views (`/dashboard/admin/`, `/contracts/carriers/*`) to `ADMIN` users, returning HTTP `403 Forbidden` for unauthorized roles.
- `ContractOwnershipMixin` filters contract, rate, document, and export querysets so `ENCODER` users access only records linked to `BatchUpload.uploaded_by == request.user`.

## Data Model & Constraints (`accounts/models.py`)

- **Table:** `accounts_customuser` (SDD `app_users`)
- **Fields:** `id` (PK), `email` (`VARCHAR(254)`, `UNIQUE`, `NOT NULL`), `password` (Django PBKDF2/Argon2 password hash), `full_name` (`VARCHAR(100)`), `role` (`ADMIN` or `ENCODER`, default `ENCODER`), `is_active` (`BOOLEAN`, default `True`), `date_joined` (`TIMESTAMP`).
- **Constraints:** `UNIQUE (email)` (`BR-01`) and `CHECK (role IN ('ADMIN', 'ENCODER'))` (`BR-02`).

## UI & Templates

- `templates/accounts/login.html` — Email/password login card using `BootstrapFormMixin` and `templates/includes/form_fields.html`.
- `templates/accounts/register.html` — Operator registration form with inline validation feedback.
- `templates/accounts/profile.html` — Self-service profile and password update form.
- `templates/base.html` — Displays current user identity, role badge, and `POST` logout button.

## Edge Cases & Error Handling

- Duplicate email registration or malformed email addresses return field-level validation errors without raising unhandled database exceptions.
- Inactive accounts (`is_active=False`) are blocked from authenticating.
- Direct URL traversal to another encoder's `/contracts/<pk>/` or `/contracts/<pk>/export/<fmt>/` returns HTTP `404 Not Found` (filtered queryset) or `403 Forbidden`.

## Acceptance Criteria

1. Unauthenticated requests to `/contracts/*` or `/dashboard/*` redirect to `/accounts/login/`.
2. Users cannot register with an existing email address (`BR-01`).
3. `ENCODER` users receive `403 Forbidden` on `/dashboard/admin/` and `/contracts/carriers/`.
4. `ENCODER` users cannot view, edit, archive, or export contracts uploaded by another user.
