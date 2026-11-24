# Spec 07: Context-Aware Metadata Association

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-05`  
**Enforced Business Rules:** `BR-10`, `BR-11`  
**Implementation Status:** Complete

---

## Overview

Extract global contractual header attributes—contract number, shipping carrier profile, trade lane scope, commodity description, effective date, and expiration date—and bind them systematically as the parent `ContractMetadata` entity governing all child freight rates and arbitrary charges.

## Goals

1. Extract parent contract context from cover pages and section headers and associate it with an active `CarrierProfile` (`BR-11`).
2. Bind every extracted `FreightRate` and `ArbitraryCharge` row to its parent `ContractMetadata` record (`1:M`) and source `DocumentFile` (`1:1`).
3. Enforce chronological validity intervals (`expiration_date >= effective_date`) at both extraction/form validation and database constraint levels (`BR-10`).

## Functional Requirements

### Header Context Extraction & Carrier Resolution (`contracts/engine/mapping.py`, `contracts/services/pipeline.py`)

- Extracts `contract_number` (e.g., `MSC-2026-901`, `MAEU-TP-88412`), `trade_scope` (e.g., `Transpacific Eastbound`), `commodity_desc` (e.g., `FAK - Freight All Kinds`), `effective_date`, and `expiration_date`.
- Matches detected carrier names/SCAC codes against active `CarrierProfile` records (`MAEU`, `MSCU`, `CMDU`, `COSU`), falling back to the seeded `UNKN` (`Unknown / Generic Carrier`) profile when no specific carrier matches (`BR-11`).
- Provides safe fallback defaults when optional header fields are omitted in minimal test PDFs while ensuring `expiration_date >= effective_date` (`BR-10`).

### Metadata Inspection & Editing (`/contracts/<pk>/edit/`)

- `ContractMetadataForm` (`contracts/forms.py`) and `ContractMetadataUpdateView` (`contracts/views.py`) allow authorized users to refine `carrier`, `contract_number`, `trade_scope`, `commodity_desc`, `effective_date`, and `expiration_date`, enforcing `BR-10`.

## Data Model & Constraints (`contracts/models.py`)

- **`contract_metadata` (`ContractMetadata`):**
  - `contract_id` (PK)
  - `document` (`OneToOneField -> DocumentFile`, `ON DELETE RESTRICT`)
  - `carrier` (`ForeignKey -> CarrierProfile`, `ON DELETE RESTRICT`, `BR-11`)
  - `contract_number` (`VARCHAR(100)`, `NOT NULL`)
  - `trade_scope` (`VARCHAR(255)`, `NOT NULL`)
  - `commodity_desc` (`TEXT`, `NOT NULL`)
  - `effective_date` (`DATE`, `NOT NULL`)
  - `expiration_date` (`DATE`, `NOT NULL`)
  - `extracted_at` (`TIMESTAMP`, `NOT NULL`)
  - Table constraint: `CHECK (expiration_date >= effective_date)` (`BR-10`).

## UI & Templates

- `templates/contracts/contract_detail.html` — Top summary card displaying Contract Number, Carrier badge, Trade Scope, Commodity Description, Validity Period (`effective_date` to `expiration_date`), and source PDF checksum.
- `templates/contracts/contract_form.html` — Edit metadata form displaying inline `BR-10` date validation errors when `expiration_date < effective_date`.

## Edge Cases & Error Handling

- Submitting `expiration_date` earlier than `effective_date` in `ContractMetadataForm` returns an inline form validation error without triggering a database `IntegrityError`.
- Referenced `CarrierProfile` and `DocumentFile` rows are protected by `ON DELETE RESTRICT` (`BR-09`, `BR-11`).

## Acceptance Criteria

1. Every extracted `DocumentFile` yields a 1:1 `ContractMetadata` record bound to a valid `CarrierProfile` (`BR-11`).
2. `ContractMetadata` rejects `expiration_date < effective_date` in both form submission and direct ORM persistence (`BR-10`).
3. Updating `ContractMetadata` preserves all child `FreightRate`, `ArbitraryCharge`, and `ExportRecord` associations.
