# Spec 11: Lightweight Local Loopback REST API

**SDD Priority:** Should Have  
**SDD Feature ID:** `F-11`  
**SDD Tables Used:** `app_users` (`accounts_customuser`), `document_files`, `contract_metadata` (plus `carrier_profiles`, `batch_uploads`, `processing_jobs`, `freight_rates`, `arbitrary_charges`)  
**Enforced Business Rules:** `BR-01`, `BR-02`, `BR-04`–`BR-08`, `BR-10`–`BR-13`  
**Implementation Status:** Implemented (Project Development 3, branch `feature/f11-local-loopback-api`)

---

## Overview

Expose a secure, lightweight, localhost-bound RESTful HTTP interface (`/api/v1/ingest` and `/api/v1/contracts/<int:pk>`) enabling authenticated local scripts, desktop utilities, and internal workstation processes to submit ocean freight contract PDFs into the offline extraction pipeline and retrieve canonical JSON contract payloads with zero external network egress.

## Goals

1. Provide programmatic local PDF ingestion at `POST /api/v1/ingest` backed by the exact same offline validation, SHA-256 deduplication (`BR-06`), vector extraction (`BR-07`, `BR-08`), and atomic persistence pipeline used by the web UI (`F-03`–`F-07`).
2. Provide programmatic canonical JSON retrieval at `GET /api/v1/contracts/<int:pk>` reusing the canonical contract serializer (`contracts/engine/exporter.py`).
3. Enforce strict localhost loopback binding (`127.0.0.1` / `::1` / `localhost`) so external network hosts cannot invoke API endpoints (SDD Section 1.7).
4. Enforce user authentication (`Authorization: Bearer <token>` or active Django session) and role/ownership isolation (`ENCODER` restricted to own uploaded contracts; `ADMIN` unrestricted).

## Functional Requirements

### 1. Local Loopback Guard & Authentication (`accounts/models.py`, `contracts/api_views.py`)

- **Loopback Boundary (`SHAKE_API_LOOPBACK_ONLY = True` in `shake/settings.py`):**
  - Allowed addresses live in `SHAKE_API_LOOPBACK_ADDRESSES` (`["127.0.0.1", "::1"]`, plus `"testserver"` only when `DEBUG` is on or under `manage.py test`).
  - Reject any request whose `REMOTE_ADDR` is not in that list with HTTP `403 Forbidden` JSON error (`{"detail": "API access is restricted to localhost loopback connections."}`). The check runs before authentication. Proxy headers (`X-Forwarded-For`) are never trusted.
- **Per-User API Token (`accounts.APIToken`):**
  - Fields: `id` (PK), `user` (`ForeignKey -> CustomUser`, `ON DELETE CASCADE`), `name` (`VARCHAR(100)`, default `"Local CLI Token"`), `key` (`VARCHAR(64)`, `UNIQUE`, generated via `secrets.token_hex(32)`), `is_active` (`BOOLEAN`, default `True`), `created_at` (`TIMESTAMP`), `last_used_at` (`TIMESTAMP`, nullable).
  - Added as `accounts/migrations/0003_apitoken.py` (after `0002_user_constraints`) without modifying earlier migrations.
  - Allow authenticated users to generate (`POST /accounts/profile/api-tokens/`) and revoke (`POST /accounts/profile/api-tokens/<pk>/revoke/`) their own local API tokens from `/accounts/profile/` (`templates/accounts/profile.html`). Revoking sets `is_active = False`; another user's token ID returns `404`.
  - Tokens are listed (read-only, raw key never shown) in the Django admin for audit and revocation.
