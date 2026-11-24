# SHAKE

## Overview

SHAKE (**Structured Handling and Automated Knowledge Extraction**: *Privacy-First Ocean Freight Contract Data Extraction System*) is an offline-first local web application engineered to automate the ingestion, vector layout parsing, cross-page table stitching, context-aware metadata binding, and canonical extraction of ocean freight contract PDFs. Authorized logistics operators (`ENCODER`) and system administrators (`ADMIN`) process single or batch PDFs locally on their workstation without transmitting confidential rates, customer names, or route margins to external cloud OCR or commercial LLM APIs.

## Goals

1. **Normalized Relational Persistence:** Maintain a fully normalized (3NF) relational schema managing users, carrier profiles, document upload batches, ingested files, processing jobs, contract metadata, base ocean freight rates, arbitrary surcharges, and export audit histories.
2. **Deterministic Constraint Enforcement:** Enforce strict domain integrity (`BR-01`–`BR-13`) through both application form validation and native database constraints (`PRIMARY KEY`, `FOREIGN KEY` with `RESTRICT`/`CASCADE`, `UNIQUE`, `CHECK`, and `NOT NULL`).
3. **Offline Parsing & Rate Extraction:** Extract base port-to-port ocean freight rates, origin arbitrary charges, and destination arbitrary charges from digitally generated carrier PDFs with zero external network egress.
4. **Structural Continuity & Metadata Binding:** Detect and stitch multi-page tables across page boundaries, prune repeated headers, and bind parent contract numbers, trade scopes, commodity classes, and validity intervals to every extracted rate row.
5. **Interactive UI & Inspection Workflow:** Provide a responsive local Bootstrap 5 interface for single/batch uploads, real-time status monitoring, interactive data grid inspection/CRUD, non-destructive archiving, and canonical exports in `JSON`, styled Excel (`.xlsx`), and `CSV` formats.
6. **Local Programmatic Interoperability:** Expose a lightweight, authenticated local loopback REST API (`/api/v1/ingest`, `/api/v1/contracts/{id}`) enabling local system-to-system interoperability without external data egress.

## Core User Flow

1. User signs in (`ENCODER` or `ADMIN`) and lands on their role-specific workspace dashboard (`/dashboard/encoder/` or `/dashboard/admin/`).
2. User navigates to `/contracts/upload/` and submits one or more digitally generated carrier contract PDFs.
3. System validates the `.pdf` signature, vector text density (`BR-07`, `BR-08`), and cryptographic SHA-256 checksum uniqueness (`BR-06`), initializing `BatchUpload`, `DocumentFile`, and `ProcessingJob` records.
4. Offline extraction engine parses vector coordinates, stitches multi-page tables, strips duplicate headers, and maps canonical entities (`F-04`–`F-07`).
5. System atomically persists `ContractMetadata`, `FreightRate`, and `ArbitraryCharge` records into the relational database.
6. User opens `/contracts/<id>/` to inspect extracted contract headers, base ocean freight rates, arbitrary surcharges, and parsing confidence indicators (`F-08`).
7. User edits contract metadata (`BR-10`), adds, updates, or deletes freight rate rows (`BR-12`, `BR-13`), or archives the contract non-destructively (`BR-09`).
8. User exports canonical datasets in `JSON`, multi-sheet `.xlsx`, or `CSV` (`/contracts/<id>/export/<fmt>/`), recording an immutable `ExportRecord` audit entry (`F-09`, `F-10`).
9. System administrators manage carrier profiles and template versions at `/contracts/carriers/` (`F-02`, `BR-03`) and monitor system-wide queues, jobs, and export logs.
10. Authorized local internal tools can submit PDFs and query extracted JSON contracts via the loopback REST API (`F-11`).

## Features

### Authentication and Access Management (F-01)

- Email/password user registration, login, and CSRF-safe `POST` logout (`CustomUser`).
- Strict role assignment (`ADMIN` and `ENCODER`) with self-only profile updates and password changes.
- Ownership-based route and query isolation (`ContractOwnershipMixin`) ensuring `ENCODER` users access only their own uploaded contracts while `ADMIN` users have system-wide visibility.

### Single and Batch PDF Ingestion & Offline Vector Parsing (F-03, F-04)

- Local single-file and multi-file `.pdf` upload with file-signature validation and selectable vector-text verification (rejecting image-only/scanned PDFs).
- Cryptographic SHA-256 file hashing (`BR-06`) to block duplicate contract ingestion.
- Deterministic vector coordinate parsing and cross-page table stitching that removes repeated column headers and reconnects split table rows.

### Context-Aware Metadata, Freight Rate & Arbitrary Extraction (F-05, F-06, F-07)

