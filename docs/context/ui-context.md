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
| `--shake-review` | `#9A6312` | Needs review (rate confidence below 0.900) only; also the `alert-warning` tint | semantic |
| `--shake-rejected` | `#B23E37` | Parse error / validation alert | semantic |

`--shake-tide-deep` (`#0B5E69`) is the pressed/hover shade of Tide.

### Derived tokens

Every rule in `shake-theme.css` outside the token block uses a `--shake-*` variable; raw hex or `rgba()` values live only in `:root`.

- **RGB channels:** `--shake-{paper,abyss,slate,tide,tide-light,sea-glass,deep-hull,verified,review,rejected}-rgb`, for `rgba(var(--x-rgb), alpha)`.
- **Lines and controls on light surfaces:** `--shake-line-input` `#8A9892` (form control boundary, 3.0 : 1 on white per WCAG 1.4.11), `--shake-line-strong` `#CBD3CF` (hover border on quiet controls), `--shake-line-dashed` `#B9C4BF` (dropzone), `--shake-placeholder` `#687880` (4.6 : 1 on white), `--shake-on-tide` (text on Tide fills).
- **Tints (one alpha set):** `--shake-tide-wash` (0.04, hover), `--shake-tide-tint` (0.08, chips / icon wells / pills), `--shake-tide-line` (0.3), `--shake-tide-line-strong` (0.45); `--shake-{verified,review,rejected}-tint` (0.06) and `-line` (0.35) for pills, alerts, and outline buttons.
- **Paper on dark surfaces:** `--shake-on-dark-muted` (0.76, secondary copy), `--shake-on-dark-subtle` (0.62, labels and icons; the floor for small text on Deep Hull), `--shake-on-dark-fill` / `-fill-strong` (0.08 / 0.12, hover / active), `--shake-on-dark-line` / `-line-strong` (0.16 / 0.3). Secondary copy on Tide uses full Paper (lower alphas drop below 4.5 : 1).
- **Focus and elevation:** `--shake-focus-ring` (3px Tide at 0.25), `--shake-shadow-card`, `--shake-shadow-menu`, `--shake-shadow-overlay` (rail), `--shake-scrim` (drawer backdrop).
- **Validation:** `--tblr-form-invalid-*` and `--tblr-form-valid-*` map to Rejected and Verified, and the in-field invalid cross is redrawn in Rejected, so the border, cross, and message share one red.

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

| Role | Font | Size / line height | Token | Class |
| --- | --- | --- | --- | --- |
| KPI figure | Manrope 800 | 32 / 38 | `--shake-text-3xl` | `.shake-kpi-figure` |
| H1 | Manrope 800 | 28 / 34 | `--shake-text-2xl` | `h1`, `.h1` |
| H2 | Manrope 700 | 20 / 28 | `--shake-text-xl` | `h2`, `.h2` (card titles), inline counts in the metadata strip |
| H3 | Manrope 700 | 17 / 24 | `--shake-text-lg` | `h3`/`h4`, side-card titles, `.shake-meta-primary`, empty-state titles |
| Body | Inter 400 | 15 / 23 | `--shake-text-base` | `body`, form controls |
| Table / data | Inter 400 · JetBrains Mono 500 | 14 | `--shake-text-md` | every `tbody td`, `.font-mono-data`, `.shake-amount`, list titles |
| Secondary | Inter 400 | 13 / 20 | `--shake-text-sm` | `.shake-secondary`, card subtitles, breadcrumbs, `.shake-chip-*` |
| Label | Inter 600, uppercase, +6% | 12 / 16 | `--shake-text-xs` | `.shake-label`, `.shake-meta-key`, table headers, pills |

- JetBrains Mono is reserved for extracted/structured values: UN/LOCODE ports (`PHCEB`), ISO equipment (`40HC`), currencies and freight rates, contract and batch numbers, and SHA-256 hashes. Inline technical text (`<code>`: API paths, token prefixes) uses JetBrains Mono 400.
- `font-variant-numeric: tabular-nums` is on for every table, badge, and numeric counter (`.shake-num`, `.shake-kpi-figure`).
- Error pages cannot load static files, so they fall back to the system sans stack.
- Text uses only these eight steps. Icon, avatar-initial, and wordmark sizes are component dimensions and stay literal. Inline mono values inside pills and secondary lines (`.shake-pill`, `.shake-secondary`, `.shake-meta-secondary`) inherit the surrounding size, so templates do not add `.small` to them.

