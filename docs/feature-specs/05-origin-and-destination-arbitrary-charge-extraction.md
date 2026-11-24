# Spec 05: Origin & Destination Arbitrary Charge Extraction

**SDD Priority:** Must Have  
**SDD Feature ID:** `F-07`  
**Enforced Business Rules:** `BR-13`  
**Implementation Status:** Complete

---

## Overview

Detect and extract origin pre-carriage and destination on-carriage arbitrary surcharges from ocean freight contract appendices, binding inland locations, maritime gateway hub ports, transport modalities, ISO equipment types, and surcharge amounts to their parent `ContractMetadata` record.

## Goals

1. Distinguish `ORIGIN` arbitrary charges (inland origin point -> loading gateway port) from `DESTINATION` arbitrary charges (discharge gateway port -> inland destination ramp/point) (`F-07`).
2. Extract gateway port hubs (`via_gateway_port`), inland location codes/names (`location_code`, `location_name`), and inland transport modes (`RAIL`, `TRUCK`, `BARGE`, `FEEDER`, `INTERMODAL`).
3. Enforce standard ISO equipment types (`BR-13`) and non-negative surcharge amounts (`charge_amount >= 0`).

## Functional Requirements

### Arbitrary Section Detection & Normalization (`contracts/engine/mapping.py`)

- Identifies origin and destination arbitrary surcharge tables using section headers (e.g., `Origin Arbitrary`, `Destination Arbitrary`, `Outport / Inland Add-On`, `Via Gateway`, `Mode`).
- Maps transport modality strings (`R`, `Rail`, `T`, `Truck`, `Motor`, `Barge`, `Feeder`, `R/T`, `Intermodal`) to canonical `transport_mode` choices (`RAIL`, `TRUCK`, `BARGE`, `FEEDER`, `INTERMODAL`).
- Normalizes equipment types to `20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, or `SPECIAL` (`BR-13`).
- Assigns sequential `line_item_sequence` (`1, 2, 3...`) per contract and records `source_page_num` and `confidence_score`.

### Arbitrary Persistence (`contracts/services/pipeline.py`)

- Persists extracted `ArbitraryCharge` rows atomically alongside `ContractMetadata` and `FreightRate` records.

## Data Model & Constraints (`contracts/models.py`)

- **`arbitrary_charges` (`ArbitraryCharge`):**
  - `charge_id` (PK), `contract` (`FK -> ContractMetadata`, `ON DELETE CASCADE`)
  - `line_item_sequence` (`INTEGER`, `CHECK (line_item_sequence >= 1)`)
  - `charge_type` (`CHECK (charge_type IN ('ORIGIN', 'DESTINATION'))`)
  - `location_code` (`VARCHAR(10)`), `location_name` (`VARCHAR(100)`)
  - `via_gateway_port` (`VARCHAR(100)`)
  - `equipment_type` (`CHECK (equipment_type IN ('20GP', '40GP', '40HC', '45HC', '20RF', '40RF', 'SPECIAL'))`)
  - `currency_code` (`VARCHAR(3)`, default `'USD'`)
  - `charge_amount` (`DECIMAL(12,2)`, `CHECK (charge_amount >= 0)`)
  - `transport_mode` (`CHECK (transport_mode IN ('RAIL', 'TRUCK', 'BARGE', 'FEEDER', 'INTERMODAL'))`)
  - `source_page_num` (`CHECK (source_page_num >= 1)`)
  - `confidence_score` (`DECIMAL(4,3)`, `CHECK (0.000 <= confidence_score <= 1.000)`)
  - Table constraint: `UNIQUE (contract, line_item_sequence)`.

## UI & Templates

- `templates/contracts/contract_detail.html` — Renders the Origin & Destination Arbitrary Charges section displaying leg badge (`ORIGIN` / `DESTINATION`), inland location, gateway hub, transport mode, ISO container type, currency, and surcharge amount.

## Edge Cases & Error Handling

- Contracts containing only base port-to-port ocean rates and zero arbitrary surcharge appendices persist cleanly with `0` `ArbitraryCharge` rows and still export valid empty arbitrary tabs/sections.
- Zero-cost included inland points (`0.00`) are permitted by `CHECK (charge_amount >= 0)`.

## Acceptance Criteria

1. Origin and destination arbitrary tables map accurately to `charge_type='ORIGIN'` and `charge_type='DESTINATION'`.
2. Transport modes and container types normalize strictly to allowed SDD enum values (`BR-13`).
3. Contracts without arbitrary appendices ingest and display without error.
