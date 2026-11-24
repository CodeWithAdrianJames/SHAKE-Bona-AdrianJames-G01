# Spec 09: Extraction Results Viewer, Rate CRUD & Non-Destructive Archiving

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-08`  
**Enforced Business Rules:** `BR-09`, `BR-10`, `BR-12`, `BR-13`  
**Implementation Status:** Complete

---

## Overview

Provide a responsive browser-based workspace allowing operators and administrators to search/filter ingested contracts, inspect extracted contract metadata, base freight rates, arbitrary charges, and job diagnostics in an interactive data grid, perform verified CRUD updates on metadata and rate rows, and archive contracts non-destructively (`BR-09`).

## Goals

1. Display all accessible contracts in a searchable, filterable registry (`/contracts/`) scoped by user role (`ContractOwnershipMixin`).
2. Provide a comprehensive Contract Detail inspection grid (`/contracts/<pk>/`) showing metadata, base rates, arbitrary charges, processing jobs, and export audit logs (`F-08`).
3. Enable full CRUD on contract metadata and freight rate rows while enforcing `BR-10`, `BR-12`, and `BR-13`.
4. Enforce `BR-09`: prevent hard deletion of extracted contracts and transition them non-destructively to `ARCHIVED` status instead.

## Functional Requirements

### Contract Registry & Detail Inspection (`contracts/views.py`)

- `ContractListView` (`/contracts/`): Lists accessible contracts with search/filter controls (contract number, carrier, status) and quick action links.
- `ContractDetailView` (`/contracts/<pk>/`): Renders bound `ContractMetadata`, ordered `FreightRate` rows, `ArbitraryCharge` rows, `ProcessingJob` history, and `ExportRecord` audit logs.

### Metadata & Freight Rate CRUD (`contracts/views.py`, `contracts/forms.py`)

- `ContractMetadataUpdateView` (`/contracts/<pk>/edit/`): Updates parent contract fields (`BR-10`, `BR-11`).
- `FreightRateCreateView` (`/contracts/<pk>/rates/add/`): Adds a new freight rate row, auto-assigning `line_item_sequence = max(existing) + 1`, normalizing UN/LOCODE ports to uppercase, and enforcing `rate_amount > 0` (`BR-12`), `origin_port_code != destination_port_code`, and valid ISO `equipment_type` (`BR-13`).
- `FreightRateUpdateView` (`/contracts/<pk>/rates/<rate_id>/edit/`): Updates an existing freight rate row with identical validation rules.
- `FreightRateDeleteView` (`POST` `/contracts/<pk>/rates/<rate_id>/delete/`): Deletes an erroneous rate line item via CSRF-protected `POST`.

### Non-Destructive Archiving & Document Delete Guard (`BR-09`)

- `ContractArchiveView` (`POST` `/contracts/<pk>/archive/`): Transitions `document.status` to `DocumentFile.Status.ARCHIVED` while retaining all relational records and audit logs (`BR-09`).
- `DocumentFileDeleteView` (`POST` `/contracts/documents/<doc_id>/delete/`): Permits hard deletion **only** for `PENDING` or `FAILED` documents with no linked `ContractMetadata`; blocks deletion of extracted documents with an error message enforcing `BR-09`.

## UI & Templates

- `templates/contracts/contract_list.html` — Searchable contract list with status badges (`EXTRACTED`, `ARCHIVED`) and quick detail/export actions.
- `templates/contracts/contract_detail.html` — Interactive inspection grid with inline `Edit Metadata`, `Add Rate Row`, per-row `Edit`/`Delete`, and `Archive Contract` controls.
- `templates/contracts/contract_form.html` & `templates/contracts/rate_form.html` — Bootstrap 5 CRUD forms with field-level validation feedback.

## Edge Cases & Error Handling

- Submitting identical origin and destination ports (`CNSHA` -> `CNSHA`) or `rate_amount <= 0` displays clear validation errors on `rate_form.html`.
- Attempting to delete an extracted document via `/contracts/documents/<doc_id>/delete/` is blocked (`BR-09`).
- `ENCODER` users attempting to edit or delete rate rows on another user's contract are blocked by `ContractOwnershipMixin`.

## Acceptance Criteria

1. Operators can inspect extracted contracts and filter the contract list by query and status.
2. Operators can add, edit, and delete `FreightRate` rows on their own contracts with full `BR-12`/`BR-13` validation.
3. Clicking **Archive Contract** sets `DocumentFile.status = 'ARCHIVED'` without deleting `ContractMetadata`, `FreightRate`, or `ExportRecord` rows (`BR-09`).
4. Hard deletion is blocked for extracted documents (`BR-09`) and permitted only for `PENDING`/`FAILED` documents without `ContractMetadata`.