- **Authentication Resolution:**
  - Authenticate via `Authorization: Bearer <token>` header (scheme case-insensitive) matching an active `APIToken` whose `user.is_active` is `True` (updating `last_used_at`), or fall back to an authenticated Django session (`request.user.is_authenticated`).
  - A present `Authorization` header is authoritative: a malformed, unknown, or revoked token returns `401` even if a valid session cookie is also sent.
  - Unauthenticated or invalid/revoked token requests return HTTP `401 Unauthorized` (`{"detail": "Authentication credentials were not provided or are invalid."}`) with `WWW-Authenticate: Bearer realm="SHAKE local API"`.
  - **CSRF:** Bearer-token requests are CSRF-exempt. Session-authenticated unsafe requests (e.g. a browser `POST` to `/api/v1/ingest`) must pass Django's CSRF check, otherwise `403` JSON (`CSRF verification failed: ...`).

### 2. Local Ingestion Endpoint (`POST /api/v1/ingest`)

- **URL Routing (`shake/urls.py`, `contracts/api_urls.py`):**
  - Register `path("api/v1/ingest", ContractIngestAPIView.as_view(), name="api_contract_ingest")` (without trailing slash per SDD Section 2.2 so `POST` requests never fail due to `APPEND_SLASH` redirects; optionally support trailing-slash alias).
- **Request Format:**
  - `Content-Type: multipart/form-data` with exactly one `.pdf` in field `file` (max 100 MB, same as the web form). Batch upload stays in the web UI; a missing field, more than one file, or a non-multipart body returns `400`.
- **Execution (`contracts/services/pipeline.py`):**
  - Delegates directly to the existing offline ingestion and extraction service (`ingest_uploaded_files`) under the authenticated `user`, so `BatchUpload.user = request.user`. `BatchIngestionOutcome.rejected_errors` carries the validation exceptions so the API can map `DuplicateDocumentError` to `409` and other validation errors to `400`.
- **Response Payloads:**
  - **`201 Created`**:
    ```json
    {
      "contract_id": 15,
      "batch_id": 12,
      "batch_number": "BATCH-20261124-012",
      "document_id": 18,
      "original_file_name": "maersk_tp_2026.pdf",
      "file_hash_sha256": "...",
      "contract_number": "MAEU-TP-88412",
      "carrier_code": "MAEU",
      "status": "EXTRACTED",
      "rates_count": 24,
      "arbitraries_count": 6,
      "detail_url": "/api/v1/contracts/15"
    }
    ```
  - **`400 Bad Request`**: Missing/multiple `file`, non-multipart body, non-`.pdf` file, zero-byte file, corrupt PDF, or image-only/scanned PDF lacking vector text (`BR-07`, `BR-08`). Pipeline validation errors carry `"rule": "BR-07/BR-08"`.
  - **`409 Conflict`**: Duplicate PDF rejected by SHA-256 checksum (`BR-06`). Body: `{"detail": "Duplicate PDF blocked (BR-06): ...", "rule": "BR-06"}`. No records are created.
  - **`422 Unprocessable Entity`**: The PDF passed validation but extraction/mapping failed. As in the web UI, a `FAILED` `DocumentFile` and `ProcessingJob` are recorded (so the same file later returns `409`). Body: `{"detail": "Extraction failed for '...': ...", "batch_id": 12}`.

### 3. Contract Retrieval Endpoint (`GET /api/v1/contracts/<int:pk>`)

- **URL Routing:**
  - Register `path("api/v1/contracts/<int:pk>", ContractDetailAPIView.as_view(), name="api_contract_detail")`.
- **Ownership & Visibility:**
  - Enforce `ContractOwnershipMixin` semantics through the shared `scope_contracts_to_user()` helper (`contracts/views.py`): `ENCODER` users can retrieve only contracts where `document.batch.user == user`; `ADMIN` users can retrieve any contract.
  - Contracts outside the user's ownership scope or non-existent IDs return `404 Not Found` (`{"detail": "Contract not found."}`).
