# Spec 06: Cross-Page Table Stitching

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-04`  
**Enforced Business Rules:** `BR-07`, `BR-12`, `BR-13`  
**Implementation Status:** Complete

---

## Overview

Detect rate and arbitrary tables that span across multiple consecutive PDF pages, strip repeated column header rows and page footers at page breaks, reconnect vertically split line items, and record exact page-span provenance (`source_page_start`, `source_page_end`).

## Goals

1. Prevent repeated page-top table headers on pages `N+1` from being misparsed as corrupted data rows (`F-04`).
2. Reconnect individual freight rate rows whose port names, notes, or rate columns wrap across a page boundary.
3. Preserve column-to-equipment alignment across multi-page rate schedules.
4. Track accurate `source_page_start` and `source_page_end` values on stitched `FreightRate` rows.

## Functional Requirements

### Multi-Page Continuation & Header Pruning (`contracts/engine/extraction.py`, `contracts/engine/mapping.py`)

- Compares column header signatures and horizontal X-coordinate column boundaries between trailing tables on page `P` and leading tables on page `P+1`.
- When a table continues onto page `P+1` with an identical or compatible column header row, prunes the duplicate header row and merges the continuation rows into the active logical table.
- Filters out non-data page headers/footers (e.g., `Page 3 of 12`, `Confidential Service Contract`, repeated carrier watermarks).

### Vertical Split-Row Reconnection & Provenance Tracking

- Detects orphan continuation lines at the top of page `P+1` lacking port pair identifiers and merges their text/rate cells into the incomplete trailing row from page `P`.
- Sets `source_page_start = P` and `source_page_end = P+1` on stitched `FreightRate` records (`CHECK (source_page_end >= source_page_start)`).

## Data Model & Constraints (`contracts/models.py`)

- **`document_files` (`DocumentFile`):** Tracks `STITCHING` lifecycle state during multi-page table assembly (`BR-07`).
- **`freight_rates` (`FreightRate`):**
  - `source_page_start` (`INTEGER`, `CHECK (source_page_start >= 1)`)
  - `source_page_end` (`INTEGER`, `CHECK (source_page_end >= source_page_start)`)

## UI & Templates

- `templates/contracts/contract_detail.html` — Displays the page provenance column (e.g., `p. 2` or `pp. 2–3`) for every extracted `FreightRate` row so operators can verify cross-page stitches against the source PDF.

## Edge Cases & Error Handling

- A distinct new table starting on page `P+1` (for example, transitioning from Base Ocean Freight Rates to Destination Arbitrary Charges) is recognized by its changed column schema and is **not** merged into the preceding base rate table.
- Single-page contracts set `source_page_start == source_page_end == 1`.

## Acceptance Criteria

1. Multi-page rate tables produce zero duplicate header rows in `FreightRate` or `ArbitraryCharge`.
2. A rate row split across pages `2` and `3` persists as a single coherent `FreightRate` record with `source_page_start=2` and `source_page_end=3`.
3. Base freight tables and arbitrary charge tables on adjacent pages remain cleanly separated into their respective tables.