### Spacing rhythm

Every card header, card body, toolbar, list row, and table edge shares one inline edge, `--shake-pad-x` (1.25rem), so content lines up from card to card. Block padding is `--shake-pad-y` (1rem) for card headers, KPI cells, and metadata cells, and `--shake-pad-y-compact` (0.75rem) for toolbars and list rows; card bodies use Tabler's 1.25rem. Form cards (`.shake-form-card`) keep their roomier 1.5rem / 1.75rem × 2rem body. Templates do not override card padding with `p-4`. Every card shares one elevation: a Mist hairline plus `--shake-shadow-card`.

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
| `ARCHIVED` | `shake-pill-neutral` (Slate) | Non-destructively archived per `BR-09`; neutral so Amber stays reserved for "Needs review" |
| `PENDING` / `PARSING` / `STITCHING` / `RUNNING` | `shake-pill-info` (Tide) | Queued or processing |
| `FAILED` / `CANCELLED` | `shake-pill-rejected` (`#B23E37`) | Validation or parser failure |

Rate-row confidence on the contract detail page: `confidence_score >= 0.900` shows a **Verified** pill, anything lower shows **Needs review**; both show the score in JetBrains Mono. The 0.900 cut-off is a display convention only (no model or business rule uses it).

Role chips: `badge-role-admin` (Deep Hull fill) and `badge-role-encoder` (Tide tint).

Pills are for record state only: document and job status, rate confidence, and the active / inactive / revoked state of carriers, users, and tokens. `shake-pill-neutral` (Slate, with its dot) marks archived, inactive, and revoked records. Card headers do not carry decorative pills or badges ("Healthy", "Localhost only", "Self-only access", "Parse error"): a card's subtitle carries that context, and row counts are `.shake-count` text (`<strong>3</strong> charge rows`). Archive and deactivate are neutral `btn-outline-secondary` actions; on an archived contract the toolbar shows "Archived, read-only (BR-09)" as Slate text beside the ARCHIVED pill.

### Data Grid & Rate Table Conventions

- **Ports:** `shake-chip shake-chip-port` (Paper fill, Deep Hull text) beside the port name in Slate.
- **Equipment:** `shake-chip shake-chip-equipment` (Tide tint) for `20GP`, `40GP`, `40HC`, `45HC`, `20RF`, `40RF`, `SPECIAL`.
- **Carriers / formats / arbitrary legs:** `shake-chip-carrier` (Deep Hull fill), `shake-chip-format` (Deep Hull outline) for export formats and the `ORIGIN` / `DESTINATION` leg of an arbitrary charge (both legs look the same).
- **Amounts:** right-aligned `.shake-amount` with a Slate `.shake-currency` prefix, 2 decimals with thousands grouping (`floatformat:"2g"`, e.g. `USD 2,450.00`); the ungrouped value stays in the row's `data-search` so search by amount works.
- **Tables:** Tabler `table table-vcenter card-table` inside cards with uppercase Label headers on Paper; rate grids add `shake-rate-table shake-table-sticky` inside a `.shake-table-scroll` wrapper (sticky header, scrolls within ~70vh).
- **Empty states:** `partials/empty_state.html` (Structured glyph, title, message, optional Tide action), never a bare "no data" row.

## Component Library

