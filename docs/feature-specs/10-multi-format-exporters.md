# Spec 10: Multi-Format Exporters & Export Audit Logging

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-09` (with `F-10` Export Audit Persistence)  
**Enforced Business Rules:** `BR-09`  
**Implementation Status:** Complete

---

## Overview

Transform extracted and operator-verified relational contract entities (`ContractMetadata`, `CarrierProfile`, `FreightRate`, `ArbitraryCharge`) into standardized, downloadable `JSON`, multi-sheet Microsoft Excel (`.xlsx`), and RFC-4180 `CSV` artifacts while recording an immutable `ExportRecord` audit entry for every download.

## Goals

1. Produce deterministic, canonical export schemas across `JSON`, `.xlsx`, and `CSV` formats (`F-09`).
2. Reconstruct canonical `MappingResult` structures directly from current database records so operator edits/additions in the UI are reflected in exported files.
3. Persist an `ExportRecord` audit entry (`user`, `contract`, `export_format`, `file_path`, `exported_at`) on every export execution (`F-10`).
4. Support exporting both `EXTRACTED` and `ARCHIVED` contracts without data loss (`BR-09`).

## Functional Requirements

### Canonical Export Engine (`contracts/engine/exporter.py`, `contracts/services/exporter.py`)

- `build_mapping_result_from_contract(contract)` queries `ContractMetadata`, `CarrierProfile`, ordered `FreightRate` rows, and ordered `ArbitraryCharge` rows to build a canonical `MappingResult`.
- `export_contract_artifact(contract, user, fmt)` supports three formats:
  - **`json`:** Structured canonical JSON payload containing contract metadata, carrier info, base freight rates array, arbitrary charges array, and export timestamp.
  - **`xlsx`:** Formatted multi-sheet Excel workbook (`openpyxl`) with distinct worksheets (`Contract Summary`, `Freight Rates`, `Arbitrary Charges`), styled headers, and typed numeric rate cells.
  - **`csv`:** Single RFC-4180 file (`<contract_number>_mapped.csv`, `text/csv; charset=utf-8`, CRLF line endings) built by `build_csv_records_from_contract()` and written by `contracts.engine.exporter.write_csv_export()`. It has one line per persisted `FreightRate` row followed by one per `ArbitraryCharge` row (origin and destination), each in `line_item_sequence` order, so no extracted surcharge is dropped. A `record_type` column (`FREIGHT_RATE` / `ARBITRARY_CHARGE`) tells the two apart, and all rows share the header `COLUMNS_CSV_EXPORT`:
    - Contract context (every row): `carrier_code`, `carrier_name`, `contract_number`, `trade_scope`, `commodity_desc`, `effective_date`, `expiration_date`, `line_item_sequence`.
    - Freight rate lane (blank on arbitrary rows): `origin_port_code`, `origin_port_name`, `destination_port_code`, `destination_port_name`.
    - Arbitrary leg (blank on freight rate rows): `direction` (`ORIGIN` / `DESTINATION`), `location_code`, `location_name`, `via_gateway_port`, `transport_mode`.
    - Shared amount fields: `charge_type` (`BASE_OCEAN_FREIGHT`, `ORIGIN_ARBITRARY`, `DESTINATION_ARBITRARY`), `basis` (`PER_CONTAINER`; every amount is quoted per unit of `equipment_type`), `equipment_type`, `currency_code`, `amount`, `source_page_start`, `source_page_end` (an arbitrary's `source_page_num` fills both), `confidence_score`.
    - The writer rejects keys outside the header (`ValueError`) rather than silently dropping them.
- Safely emits valid empty rate/arbitrary sheets or CSV headers when a contract has zero rate or arbitrary rows. A CSV export of a contract with neither contains just the header line.
- Saves the generated file locally under `media/exports/` and creates an `ExportRecord` row.

### Export View & Download Endpoint (`contracts/views.py`, `contracts/urls.py`)

- `ContractExportView` (`/contracts/<int:pk>/export/<str:fmt>/`) enforces `LoginRequiredMixin` and `ContractOwnershipMixin`, validates `fmt` in `{'json', 'xlsx', 'csv'}`, and returns an HTTP attachment (`Content-Disposition: attachment; filename="..."`).

## Data Model & Constraints (`contracts/models.py`)

- **`export_records` (`ExportRecord`):**
  - `export_id` (PK)
  - `user` (`ForeignKey -> CustomUser`, `ON DELETE RESTRICT`)
  - `contract` (`ForeignKey -> ContractMetadata`, `ON DELETE CASCADE`)
  - `export_format` (`VARCHAR(10)`, `CHECK (export_format IN ('JSON', 'XLSX', 'CSV'))`)
  - `file_path` (`VARCHAR(255)`, `NOT NULL`)
  - `exported_at` (`TIMESTAMP`, `NOT NULL`)

## UI & Templates

- `templates/contracts/contract_detail.html` — Provides **Export JSON**, **Export Excel (.xlsx)**, and **Export CSV** download buttons and displays the **Export Audit Log** table (`ExportRecord` history with format badge, operator, file path, and timestamp).
- `templates/dashboard/admin_dashboard.html` & `encoder_dashboard.html` — Displays recent export audit activity.

## Edge Cases & Error Handling

- Requesting an unsupported format (e.g., `/contracts/<pk>/export/xml/`) returns HTTP `400 Bad Request` or `404 Not Found` without creating an `ExportRecord`.
- Exporting a contract with zero `FreightRate` rows produces a valid `.xlsx` workbook / `.csv` file with column headers rather than raising an index error.
- `ENCODER` users cannot export contracts belonging to other operators.

## Acceptance Criteria

1. Clicking **Export JSON**, **Export Excel**, or **Export CSV** downloads a valid, non-empty file reflecting the latest edited contract metadata and rates.
2. Each export creates a persistent `ExportRecord` row linked to the requesting user and exported contract.
3. Contracts with zero rate rows export cleanly in `json`, `xlsx`, and `csv` formats.
4. Archived contracts (`status='ARCHIVED'`) remain exportable by authorized users.
5. The `csv` download contains every `FreightRate` row and every origin/destination `ArbitraryCharge` row of the contract, distinguished by `record_type`.
