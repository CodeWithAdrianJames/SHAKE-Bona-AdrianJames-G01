# UI Context

## Theme

Clean, high-contrast operational workspace built on **Tabler 1.7.5** (Bootstrap 5), bundled offline under `static/vendor/tabler/` and themed by `static/css/shake-theme.css` (loaded right after `tabler.min.css` and `tabler-icons.min.css` in `templates/base.html`). The palette follows the SHAKE logo: maritime navy surfaces, cobalt/sky blue actions, and an amber-gold spark accent over a crisp light canvas.

Brand tokens are CSS custom properties in `shake-theme.css` (which also maps them onto Tabler's `--tblr-*` tokens). Templates use the brand classes instead of inline colors:

| Role | CSS Variable | Hex |
| --- | --- | --- |
| Sidebar / dark auth surfaces | `--shake-navy` | `#0F213E` |
| Elevated navy borders, hero gradient end | `--shake-navy-elevated` | `#162E54` |
| Primary buttons & active states | `--shake-blue` (`--tblr-primary`) | `#2563EB` |
| Highlights, link hover, active nav icon | `--shake-sky` | `#488EE6` |
| Spark accent (active nav bar, KPI accent, star) | `--shake-amber` | `#F59E0B` |
| Soft warning / pending status fill | `--shake-amber-soft` | `#FEF3C7` (text `--shake-amber-text` `#B45309`) |
| Page background | `--shake-canvas` | `#F8FAFC` |
| Card surface | `--shake-surface` | `#FFFFFF` |
| Hairlines & borders | `--shake-hairline` | `#E2E8F0` |

Body links use `#2563EB` (readable on white); `#488EE6` is the hover/highlight color and the accent on navy surfaces.

## Brand Mark

- Use only the slanted S-emblem with its amber 4-point star plus a bold `SHAKE` wordmark (`.shake-lockup`, `.shake-emblem`, `.shake-wordmark`). Never show the subtitle line from the source logo artwork.
- `static/img/shake-emblem-light.svg` (sky-to-cobalt gradient) on the navy sidebar and guest header; `static/img/shake-emblem.svg` (blue-to-navy gradient) on light cards, the footer, and the favicon. Both are vector traces of `static/img/shake-logo.png`, so there is no white raster box.
- `404.html` and `500.html` embed the same emblem as inline SVG because they cannot load static files.

## Typography

| Role | Font | Usage |
| --- | --- | --- |
| UI & Headings | Tabler system sans-serif stack | Navigation, page titles, section headers, form labels, and prose |
| Data & Identifiers | `.font-mono-code` (`ui-monospace`, `JetBrains Mono` when installed, Consolas, ...) | Contract numbers, UN/LOCODE port codes, SHA-256 hashes, ISO equipment codes, batch numbers, and monetary rates |

No web fonts are downloaded; every stack falls back to locally installed fonts.

## Border Radius & Elevation

| Context | Bootstrap / CSS Class |
| --- | --- |
| Inline badges & status pills | `rounded-2` / `rounded-pill` |
| Buttons & form controls | `rounded-2` |
| Workspace cards & tables | `.card` (0.75rem radius, `#E2E8F0` hairline border, faint shadow from `shake-theme.css`) |
| Confirmation modals & dialogs | `rounded-4` |

## Domain Visual Conventions

### Status Badge Palette

`templates/includes/status_badge.html` renders `DocumentFile.status` and `ProcessingJob.status` consistently:

| State | Visual Style | Meaning |
| --- | --- | --- |
| `EXTRACTED` / `COMPLETED` | Green (`bg-success-lt`, `ti-circle-check`) | Successfully parsed and persisted |
| `ARCHIVED` | Neutral slate (`bg-secondary-lt`, `ti-archive`) | Non-destructively archived per `BR-09` |
| `PENDING` / `PARSING` / `STITCHING` / `RUNNING` | Amber (`badge-amber`: `#FEF3C7` fill, `#B45309` text) | Queued or actively processing |
| `FAILED` / `CANCELLED` | Crimson (`bg-danger-lt`, `ti-alert-octagon`) | Validation or parser failure |

Other badge classes: `badge-carrier` (navy carrier codes), `badge-port` (UN/LOCODE), `badge-equipment` (ISO container types), `badge-format` (export formats), `badge-role-admin` (amber) / `badge-role-encoder` (blue), `badge-neutral`.

### Data Grid & Rate Table Conventions

- **Port Pairs:** Display 5-character UN/LOCODE codes (`CNSHA`, `USLAX`) as `badge-port font-mono-code` alongside human-readable port names.
- **Equipment Types:** Render ISO container types (`20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, `SPECIAL`) as `badge-equipment font-mono-code`.
- **Monetary Amounts:** Right-align `rate_amount` and `charge_amount` (`text-end font-mono-code shake-amount`) with 2 decimal places and 3-letter ISO currency code (`USD`, `EUR`).
- **Tables:** Tabler `table table-vcenter card-table` (plus `table-hover` / `table-sm`) inside cards; rate grids add `shake-rate-table` (single-line cells, horizontal scroll on small screens).
- **Confidence Scores:** Display algorithmic confidence (`0.000`–`1.000`) clearly so operators can spot rows needing manual review.

## Component Library

Tabler / Bootstrap 5 components (cards, KPI stat blocks `.shake-kpi`, badges, alerts, dropdowns, collapse) with standardized Django partial rendering via `templates/includes/form_fields.html` and `BootstrapFormMixin`. JavaScript comes only from the local `tabler.min.js` (which bundles the Bootstrap data API) plus the shared `data-confirm` submit listener in `base.html`. No SPA frameworks or CDN dependencies.

## Layout Patterns

- **Signed-in shell (`templates/base.html`):** Tabler dark-navy vertical sidebar (`.shake-sidebar`, `#0F213E`, collapsing behind a toggler below the `lg` breakpoint) with the emblem + `SHAKE` lockup and role-specific navigation; the active item gets a blue tint and an amber left bar. A white top utility bar shows the workspace context, avatar, role badge, and the `POST` logout form.
  - `ENCODER` ("Encoder Workspace" section): Encoder Workspace (`/dashboard/encoder/`), Upload Contract (`/contracts/upload/`), My Contracts (`/contracts/`); Account: Profile (`/accounts/profile/`).
  - `ADMIN` ("Admin Workspace" section): Admin Dashboard (`/dashboard/admin/`), All Contracts (`/contracts/`), Upload Contract (`/contracts/upload/`), Carrier Profiles (`/contracts/carriers/`); Account: Profile.
- **Guest shell:** Navy top bar with the lockup, a Log in link, and an amber Create Account button. Login, register, password change, and profile edit cards use a light `.shake-auth-header` carrying the lockup or section eyebrow.
- **Dashboard Workspace:** Navy `.shake-hero` banner, a row of `.shake-kpi` stat cards, then structured tables for recent contracts/batches, processing job status, and recent export audit logs.
- **Contract Detail Workspace (`/contracts/<id>/`):** Header card with bound contract metadata and action buttons (`Edit Metadata`, `Export JSON`, `Export Excel`, `Export CSV`, `Archive Contract`), followed by the Base Freight Rates grid (with inline `Add Rate`, `Edit`, `Delete` actions), Arbitrary Charges table, Processing Jobs, and Export Audit Log.

## Icons

Tabler Icons webfont (`ti ti-*`, bundled locally in `static/vendor/tabler/icons/`) with consistent spacing (`me-1` for compact table buttons, `me-2` for toolbar buttons and section headers).