Tabler / Bootstrap 5 components (cards, dropdowns, alerts) with standardized Django form rendering: every visible field goes through `templates/includes/form_field.html` (label with a decorative `.shake-required` asterisk, control, then `includes/field_feedback.html` with the `<id>_error` / `<id>_helptext` targets of Django's `aria-describedby`), with `includes/form_errors.html` for non-field errors and hidden fields, on top of `BootstrapFormMixin`. Errors use one `.invalid-feedback` container per field (13px, Rejected, `.shake-field-error` line per message); code inputs (ports, carrier and currency codes) use `.shake-input-code` (JetBrains Mono, uppercase); an invalid upload dropzone turns Rejected via `:has(.is-invalid)`. Brand components in `shake-theme.css`:

- Shell: `.shake-rail` (navigation rail), `.shake-topbar`, `.shake-page-head` (two-part page header).
- Metrics: `.shake-kpi-strip` (4-card grid: one `.shake-hero` Deep Hull card with a Sea Glass `.shake-kpi-figure`, then three white `.shake-kpi` cards with a 12px uppercase `.shake-label`, a Manrope `.shake-kpi-figure` in `tabular-nums`, and a `.shake-kpi-caption`).
- Side rail: `.shake-side-stack`, `.shake-side-card`, `.shake-action-list` (quick actions), `.shake-mini-list` (compact rows), `.shake-steps` (vertical `1 · Raw → 2 · SHAKE → 3 · Structured`; `.is-current` / `.is-done` / `.is-working` on the upload page), `.shake-rule-list`.
- Data: `.shake-meta-strip` / `.shake-meta-cell` (4-cell metadata strip + a full-width cell), `.shake-table-toolbar` (search with `.shake-kbd` `/` hint, selects, `.shake-count`), `.shake-seg` / `.shake-seg-btn` (equipment pills), `.shake-lane` (Origin → Destination chips + names), `.shake-copy` (copy button, Tide when `.is-copied`), `.shake-section-label`.
- Forms: `.shake-form-card`, `.shake-form-block` (fieldset) + `.shake-form-block-title` (12px uppercase legend) + `.shake-form-block-hint`, `.shake-form-actions`.
- Upload: `.shake-dropzone` (`.is-dragover`, `.has-files`), `.shake-file-list` / `.shake-file-card`, `.shake-extracting`.
- Existing: `.shake-hero`, `.shake-cta-tide` with `.btn-paper`, `.shake-well`, `.shake-meta-key`, `.shake-pill-*`, `.shake-chip-*`.

JavaScript comes only from the local `tabler.min.js` (Bootstrap dropdowns, alert dismiss) and `static/js/shake-ui.js` (rail pin / drawer, `data-confirm` prompts, copy buttons, `/` search shortcut, live table filters, upload dropzone). Motion: the rail animates width only; the upload step highlight and new file cards arrive from 4px above and settle down (`@keyframes shake-step-settle`); the extracting state lets the strokes fade and drift down (`@keyframes shake-settle`). Nothing rotates or moves upward, and `prefers-reduced-motion: reduce` turns off rail, step, copy, and pill transitions and animations.

## Layout Patterns

- **Signed-in shell (`templates/base.html`):** Deep Hull navigation rail (`.shake-rail`). At `>= 992px` it is a 72px compact rail (cropped Settle mark: Paper waves + Sea Glass row, centered Tabler icons, Sea Glass active left rail, hairlines in place of group headings) and the workspace reserves a fixed 72px margin. Hover or keyboard focus expands it over the canvas to 252px (`220ms cubic-bezier(0.22, 1, 0.36, 1)`, shadow `12px 0 32px rgba(9, 27, 38, 0.24)`), fading in the `SHAKE` wordmark, the grouped navigation, and the Abyss footer `contract in · structured data out · nothing leaves the device`. The pin button (`localStorage` `shake.sidebar.pinned`) locks it open and reserves 252px. Below `992px` it is a slide-over drawer opened from the top bar, with a dismissible backdrop. Navigation:
  - Workspace: Dashboard (`/dashboard/encoder/`, ENCODER only), Contracts (`/contracts/`), Upload PDF (`/contracts/upload/`).
  - Administration (ADMIN only): Admin Overview (`/dashboard/admin/`), Carriers (`/contracts/carriers/`).
  - Account: Profile (`/accounts/profile/`), Sign Out (`POST` logout form).
  - The sticky Manifest Paper top bar shows the drawer toggle and small lockup (`< 992px`), the workspace label, and the user's name, role chip, and avatar.
- **Page header:** every signed-in page starts with `.shake-page-head`: breadcrumb, Manrope H1, one-line Slate subtitle on the left; primary CTAs on the right.
- **Guest pages (login, register):** no app chrome; a centered white card on Manifest Paper with the light-surface lockup, Tide submit button and focus rings, and a local-device privacy note under the card.
- **Dashboards:** Tier 1 is the 4-card KPI strip (encoder: structured rate rows, batches, extracted contracts, exports; admin: system-wide rate rows, users, extracted contracts, active carriers). Tier 2 is an 8 / 4 split: the Recent Contracts ledger (admin: plus the user roster) on the left; the side rail holds the reversed Tide upload CTA (encoder), Quick Actions, the vertical pipeline (admin: inside the Offline Engine card), output schemas and active carriers (encoder), and the carrier registry and recent exports (admin).
- **Contract Detail (`/contracts/<id>/`), 4 zones:** (1) page header with the contract number in Mono, carrier chip, and status pill, plus a toolbar: `Export XLSX` / `CSV` / `JSON` button group, Edit Metadata, Archive (`data-confirm`). (2) Metadata strip: Carrier & Code, Validity Window (Effective → Expiration), Extracted Line Items (freight rate and arbitrary charge counts), Source File & SHA-256 (file name, pages, size, truncated hash + copy button for the full hash), then a full-width Trade Scope & Commodity cell. (3) Base Ocean Freight Rates ledger with an integrated filter bar (`Showing X of Y rates`, search by port / code / amount with `/`, equipment pills `All` / `20GP` / `40GP` / `40HC` / `45HC`, confidence select, clear) and `+ Add Rate Row`. Columns in scan order: Lane (UN/LOCODE chips `PHCEB → USLAX`, port names, route copy), Equipment, Rate & Currency (right-aligned, grouped thousands, e.g. `USD 1,950.50`), Source · Notes (row number, page span, "stitched across pages" when the span covers more than one page; the schema stores no transit or free-time fields), Confidence, Actions (icon-only Edit / Delete). (4) Below a "Surcharges & audit trail" divider: Arbitrary Charges, then Processing Job History and Export Audit Log, each full width. A job row shows one line per job; its `error_message`, when present, follows as a borderless detail row (`tr.has-detail` + `tr.shake-detail-row`) in Rejected for FAILED jobs and Slate otherwise.
- **Contract list & carrier directory:** search (`/` shortcut) and filters sit in the table card's toolbar. The contract list submits its existing `q` / `status` `GET` form; the carrier directory filters the rendered rows client-side by text and status. Mono primary identifiers, right-aligned numbers, semantic pills, right-aligned actions, and Structured-glyph empty states. The contract number is the row's link to its detail page (no separate Inspect button); contract-list rows end in a fixed pair, an Edit icon and a `⋯` menu (Export XLSX / CSV / JSON, then Archive as a `data-confirm` form), so actions align whether or not a row is archived. The encoder dashboard's Recent Contracts keeps only an Export menu, and a failed upload's diagnostic sits under its file name (`.shake-diagnostic`) instead of in the Actions column. Row menus inside `.table-responsive` set `data-bs-popper-config='{"strategy":"fixed"}'` so the scroll container does not clip them.
- **Upload (`/contracts/upload/`), 7 / 5 split:** left card with the carrier template hint (`carrier_profile`), the PDF dropzone (`pdf_files`) with live file cards (name, size, remove), the extracting state, and Start Extraction; right column with the `1 · Raw` → `2 · SHAKE` → `3 · Structured` steps (step 1 is current, then done once files are chosen while step 2 becomes current) and the ingestion rules (100% local parsing, SHA-256 duplicate protection, vector text only).
- **Forms (contract, rate, carrier, profile edit, password):** page header + one card; fields grouped into fieldsets with 12px uppercase legends and 2-column rows (Contract # + Carrier, Effective + Expiration Date, Origin + Destination Port Code, Origin + Destination Port Name, Equipment Type + Base Rate, Carrier Code + Name, Template + Active); errors sit directly under each field.
- **Profile:** page header (Change Password, Edit Profile) → Deep Hull identity card beside sectioned details (Identity, Operations, Activity) → Local API Tokens (Generate a token, Your tokens).

## Icons

Tabler Icons webfont (`ti ti-*`, bundled locally in `static/vendor/tabler/icons/`) for UI affordances only (`me-1` in compact buttons). No icon may stand in for the brand mark, and ship / anchor / padlock / sparkle icons are not used as brand imagery.
