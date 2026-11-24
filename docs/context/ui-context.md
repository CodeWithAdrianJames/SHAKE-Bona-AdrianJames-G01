# UI Context

## Theme

Clean, high-contrast operational workspace built on **Bootstrap 5** (`templates/base.html`). The visual language pairs crisp white data cards and tables over a soft slate canvas with a deep maritime indigo/blue brand identity and clear semantic status badges.

Define and reuse centralized CSS custom properties in `templates/base.html` rather than scattering hardcoded inline colors across templates:

| Role | CSS Variable | Hex / Value |
| --- | --- | --- |
| Page background | `--bg-base` | `#f4f6f9` |
| Card surface | `--bg-surface` | `#ffffff` |
| Subtle table/header surface | `--bg-subtle` | `#f8fafc` |
| Default border | `--border-default` | `#e2e8f0` |
| Primary text | `--text-primary` | `#1e293b` |
| Secondary text | `--text-secondary` | `#475569` |
| Muted text | `--text-muted` | `#64748b` |
| Brand primary | `--accent-primary` | `#3f2870` (deep indigo) |
| Maritime secondary | `--accent-secondary` | `#0d47a1` (ocean blue) |
| Highlight accent | `--accent-highlight` | `#f6cc4d` (warm amber) |
| Success state | `--state-success` | `#0f766e` (teal-green) |
| Warning state | `--state-warning` | `#d97706` (amber) |
| Error state | `--state-error` | `#dc2626` (crimson) |

## Typography

| Role | Font | Usage |
| --- | --- | --- |
| UI & Headings | `Varela Round` / system sans-serif | Navigation, page titles, section headers, form labels, and prose |
| Data & Identifiers | `JetBrains Mono` / `font-monospace` | Contract numbers, UN/LOCODE port codes, SHA-256 hashes, ISO equipment codes, and monetary rates |

## Border Radius & Elevation

| Context | Bootstrap / CSS Class |
| --- | --- |
| Inline badges & status pills | `rounded-2` / `rounded-pill` |
| Buttons & form controls | `rounded-2` |
| Workspace cards & tables | `rounded-3` with `border` and `shadow-sm` |
| Confirmation modals & dialogs | `rounded-4` |

## Domain Visual Conventions

### Status Badge Palette

Consistent Bootstrap 5 semantic badges reflect `DocumentFile.status` and `ProcessingJob.status`:

| State | Visual Style | Meaning |
| --- | --- | --- |
| `EXTRACTED` / `COMPLETED` | Teal/Green (`bg-success-subtle text-success`) | Successfully parsed and persisted |
| `ARCHIVED` | Neutral Slate (`bg-secondary-subtle text-secondary`) | Non-destructively archived per `BR-09` |
| `PENDING` / `PARSING` / `STITCHING` / `RUNNING` | Blue/Amber (`bg-info-subtle text-info` / `bg-warning-subtle`) | Queued or actively processing |
| `FAILED` / `CANCELLED` | Crimson (`bg-danger-subtle text-danger`) | Validation or parser failure |

### Data Grid & Rate Table Conventions

- **Port Pairs:** Display 5-character UN/LOCODE codes (`CNSHA`, `USLAX`) in bold uppercase `font-monospace` alongside human-readable port names.
- **Equipment Types:** Render ISO container types (`20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, `SPECIAL`) as compact monospace badges.
- **Monetary Amounts:** Right-align `rate_amount` and `charge_amount` (`text-end font-monospace`) with 2 decimal places and 3-letter ISO currency code (`USD`, `EUR`).
- **Confidence Scores:** Display algorithmic confidence (`0.000`–`1.000`) clearly so operators can spot rows needing manual review.

## Component Library

Bootstrap 5 components with standardized Django partial rendering via `templates/includes/form_fields.html` and `BootstrapFormMixin`. Avoid introducing heavy frontend SPA frameworks or external CDN dependencies that compromise offline execution.

## Layout Patterns

- **Top Navbar (`templates/base.html`):** Displays brand identity, role badge (`ADMIN` or `ENCODER`), and role-specific navigation links:
  - `ENCODER`: Dashboard (`/dashboard/encoder/`), Upload Contract (`/contracts/upload/`), My Contracts (`/contracts/`), Profile (`/accounts/profile/`), and `POST` Logout (`/accounts/logout/`).
  - `ADMIN`: Admin Dashboard (`/dashboard/admin/`), Upload Contract (`/contracts/upload/`), All Contracts (`/contracts/`), Carrier Profiles (`/contracts/carriers/`), Profile (`/accounts/profile/`), and `POST` Logout (`/accounts/logout/`).
- **Dashboard Workspace:** Top row of live KPI summary cards followed by structured tables for recent contracts/batches, processing job status, and recent export audit logs.
- **Contract Detail Workspace (`/contracts/<id>/`):** Header card with bound contract metadata and action buttons (`Edit Metadata`, `Export JSON`, `Export Excel`, `Export CSV`, `Archive Contract`), followed by Base Freight Rates grid (with inline `Add Rate`, `Edit`, `Delete` actions), Arbitrary Charges table, Processing Jobs, and Export Audit Log.

## Icons

Bootstrap Icons (`bi-*`) with consistent inline spacing (`me-1` for compact table buttons, `me-2` for primary toolbar buttons and section headers).