- Extracts parent contract identifiers (`contract_number`, `trade_scope`, `commodity_desc`, `effective_date`, `expiration_date`) and associates them with a registered `CarrierProfile`.
- Extracts normalized base freight rate rows (`origin_port_code`, `destination_port_code`, `equipment_type`, `currency_code`, `rate_amount`, `source_page_start`, `source_page_end`, `confidence_score`).
- Extracts origin and destination arbitrary surcharges (`charge_type`, `location_code`, `via_gateway_port`, `transport_mode`, `charge_amount`).

### Results Inspection Viewer, CRUD & Non-Destructive Archiving (F-08, BR-09)

- Searchable contract registry (`/contracts/`) and interactive Contract Detail workspace (`/contracts/<id>/`).
- Full inline CRUD for contract metadata (`/contracts/<id>/edit/`) and freight rate rows (`/contracts/<id>/rates/add/`, `/contracts/<id>/rates/<rate_id>/edit/`, `POST` `/delete/`).
- Non-destructive contract archiving (`POST` `/contracts/<id>/archive/` transitioning `DocumentFile.status` to `ARCHIVED`) and hard-delete protection for extracted documents (`BR-09`).

### Canonical Multi-Format Exporters & Audit Logging (F-09, F-10)

- Deterministic export engine transforming relational contract records into standardized `JSON`, formatted multi-sheet Excel (`.xlsx`), and RFC-4180 `CSV` downloads.
- Permanent operational history tracking `ProcessingJob` diagnostics and `ExportRecord` user export logs.

### Carrier Profile Management & Live Dashboards (F-02, F-08)

- Administrative CRUD and active/inactive toggling for shipping carrier profiles (`MAEU`, `MSCU`, `CMDU`, `COSU`, `UNKN`, and custom carriers) under `/contracts/carriers/*`.
- Live role dashboards (`/dashboard/encoder/`, `/dashboard/admin/`) displaying real-time database metrics, recent uploads, processing job statuses, and export history.

### Lightweight Local Loopback REST API (F-11 — Should Have)

- Localhost-bound REST endpoints (`/api/v1/ingest`, `/api/v1/contracts/{id}`) enabling authenticated local processes to submit contract PDFs and retrieve structured JSON payloads.

### Optional Template & Transformation Enhancements (Could Have)

- Visual manual extraction boundary override for non-standard or newly released carrier PDF layouts.
- User-configured field transformation rules, currency converter presets, and inland port synonym mappings.

## Scope

### In Scope

- User authentication and role-based access control (`ADMIN`, `ENCODER`)
- Single and batch digital vector PDF contract ingestion with SHA-256 deduplication
- Offline vector coordinate extraction, cross-page table stitching, and metadata binding
- Normalized relational storage for base freight rates, origin/destination arbitraries, jobs, and audit logs
- Web-based inspection grid, metadata/rate CRUD, and `BR-09` non-destructive archiving
- Canonical `JSON`, `.xlsx`, and `CSV` exporters with persistent export audit records
- Administrative carrier profile management and live status/queue dashboards
- Lightweight local loopback HTTP/REST API (`/api/v1/ingest`, `/api/v1/contracts/{id}`)

### Out Of Scope

- Optical Character Recognition (OCR) for heavily distorted, scanned, photocopied, or handwritten PDFs
- Processing unrecognized carrier layouts not registered in the carrier profile dictionary
- Direct bidirectional database synchronization or live write-back into external proprietary ERP or TMS platforms
- Live external network connections to carrier portals, container tracking EDI networks, or customs platforms
- Live freight rate validation against external commercial indexes (e.g., Freightos Baltic Index, Xeneta)
- Public multi-tenant cloud hosting or integration with commercial cloud AI/LLM APIs (e.g., OpenAI, AWS Textract, Google Document AI)
- Enterprise online Single Sign-On (SSO) federations (Azure AD, SAML2, OAuth2 social logins)
- Native mobile client applications (Android/iOS)

## Success Criteria

1. Authenticated `ENCODER` and `ADMIN` users can sign in, view live role dashboards, and enforce strict ownership isolation (`ENCODER` restricted to own uploads).
2. Single and batch digital contract PDFs ingest locally with zero cloud transmissions, rejecting non-PDFs, image-only PDFs (`BR-07`, `BR-08`), and duplicate SHA-256 hashes (`BR-06`).
3. Multi-page tables stitch accurately into normalized `ContractMetadata`, `FreightRate`, and `ArbitraryCharge` records satisfying all database `CHECK`, `UNIQUE`, and `FOREIGN KEY` rules (`BR-01`–`BR-13`).
4. Users can inspect, edit, add/delete rates, and non-destructively archive (`BR-09`) contracts through the web UI without losing historical audit records.
5. Contracts export cleanly into `JSON`, `.xlsx`, and `CSV` formats while recording `ExportRecord` audit entries.
6. Administrative users can create, update, and activate/deactivate `CarrierProfile` records without breaking historical contract references.
7. Authorized local clients can submit PDFs and fetch structured JSON payloads over the localhost loopback REST API (`F-11`).
