# UI Context

## Theme — "Settle": Deep water, clear data

SHAKE uses its official **"Settle"** brand identity on top of **Tabler 1.7.5** (Bootstrap 5), bundled offline under `static/vendor/tabler/` and themed by `static/css/shake-theme.css` (loaded right after `tabler.min.css` and `tabler-icons.min.css` in `templates/base.html`). A cool, deep core for trust sits on a warm paper ground that nods to the contracts themselves. Sea Glass is used for one thing only: data that has been extracted and settled.

Brand tokens are CSS custom properties in `shake-theme.css`, which also maps them onto Tabler's `--tblr-*` tokens (`primary`/`info` = Tide, `success` = Verified, `warning` = Needs review, `danger` = Rejected), so Tabler's derived `-lt` / `-subtle` utilities follow the palette. Templates use the brand classes, never inline colors or inline styles.

| Token | Hex | Role | Usage ratio |
| --- | --- | --- | --- |
| `--shake-paper` (Manifest Paper) | `#F6F3EC` | App ground, document viewer backdrop, top bar, table headers | 60% |
| `--shake-surface` | `#FFFFFF` | Cards, forms, rate tables (sit above the paper) | — |
| `--shake-deep-hull` (Deep Hull) | `#0E2A3B` | Sidebar, headings, body text, hero stat cards, dark lockups | 30% |
| `--shake-abyss` (Abyss) | `#091B26` | Sidebar footer, dark KPI callouts | — |
| `--shake-tide` (Tide) | `#0E7482` | Primary buttons, links, focus rings, selected rows, info states | 8% |
| `--shake-tide-light` (Tide Light) | `#2FA5B3` | Tide highlight on dark surfaces | — |
| `--shake-sea-glass` (Sea Glass) | `#7FD8C3` | Settled mark row, dark KPI numbers, active sidebar rail — **dark surfaces only** | 2% |
| `--shake-slate` (Slate) | `#55666E` | Secondary text | — |
| `--shake-mist` (Mist) | `#E4E8E6` | 1px borders and dividers | — |
| `--shake-verified` | `#2F7D4F` | Confirmed / Extracted | semantic |
| `--shake-review` | `#9A6312` | Needs review / Archived | semantic |
| `--shake-rejected` | `#B23E37` | Parse error / validation alert | semantic |

`--shake-tide-deep` (`#0B5E69`) is the pressed/hover shade of Tide.

## Brand Mark ("Settle")

- The mark is three strokes on a **64 × 64** grid, `stroke-width 6`, round caps, strokes 14 units apart (clear space `x = 14`). Read top to bottom: a rough wave (the raw carrier PDF), a calmer wave (extraction in progress), and a flat divided row (field on the left, value on the right).
- Wordmark: `SHAKE` in Manrope ExtraBold 800, uppercase, `letter-spacing: 0.08em`.
- Rendered as inline SVG through partials so it inherits the bundled Manrope font and CSS tokens:
  - `templates/partials/shake_mark.html` — `tone`: `light` (Deep Hull waves + Tide row), `hull` (Paper waves + Sea Glass row), `tide` (all Paper); `crop` trims the clear space.
  - `templates/partials/shake_lockup.html` — horizontal lockup; `tone` as above, `scale` `sm`/`lg`, optional `href`.
  - `templates/partials/shake_state.html` — extraction-state glyphs: `raw` (three rough waves, Slate), `shake` (the mark), `structured` (three divided rows, Tide).
  - `templates/partials/empty_state.html` — empty state built on the `structured` glyph.
- Standalone files in `static/img/`: `shake-mark.svg` (on light), `shake-mark-hull.svg` (on Deep Hull), `shake-mark-tide.svg` (reversed on Tide), `favicon.svg` (Deep Hull rounded square; middle stroke dropped and the rest thickened to 9 units per the <= 32 px rule), `shake-state-raw.svg`, `shake-state-structured.svg`.
- Rules: never put Sea Glass on a light surface; never add symbols (anchors, ships, padlocks, sparkles, AI stars); never drop the settled row; never rotate, stretch, or animate the strokes upward (data always settles downward).
- `404.html` and `500.html` embed the light-surface mark as inline SVG because they cannot load static files.

## Typography

All three families are SIL OFL 1.1 WOFF2 files bundled in `static/fonts/` (latin + latin-ext subsets, `font-display: swap`); there is no Google Fonts or CDN request. Manrope speaks, Inter explains, Mono records.

| Role | Font | Size / line height | Class |
| --- | --- | --- | --- |
| Display | Manrope 800 | 36 / 40 | `.shake-display`, `.shake-hero-metric` |
| H1 | Manrope 800 | 28 / 34 | `h1`, `.h1` |
| H2 | Manrope 700 | 20 / 28 | `h2`, `.h2` (card titles) |
| Body | Inter 400 | 15 / 23 | `body` |
| Label | Inter 600, uppercase, +6% | 12 | `.shake-label`, `.shake-meta-key`, table headers |
| Data | JetBrains Mono 500 | 14 | `.font-mono-data`, `.shake-chip-*`, `.shake-amount` |

- JetBrains Mono is reserved for extracted/structured values: UN/LOCODE ports (`PHCEB`), ISO equipment (`40HC`), currencies and freight rates, contract and batch numbers, and SHA-256 hashes. Inline technical text (`<code>`: API paths, token prefixes) uses JetBrains Mono 400.
- `font-variant-numeric: tabular-nums` is on for every table, badge, and numeric counter (`.shake-num`, `.shake-kpi-value`).
- Error pages cannot load static files, so they fall back to the system sans stack.

## Border Radius & Elevation

