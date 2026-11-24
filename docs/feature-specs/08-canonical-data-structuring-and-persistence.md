# Spec 08: Canonical Data Structuring & Persistence

**SDD Priority:** Must Have  
**SDD Feature ID:** Core Persistence Architecture (SDD Section 4.0)  
**Enforced Business Rules:** `BR-01`–`BR-13`  
**Implementation Status:** Complete

---

## Overview

Persist all users, carrier definitions, upload batches, PDF files, processing jobs, contract headers, base freight rates, arbitrary surcharges, and export logs in a normalized (3NF) relational database enforcing native `PRIMARY KEY`, `FOREIGN KEY`, `UNIQUE`, `CHECK`, and `NOT NULL` constraints across PostgreSQL and default local SQLite.

## Goals

1. Implement all 9 normalized entities defined in SDD Section 4.0 without redundant data anomalies.
2. Enforce all 13 business rules (`BR-01`–`BR-13`) natively at the database constraint layer.
3. Guarantee atomic multi-table ingestion via `transaction.atomic()` so failed uploads never leave partial database state.
4. Support seamless local execution on SQLite (`db.sqlite3` default when `DATABASE_URL` is unset) as well as PostgreSQL (`DATABASE_URL` configured in `.env`).

## Functional Requirements

### Relational Entity Mapping (`accounts/models.py`, `contracts/models.py`)

- `accounts_customuser` (SDD `app_users`) -> `batch_uploads` (`1:M`, `RESTRICT`) and `export_records` (`1:M`, `RESTRICT`).
- `carrier_profiles` -> `contract_metadata` (`1:M`, `RESTRICT`).
- `batch_uploads` -> `document_files` (`1:M`, `CASCADE`).
- `document_files` -> `processing_jobs` (`1:M`, `CASCADE`) and `contract_metadata` (`1:1`, `RESTRICT`).
- `contract_metadata` -> `freight_rates` (`1:M`, `CASCADE`), `arbitrary_charges` (`1:M`, `CASCADE`), and `export_records` (`1:M`, `CASCADE`).

### Migrations & Seed Data (`contracts/migrations/`)

- `0001_initial.py` creates all 8 `contracts` tables, indexes, `UniqueConstraint`s, and `CheckConstraint`s.
- `0002_seed_default_carriers.py` populates canonical carrier profiles (`CMDU`, `COSU`, `MAEU`, `MSCU`, `UNKN`).
- Applied migration files are immutable and must never be edited or deleted.

### Dual-Database Configuration (`shake/settings.py`)

- When `DATABASE_URL` is unset or empty, Django automatically uses `django.db.backends.sqlite3` at `BASE_DIR / 'db.sqlite3'`.
- When `DATABASE_URL` is present in `.env`, Django connects to PostgreSQL via `dj_database_url.parse()`.

## Data Model & Constraints

- Enforces every constraint specified in SDD Section 3.1 & 4.4:
  - `UNIQUE`: `email`, `carrier_code`, `carrier_name`, `batch_number`, `file_hash_sha256`, `document_id` on `contract_metadata`, `(contract_id, line_item_sequence)` on `freight_rates` and `arbitrary_charges`.
  - `CHECK`: `total_files >= 1`, `file_size_bytes > 0`, `page_count > 0`, `completed_at >= started_at`, `expiration_date >= effective_date`, `rate_amount > 0`, `origin_port_code <> destination_port_code`, `charge_amount >= 0`, `source_page_end >= source_page_start`, `0 <= confidence_score <= 1`, and valid enum values for `role`, `status`, `job_type`, `equipment_type`, `charge_type`, `transport_mode`, and `export_format`.

## Edge Cases & Error Handling

- Database `IntegrityError` exceptions during concurrent duplicate submissions are caught gracefully and surfaced as validation messages.
- Full test suite passes on both SQLite and PostgreSQL backends.

## Acceptance Criteria

1. Running `manage.py migrate` on a fresh database creates all 9 normalized tables and seeds the 5 default carriers.
2. Direct ORM attempts to violate `BR-03`, `BR-05`, `BR-06`, `BR-08`, `BR-09`, `BR-10`, `BR-11`, `BR-12`, or `BR-13` raise `IntegrityError`.
3. `manage.py test` passes cleanly on both SQLite and PostgreSQL.