- **Response Payload (`200 OK`):**
  - Built by `build_contract_api_payload(contract)` (`contracts/services/exporter.py`): `contract_id`, `document_id`, `batch_id`, `document_status` (`EXTRACTED` or `ARCHIVED`), `original_file_name`, `file_hash_sha256`, `page_count`, `carrier` (`carrier_code`, `carrier_name`), `metadata` (`contract_number`, `trade_scope`, `commodity_desc`, `effective_date`, `expiration_date`, `extracted_at`), `freight_rates` and `arbitrary_charges` (normalized rows; amounts and confidence scores as decimal strings), and `canonical`.
  - `canonical` is `build_canonical_payload(build_mapping_result_from_contract(contract))` (`contracts/engine/exporter.py`), the exact structure written by the `F-09` JSON export (`carrier`, `contract_id`, `Rates`, `Origin_Arbitraries`, `Destination_Arbitraries`).

## Data Model & Constraints (`accounts/models.py`)

- **`accounts_apitoken` (`APIToken`):**
  - `id` (PK)
  - `user` (`ForeignKey -> CustomUser`, `ON DELETE CASCADE`)
  - `name` (`VARCHAR(100)`, `NOT NULL`)
  - `key` (`VARCHAR(64)`, `UNIQUE`, `NOT NULL`)
  - `is_active` (`BOOLEAN`, `NOT NULL`, default `True`)
  - `created_at` (`TIMESTAMP`, `NOT NULL`)
  - `last_used_at` (`TIMESTAMP`, nullable)

## UI & Templates

- `templates/accounts/profile.html` — Add a compact **Local API Tokens** card allowing `ENCODER` and `ADMIN` users to generate a new loopback Bearer token (displayed once upon creation), view active tokens (masked prefix + created/last-used timestamps), and revoke tokens via CSRF-protected `POST`.

## Edge Cases & Error Handling

- Non-loopback client IP (`REMOTE_ADDR = "203.0.113.10"`) returns `403 Forbidden` even with a valid Bearer token.
- Missing or malformed `Authorization` header returns `401 Unauthorized` with JSON error body (never an HTML login redirect).
- Uploading a duplicate PDF via `POST /api/v1/ingest` returns `409 Conflict` with the `BR-06` duplicate checksum message without creating partial database records.
- Archived contracts (`DocumentFile.Status.ARCHIVED`) remain readable via `GET /api/v1/contracts/<int:pk>` (`BR-09`).
- Wrong HTTP methods (e.g., `GET /api/v1/ingest` or `DELETE /api/v1/contracts/1`) return `405 Method Not Allowed` with JSON error payload and an `Allow` header (after the loopback and authentication checks).

## Acceptance Criteria

1. `POST /api/v1/ingest` with a valid Bearer token and digital vector PDF returns `201 Created`, persists `BatchUpload`, `DocumentFile`, `ProcessingJob`, `ContractMetadata`, `FreightRate`, and `ArbitraryCharge` records, and makes the contract immediately visible in the web UI.
2. `POST /api/v1/ingest` with a duplicate PDF returns `409 Conflict` (`BR-06`), and with a non-PDF, empty, corrupt, or image-only PDF returns `400 Bad Request` (`BR-07`, `BR-08`).
3. `GET /api/v1/contracts/<int:pk>` returns `200 OK` with canonical JSON matching the contract's metadata, base freight rates, and arbitrary charges.
4. `ENCODER` users receive `404 Not Found` when requesting another user's contract ID via `GET /api/v1/contracts/<int:pk>`, while `ADMIN` users can retrieve all contracts.
5. Requests originating from non-loopback IP addresses are rejected with `403 Forbidden`.
6. Automated API tests in `contracts/tests.py` and `accounts/tests.py` pass on both SQLite and PostgreSQL.

## Local Usage (`curl`)

```bash
export SHAKE_TOKEN=<token from /accounts/profile/>
curl -X POST http://127.0.0.1:8000/api/v1/ingest -H "Authorization: Bearer $SHAKE_TOKEN" -F "file=@./contract.pdf;type=application/pdf"
curl http://127.0.0.1:8000/api/v1/contracts/15 -H "Authorization: Bearer $SHAKE_TOKEN"
```

On Windows PowerShell call `curl.exe` (not the `curl` alias).
