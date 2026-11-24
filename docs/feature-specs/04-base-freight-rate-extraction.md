# Spec 04: Base Freight Rate Extraction

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-06`  
**Enforced Business Rules:** `BR-12`, `BR-13`  
**Implementation Status:** Complete

---

## Overview

Identify, normalize, and extract port-to-port base ocean freight rate rows—including origin/destination UN/LOCODE ports, ISO container equipment types, currency codes, monetary rate amounts, page provenance, and confidence scores—and bind them to their parent `ContractMetadata` record.

## Goals

1. Parse tabular base ocean freight sections across supported shipping line contract templates (`MAEU`, `MSCU`, `CMDU`, `COSU`, `UNKN`).
2. Normalize port identifiers to 5-character uppercase UN/LOCODEs (`CNSHA`, `USLAX`, `USLGB`, `NLRTM`, etc.) alongside human-readable port names.
3. Normalize container equipment specifications to canonical ISO maritime types (`20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, `SPECIAL`) (`BR-13`).
4. Enforce strictly positive rate amounts (`rate_amount > 0`) and distinct origin/destination port pairs (`BR-12`).

## Functional Requirements

### Canonical Rate Mapping (`contracts/engine/mapping.py`, `contracts/utils/patterns.py`)

- Detects base freight rate headers (e.g., `POL`, `Origin`, `POD`, `Destination`, `20'`, `40'`, `40'HC`, `Rate`, `USD`).
- Splits multi-column equipment rate rows (e.g., a single PDF row containing `20GP`, `40GP`, and `40HC` columns) into normalized per-equipment `FreightRate` line items with sequential `line_item_sequence` (`1, 2, 3...`).
- Normalizes currency symbols/codes (`$`, `USD`, `EUR`) to 3-letter ISO 4217 codes (default `USD`).
- Records `source_page_start`, `source_page_end`, and algorithmic `confidence_score` (`0.000`–`1.000`).

### Rate Persistence (`contracts/services/pipeline.py`)

- Persists normalized `FreightRate` rows inside `transaction.atomic()` linked via `ForeignKey(ContractMetadata, on_delete=models.CASCADE)`.

## Data Model & Constraints (`contracts/models.py`)

- **`freight_rates` (`FreightRate`):**
  - `rate_id` (PK), `contract` (`FK -> ContractMetadata`, `ON DELETE CASCADE`)
  - `line_item_sequence` (`INTEGER`, `CHECK (line_item_sequence >= 1)`)
  - `origin_port_code` (`VARCHAR(10)`), `origin_port_name` (`VARCHAR(100)`)
  - `destination_port_code` (`VARCHAR(10)`), `destination_port_name` (`VARCHAR(100)`)
  - `equipment_type` (`CHECK (equipment_type IN ('20GP', '40GP', '40HC', '45HC', '20RF', '40RF', 'SPECIAL'))`)
  - `currency_code` (`VARCHAR(3)`, default `'USD'`)
  - `rate_amount` (`DECIMAL(12,2)`, `CHECK (rate_amount > 0)`)
  - `source_page_start` (`CHECK (source_page_start >= 1)`), `source_page_end` (`CHECK (source_page_end >= source_page_start)`)
  - `confidence_score` (`DECIMAL(4,3)`, `CHECK (0.000 <= confidence_score <= 1.000)`)
  - Table constraints: `UNIQUE (contract, line_item_sequence)` and `CHECK (origin_port_code <> destination_port_code)`.

## UI & Templates

- `templates/contracts/contract_detail.html` — Renders the Base Ocean Freight Rates data grid with monospace port codes, ISO equipment badges, right-aligned monetary rates, page ranges, and confidence scores.

## Edge Cases & Error Handling

- Rows with `0.00`, negative, or non-numeric/placeholder (`N/A`, `-`) rate cells are skipped during automated extraction so `BR-12` (`rate_amount > 0`) is never violated.
- Unrecognized container labels map safely to `SPECIAL` (`BR-13`) with a lower confidence indicator for operator review.

## Acceptance Criteria

1. Multi-equipment rate rows expand into distinct normalized `FreightRate` records with sequential `line_item_sequence`.
2. Every persisted `FreightRate` satisfies `rate_amount > 0`, `origin_port_code != destination_port_code`, and valid `equipment_type`.
3. Deleting a parent `ContractMetadata` cascades cleanly to its child `FreightRate` records.