| Context | Class |
| --- | --- |
| Status pills | `.shake-pill` (fully rounded) |
| Data chips | `.shake-chip` (0.35rem) |
| Buttons & form controls | 0.5rem |
| Cards, wells, dropzone | `.card` / `.shake-well` / `.shake-dropzone` (0.75rem, Mist hairline, faint shadow) |

## Domain Visual Conventions

### Extraction-State Pills

`templates/includes/status_badge.html` renders `DocumentFile.status` and `ProcessingJob.status` as `.shake-pill` (status text unchanged):

| State | Pill | Meaning |
| --- | --- | --- |
| `EXTRACTED` / `COMPLETED` | `shake-pill-verified` (`#2F7D4F`) | Successfully parsed and persisted |
| `ARCHIVED` | `shake-pill-review` (`#9A6312`) | Non-destructively archived per `BR-09` |
| `PENDING` / `PARSING` / `STITCHING` / `RUNNING` | `shake-pill-info` (Tide) | Queued or processing |
| `FAILED` / `CANCELLED` | `shake-pill-rejected` (`#B23E37`) | Validation or parser failure |

Rate-row confidence on the contract detail page: `confidence_score >= 0.900` shows a **Verified** pill, anything lower shows **Needs review**; both show the score in JetBrains Mono. The 0.900 cut-off is a display convention only (no model or business rule uses it).

Role chips: `badge-role-admin` (Deep Hull fill) and `badge-role-encoder` (Tide tint). Counters: `badge-count`, `badge-neutral`.

### Data Grid & Rate Table Conventions

- **Ports:** `shake-chip shake-chip-port` (Paper fill, Deep Hull text) beside the port name in Slate.
- **Equipment:** `shake-chip shake-chip-equipment` (Tide tint) for `20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, `SPECIAL`.
- **Carriers / formats:** `shake-chip-carrier` (Deep Hull fill), `shake-chip-format` (Deep Hull outline).
- **Amounts:** right-aligned `.shake-amount` with a Slate `.shake-currency` prefix, 2 decimals.
- **Tables:** Tabler `table table-vcenter card-table` inside cards with uppercase Label headers on Paper; rate grids add `shake-rate-table shake-table-sticky` inside a `.shake-table-scroll` wrapper (sticky header, scrolls within ~70vh).
- **Empty states:** `partials/empty_state.html` (Structured glyph, title, message, optional Tide action), never a bare "no data" row.

## Component Library

Tabler / Bootstrap 5 components (cards, dropdowns, collapse, alerts) with standardized Django form rendering via `templates/includes/form_fields.html` and `BootstrapFormMixin`. Brand components in `shake-theme.css`: `.shake-hero` (Deep Hull stat card with `.shake-hero-metric` in Sea Glass), `.shake-kpi` (white KPI card), `.shake-cta-tide` (reversed Tide call to action with `.btn-paper`), `.shake-pipeline` / `.shake-step` (the 1 · Raw → 2 · SHAKE → 3 · Structured strip), `.shake-dropzone`, `.shake-extracting` (in-progress state), `.shake-export-toolbar`, `.shake-well`, `.shake-meta-key`. JavaScript comes only from the local `tabler.min.js`, the shared `data-confirm` submit listener in `base.html`, and a small progressive-enhancement script on the upload page (drag-and-drop file list and the extracting state; the plain form still posts without it). Motion: the extracting state lets the strokes fade and drift down into place (`@keyframes shake-settle`) and is disabled under `prefers-reduced-motion`.

## Layout Patterns

- **Signed-in shell (`templates/base.html`):** Deep Hull vertical sidebar (`.shake-sidebar`, collapsing below `lg`) with the dark-surface lockup, a Sea Glass active left rail, and an Abyss footer reading `contract in · structured data out · nothing leaves the device`. Navigation:
  - Workspace: Dashboard (`/dashboard/encoder/`, ENCODER only), Contracts (`/contracts/`), Upload PDF (`/contracts/upload/`).
  - Administration (ADMIN only): Admin Overview (`/dashboard/admin/`), Carriers (`/contracts/carriers/`).
  - Account: Profile (`/accounts/profile/`).
  - The Manifest Paper top bar shows the workspace label, avatar, name, role chip, and the `POST` logout form.
- **Guest pages (login, register):** no app chrome; a centered white card on Manifest Paper with the light-surface lockup, Tide submit button and focus rings, and a local-device privacy note under the card.
- **Dashboards:** page header (Label eyebrow, H1, Slate lede) → a Deep Hull hero stat card (Sea Glass metric) beside white KPI cards → (encoder) a reversed Tide upload CTA → recent-contracts / roster / carrier / job / export tables with semantic pills.
- **Contract Detail (`/contracts/<id>/`):** metadata summary card (carrier chip, contract number in Mono, effective/expiration dates, trade scope, source PDF, full SHA-256 in Mono, commodity) with an export toolbar (`XLSX`, `CSV`, `JSON`) and Edit / Archive actions; then the sticky-header Base Freight Rates grid (confidence pills, icon-only Edit / Delete with `aria-label`s), Arbitrary Charges, Processing Job History, and Export Audit Log.
- **Upload (`/contracts/upload/`):** the 1 · Raw → 2 · SHAKE → 3 · Structured strip, then a card with the PDF dropzone (`pdf_files`), the carrier template hint (`carrier_profile`), and the extracting state shown on submit.

## Icons

Tabler Icons webfont (`ti ti-*`, bundled locally in `static/vendor/tabler/icons/`) for UI affordances only (`me-1` in compact buttons). No icon may stand in for the brand mark, and ship / anchor / padlock / sparkle icons are not used as brand imagery.
