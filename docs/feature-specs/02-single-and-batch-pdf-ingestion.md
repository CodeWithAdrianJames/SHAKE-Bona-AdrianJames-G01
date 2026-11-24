# Spec 02: Single & Batch PDF Ingestion

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-03`  
**Enforced Business Rules:** `BR-04`, `BR-05`, `BR-06`, `BR-07`, `BR-08`  
**Implementation Status:** Complete

---

## Overview

Enable authenticated operators and administrators to upload single or multiple ocean freight contract PDFs locally via `/contracts/upload/`, verifying file integrity, digital vector-text presence, and cryptographic SHA-256 uniqueness before initializing batch and document persistence records.

## Goals

1. Support both single-file and multi-file `.pdf` uploads within a single atomic batch submission (`F-03`).
2. Reject non-PDF files, zero-byte files, and rasterized/scanned image-only PDFs prior to extraction (`BR-07`, `BR-08`).
3. Prevent duplicate contract ingestion across the system using SHA-256 content hashing (`BR-06`).
4. Track batch-level and file-level ingestion states deterministically (`BR-04`, `BR-05`).

## Functional Requirements

### Multi-File Upload Form & View (`contracts/forms.py`, `contracts/views.py`)

- `ContractUploadForm` accepts one or more `.pdf` files via `<input type="file" multiple accept=".pdf,application/pdf">` at `/contracts/upload/`.
- Enforces `total_files >= 1` (`BR-05`) and generates a unique `batch_number` (e.g., `BATCH-YYYYMMDD-<seq>`) linked to `request.user`.

### File Signature & Vector Integrity Validation (`contracts/engine/ingestion.py`)

- Verifies `.pdf` file extension and `%PDF-` magic header bytes.
- Verifies `file_size_bytes > 0` and `page_count > 0` (`BR-08`).
- Inspects page text objects via PyMuPDF (`fitz`) to confirm selectable machine-readable vector text exists; image-only/scanned PDFs fail validation cleanly with an actionable error message.

### Cryptographic SHA-256 Deduplication (`contracts/services/pipeline.py`)

- Computes the 64-character lowercase hexadecimal SHA-256 digest of the raw uploaded file bytes.
- Queries `DocumentFile.objects.filter(file_hash_sha256=digest)` before persisting; duplicate uploads are blocked with a user-facing validation error (`BR-06`).

## Data Model & Constraints (`contracts/models.py`)

- **`batch_uploads` (`BatchUpload`):** `batch_id` (PK), `uploaded_by` (`FK -> CustomUser`, `ON DELETE RESTRICT`), `batch_number` (`UNIQUE`), `total_files` (`CHECK (total_files >= 1)`), `status` (`QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`, `CANCELLED`), `created_at`.
- **`document_files` (`DocumentFile`):** `document_id` (PK), `batch` (`FK -> BatchUpload`, `ON DELETE CASCADE`), `uploaded_file` (`FileField`), `original_file_name`, `file_hash_sha256` (`CHAR(64)`, `UNIQUE`), `file_size_bytes` (`CHECK (file_size_bytes > 0)`), `page_count` (`CHECK (page_count > 0)`), `status` (`PENDING`, `PARSING`, `STITCHING`, `EXTRACTED`, `FAILED`, `ARCHIVED`), `uploaded_at`.

## UI & Templates

- `templates/contracts/contract_upload.html` — Clean upload card supporting single or multi-file selection, inline `BR-06`/`BR-07`/`BR-08` validation alerts, and batch processing summary feedback.

## Edge Cases & Error Handling

- Uploading a renamed `.txt` or `.docx` file with a `.pdf` extension is rejected by header/PyMuPDF validation without crashing.
- Uploading an identical contract PDF under a different filename is caught by `file_hash_sha256` (`BR-06`) and rejected cleanly.
- If one file in a multi-file batch fails validation, the error is surfaced cleanly without leaving orphaned partial records.

## Acceptance Criteria

1. Single-file upload creates 1 `BatchUpload` (`total_files=1`) and 1 `DocumentFile` (`status='EXTRACTED'`).
2. Multi-file upload of 2+ distinct PDFs creates 1 `BatchUpload` (`total_files=N`) and `N` `DocumentFile` records.
3. Re-uploading the exact same PDF file fails with a duplicate SHA-256 validation error (`BR-06`).
4. Uploading an empty file or scanned image-only PDF fails validation without HTTP 500.
