# Spec 03: Offline PDF Document Parsing Engine

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-04`  
**Enforced Business Rules:** `BR-07`, `BR-08`  
**Implementation Status:** Complete

---

## Overview

Execute deterministic, 100% offline vector text, coordinate layout, and table structure extraction from digitally generated carrier contract PDFs on the local workstation with zero external cloud OCR or LLM network transmissions.

## Goals

1. Guarantee strict data privacy: no contract bytes, text streams, or metadata leave the local host (`Zero Cloud Egress`).
2. Extract structured page text blocks, bounding coordinates, and table grids deterministically (`F-04`).
3. Provide resilient local execution across workstations with or without a local Java Runtime Environment (JRE).
4. Record granular execution telemetry and error diagnostics in `ProcessingJob` (`F-10`).

## Functional Requirements

### Decoupled Extraction Module (`contracts/engine/extraction.py`, `contracts/engine/models.py`, `contracts/engine/errors.py`)

- Operates purely on local file paths/streams and returns typed internal dataclasses (`ExtractedPage`, `ExtractedTable`, `ExtractionResult`) without importing Django HTTP request/response objects.
- Primary extractor invokes local OpenDataLoader Java AST parsing when `java` is available on the host.
- Automatic fallback invokes local PyMuPDF (`fitz`) vector block and table coordinate extraction when JRE is absent or restricted.

### Lifecycle State & Job Telemetry (`contracts/services/pipeline.py`)

- Transitions `DocumentFile.status` through `PENDING` -> `PARSING` -> `STITCHING` -> `EXTRACTED` (or `FAILED` on unrecoverable parse errors).
- Creates `ProcessingJob` audit entries (`job_type` in `PARSE_VECTOR`, `STITCH_TABLES`, `EXTRACT_ENTITIES`, `FULL_PIPELINE`) capturing `started_at`, `completed_at`, `status` (`RUNNING`, `COMPLETED`, `FAILED`), and `error_message`.

## Data Model & Constraints (`contracts/models.py`)

- **`processing_jobs` (`ProcessingJob`):**
  - `job_id` (PK)
  - `document` (`FK -> DocumentFile`, `ON DELETE CASCADE`)
  - `job_type` (`CHECK (job_type IN ('PARSE_VECTOR', 'STITCH_TABLES', 'EXTRACT_ENTITIES', 'FULL_PIPELINE'))`)
  - `status` (`CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED'))`)
  - `error_message` (`TEXT`, nullable)
  - `started_at` (`TIMESTAMP`, `NOT NULL`)
  - `completed_at` (`TIMESTAMP`, nullable, `CHECK (completed_at >= started_at)`)

## UI & Templates

- `templates/contracts/contract_detail.html` — Renders the Processing Job history table showing job type, execution status badge, timestamps, and any parser diagnostic notes.
- `templates/dashboard/admin_dashboard.html` & `encoder_dashboard.html` — Displays recent processing job execution statuses.

## Edge Cases & Error Handling

- Corrupted PDF cross-reference tables or unsupported password-encrypted PDFs raise typed domain exceptions (`ContractExtractionError`), record `status='FAILED'` with `error_message` on `ProcessingJob`, and return a user-friendly form error.
- Missing JRE on Windows/Linux workstations falls back transparently to PyMuPDF without failing extraction.

## Acceptance Criteria

1. Extraction runs completely offline with network interfaces disabled and zero external HTTP requests.
2. Both OpenDataLoader AST (when JRE is present) and PyMuPDF fallback produce valid `ExtractionResult` payloads.
3. Every ingestion run persists a `ProcessingJob` record with `completed_at >= started_at`.
