from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from contracts.utils.logger import get_shared_logger
from contracts.utils.patterns import (
    AMOUNT_CELL_RX,
    CARRIER_PRIMARY_RX,
    CARRIER_SECONDARY_RX,
    COMMODITY_RX,
    COMMODITY_TRUNC_RX,
    CONTRACT_ID_RX,
    DATE_COMPACT_RX,
    DATE_EFFECTIVE_HEADER_RX,
    DATE_EXPIRY_COMPACT_RX,
    DATE_ISO_RX,
    DATE_RANGE_COMPACT_RX,
    DATE_RANGE_ISO_RX,
    DEST_ARBIT_RX,
    ORIGIN_ARBIT_RX,
    ORIGIN_RX,
    ORIGIN_VIA_RX,
    ORIGIN_VIA_SPLIT_RX,
    PAGE_BOILERPLATE_RX,
    RATE_OVER_RX,
    SCOPE_RX,
    WHITESPACE_RX,
    CITY_PAREN_STRIP_RX,
)

logger = get_shared_logger(__name__)


def clean_text(s: str) -> str:
    replacements = {
        "&amp;": "&",
        "NORTHAMERICA-EASTCOASTSOUTHAMERICA(SB)": "NORTH AMERICA - EAST COAST SOUTH AMERICA (SB)",
        "NORTHAMERICA-EUROPE(EB)": "NORTH AMERICA - EUROPE (EB)",
        "NORTHAMERICA-OCEANIA(WB)": "NORTH AMERICA - OCEANIA (WB)",
        "NORTHAMERICA-WESTCOASTSOUTHAMERICA(SB)": "NORTH AMERICA - WEST COAST SOUTH AMERICA (SB)",
        "NORTHAMERICA-WESTASIAANDAFRICA(WB)": "NORTH AMERICA - WEST ASIA AND AFRICA (WB)",
        "NORTHAMERICA-ASIA(SB)": "NORTH AMERICA - ASIA (WB)",
    }
    for bad, good in replacements.items():
        s = s.replace(bad, good)
    return s


def parse_date(raw: str) -> str:
    raw = raw.strip()
    m = DATE_COMPACT_RX.match(raw)
    if m:
        return f"{m.group(2).zfill(2)}/{m.group(3).zfill(2)}/{m.group(1)}"
    m = DATE_ISO_RX.match(raw)
    if m:
        return f"{m.group(2).zfill(2)}/{m.group(3).zfill(2)}/{m.group(1)}"
    return raw


def clean_city(raw: str) -> str:
    raw = re.sub(r"(?i)^\s*VIA\s*:?\s*", "", raw)
    s = re.split(r"\s*[,-]\s*", raw)[0]
    s = re.sub(r"(?i)\s*Rate$", "", s)
    s = CITY_PAREN_STRIP_RX.sub("", s)
    return WHITESPACE_RX.sub(" ", s).strip()


def same_city(city1: str | None, city2: str | None) -> bool:
    if not city1 or not city2:
        return False
    return city1.strip().lower() == city2.strip().lower()


def clean_commodity(raw: str) -> str:
    if not raw:
        return ""
    return COMMODITY_TRUNC_RX.split(raw, maxsplit=1)[0].strip(" ,;-")


def _cell_text(cell: dict) -> str:
    kids = cell.get("kids", [])
    if not kids:
        return ""
    raw_text = " ".join(k.get("content", "").strip() for k in kids if "content" in k)
    return clean_text(raw_text)


# --------------------------------------------------------------------------- #
# Table grids and cross-page stitching (F-04)
# --------------------------------------------------------------------------- #

# Column header tokens (normalized by _signature) that mark a row as a header row.
KNOWN_HEADER_SIGNATURES = frozenset(
    {
        "DESTINATION",
        "DESTINATIONVIA",
        "ORIGIN",
        "ORIGINVIA",
        "POINT",
        "VIA",
        "TERM",
        "TYPE",
        "CUR",
        "CURRENCY",
        "MODE",
        "SERVICE",
        "REMARKS",
        "NOTE",
        "COMMODITY",
        "20",
        "40",
        "40H",
        "40HC",
        "45",
        "20GP",
        "40GP",
        "45HC",
        "20RF",
        "40RF",
    }
)

# Minimum tolerance (PDF points) when comparing column x-boundaries across pages.
COLUMN_ALIGNMENT_TOLERANCE_PT = 4.0


def _signature(text: str) -> str:
    """Normalize a header/cell string for layout-insensitive comparison."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def _is_amount(text: str) -> bool:
    return bool(AMOUNT_CELL_RX.match((text or "").strip()))


@dataclass
class TableGrid:
    """One physical table fragment as it appears on a single PDF page."""

    page: int
    rows: list[list[str]]
    column_bounds: list[tuple[float, float]] | None

    @property
    def column_count(self) -> int:
        return len(self.rows[0]) if self.rows else 0


@dataclass
class StitchedRow:
    cells: list[str]
    page_start: int
    page_end: int


@dataclass
class LogicalTable:
    """A table assembled from one or more consecutive page fragments."""

    section: str
    metadata: dict[str, Any]
    headers: list[str]
    signature: tuple[str, ...]
    column_bounds: list[tuple[float, float]] | None
    page_start: int
    page_end: int
    rows: list[StitchedRow] = field(default_factory=list)


def table_grid(node: dict, page: int) -> TableGrid:
    """Flatten an AST table node into a rectangular grid of cleaned cell text."""
    raw_rows = node.get("rows", [])
    column_count = int(node.get("number of columns") or 0)
    for row in raw_rows:
        for cell in row.get("cells", []):
            column_count = max(column_count, int(cell.get("column number") or 1))

    rows: list[list[str]] = []
    lefts: dict[int, float] = {}
    rights: dict[int, float] = {}
    for row in raw_rows:
        values = [""] * column_count
        for cell in row.get("cells", []):
            col_index = int(cell.get("column number") or 1) - 1
            if not 0 <= col_index < column_count:
                continue
            values[col_index] = WHITESPACE_RX.sub(" ", _cell_text(cell)).strip()
            bbox = cell.get("bounding box")
            if bbox and len(bbox) == 4 and int(cell.get("column span") or 1) == 1:
                lefts[col_index] = min(lefts.get(col_index, bbox[0]), bbox[0])
                rights[col_index] = max(rights.get(col_index, bbox[2]), bbox[2])
        rows.append(values)

    column_bounds = None
    if column_count and len(lefts) == column_count:
        column_bounds = [(lefts[i], rights[i]) for i in range(column_count)]
    return TableGrid(page=page, rows=rows, column_bounds=column_bounds)


def _columns_aligned(
    a: list[tuple[float, float]] | None, b: list[tuple[float, float]] | None
) -> bool | None:
    """Compare horizontal column boundaries; None when either side lacks coordinates."""
    if a is None or b is None:
        return None
    if len(a) != len(b):
        return False
    width = max(a[-1][1] - a[0][0], b[-1][1] - b[0][0], 1.0)
    tolerance = max(COLUMN_ALIGNMENT_TOLERANCE_PT, 0.02 * width)
    return all(
        abs(la - lb) <= tolerance and abs(ra - rb) <= tolerance
        for (la, ra), (lb, rb) in zip(a, b)
    )


def _is_header_like(cells: list[str]) -> bool:
    """A header row carries known column vocabulary and no monetary amounts."""
    if any(_is_amount(c) for c in cells):
        return False
    return any(_signature(c) in KNOWN_HEADER_SIGNATURES for c in cells if c)


def _is_boilerplate_row(cells: list[str], running_texts: frozenset[str]) -> bool:
    """Detect page header/footer text captured inside a table body."""
    text = " ".join(c for c in cells if c).strip()
    if not text:
        return False
    return bool(PAGE_BOILERPLATE_RX.match(text)) or _signature(text) in running_texts


def _is_orphan_continuation(cells: list[str]) -> bool:
    """A row fragment with no line identifier (first column) but other content."""
    return bool(cells) and not cells[0] and any(cells[1:])


def _merge_split_row(head: StitchedRow, tail: list[str], tail_page: int) -> None:
    """Reconnect a line item that was split vertically across a page break."""
    merged = []
    for a, b in zip(head.cells, tail):
        if a and b:
            merged.append(f"{a} {b}")
        else:
            merged.append(a or b)
    head.cells = merged
    head.page_end = max(head.page_end, tail_page)


def _body_rows(
    rows: list[list[str]], signature: tuple[str, ...], running_texts: frozenset[str]
) -> list[list[str]]:
    """Drop blank rows, repeated header rows, and page header/footer rows."""
    body = []
    for cells in rows:
        if not any(cells):
            continue
        if tuple(_signature(c) for c in cells) == signature:
            continue
        if _is_boilerplate_row(cells, running_texts):
            continue
        body.append(cells)
    return body


def continuation_offset(previous: LogicalTable, grid: TableGrid) -> int | None:
    """
    Decide whether ``grid`` (the leading table on page P+1) continues ``previous``
    (the trailing table on page P) by comparing column header signatures and
    horizontal column alignment.

    Returns the number of leading rows to skip (1 when the header row is repeated,
    0 for a header-less continuation), or None when the fragment is a distinct table.
    """
    if not grid.rows or grid.page != previous.page_end + 1:
        return None
    if grid.column_count != len(previous.headers):
        return None
    if _columns_aligned(previous.column_bounds, grid.column_bounds) is False:
        return None

    first_row = grid.rows[0]
    if tuple(_signature(c) for c in first_row) == previous.signature:
        return 1
    if _is_header_like(first_row):
        # Same width but a different header vocabulary: a new table schema.
        return None
    return 0


def start_logical_table(
    grid: TableGrid,
    section: str,
    metadata: dict[str, Any],
    running_texts: frozenset[str] = frozenset(),
) -> LogicalTable | None:
    if len(grid.rows) < 2:
        return None
    headers = [
        text if text else f"col_{index + 1}" for index, text in enumerate(grid.rows[0])
    ]
    table = LogicalTable(
        section=section,
        metadata=metadata,
        headers=headers,
        signature=tuple(_signature(c) for c in grid.rows[0]),
        column_bounds=grid.column_bounds,
        page_start=grid.page,
        page_end=grid.page,
    )
    for cells in _body_rows(grid.rows[1:], table.signature, running_texts):
        table.rows.append(StitchedRow(cells=cells, page_start=grid.page, page_end=grid.page))
    return table if table.rows else None


def append_continuation(
    table: LogicalTable,
    grid: TableGrid,
    skip_rows: int,
    running_texts: frozenset[str] = frozenset(),
) -> None:
    """Merge a continuation fragment into ``table``, reconnecting a split line item."""
    body = _body_rows(grid.rows[skip_rows:], table.signature, running_texts)
    if body and table.rows and _is_orphan_continuation(body[0]):
        _merge_split_row(table.rows[-1], body.pop(0), grid.page)
    for cells in body:
        table.rows.append(StitchedRow(cells=cells, page_start=grid.page, page_end=grid.page))
    table.page_end = max(table.page_end, grid.page)


def logical_table_payload(table: LogicalTable) -> dict[str, Any]:
    """Serialize a stitched table into the extraction payload shape."""
    rows: list[dict[str, str]] = []
    spans: list[list[int]] = []
    for row in table.rows:
        row_dict = {}
        for index, header in enumerate(table.headers):
            value = row.cells[index] if index < len(row.cells) else ""
            row_dict[header] = clean_city(value) if index == 0 else value
        if any(v.strip() for v in row_dict.values()):
            rows.append(row_dict)
            spans.append([row.page_start, row.page_end])
    return {
        "section": table.section,
        "page_number": table.page_start,
        "source_page_start": table.page_start,
        "source_page_end": table.page_end,
        "metadata": table.metadata,
        "rows": rows,
        "row_page_spans": spans,
    }


def extract_table(table: dict) -> list[dict[str, str]]:
    """Extract one AST table node into header-keyed rows (no cross-page stitching)."""
    page = table.get("page number") or 1
    logical = start_logical_table(table_grid(table, page), "RATES", {})
    return logical_table_payload(logical)["rows"] if logical else []


def _is_context_text(text: str) -> bool:
    """True when a line carries section/scope/lane/date context (never boilerplate)."""
    return any(
        rx.search(text)
        for rx in (
            ORIGIN_ARBIT_RX,
            DEST_ARBIT_RX,
            SCOPE_RX,
            COMMODITY_RX,
            ORIGIN_RX,
            ORIGIN_VIA_RX,
            RATE_OVER_RX,
            DATE_RANGE_COMPACT_RX,
            DATE_EXPIRY_COMPACT_RX,
            DATE_RANGE_ISO_RX,
        )
    )


def _node_texts(node: dict) -> list[str]:
    ntype = node.get("type", "")
    if ntype in {"paragraph", "heading", "caption", "list item"}:
        return [clean_text(node.get("content", "").strip())]
    if ntype == "list":
        return [
            clean_text(item.get("content", "").strip())
            for item in node.get("list items", [])
        ]
    return []


def running_page_texts(kids: list[dict]) -> frozenset[str]:
    """
    Signatures of short, non-context text lines repeated on two or more pages:
    running headers, footers, and carrier watermarks.
    """
    pages_by_signature: dict[str, set[int]] = {}
    for node in kids:
        page = node.get("page number")
        for text in filter(None, _node_texts(node)):
            if len(text) > 80 or _is_context_text(text):
                continue
            sig = _signature(text)
            if sig:
                pages_by_signature.setdefault(sig, set()).add(page)
    return frozenset(sig for sig, pages in pages_by_signature.items() if len(pages) > 1)


def _is_page_boilerplate(text: str, running_texts: frozenset[str]) -> bool:
    return bool(PAGE_BOILERPLATE_RX.match(text)) or _signature(text) in running_texts


def extract(doc: Any, filename_stem: str = "UNKNOWN") -> dict[str, Any]:
    """Extract flat array JSON into structured dictionary payload."""
    data = doc.json if hasattr(doc, "json") else doc
    kids_array = data.get("kids", [])

    page_1_blocks = [
        clean_text(n.get("content", "").strip())
        for n in kids_array
        if n.get("type") in {"paragraph", "heading", "caption", "list item"}
        and n.get("page number") == 1
        and n.get("content", "").strip()
    ]
    first_page_text = "\n".join(page_1_blocks)

    contract_match = CONTRACT_ID_RX.search(filename_stem) or CONTRACT_ID_RX.search(
        first_page_text
    )
    contract_id = contract_match.group(1) if contract_match else "UNKNOWN"

    carrier_match = CARRIER_PRIMARY_RX.search(
        first_page_text
    ) or CARRIER_SECONDARY_RX.search(first_page_text)
    carrier = (
        WHITESPACE_RX.sub(" ", carrier_match.group(1).strip().rstrip(","))
        if carrier_match
        else filename_stem
    )

    # Fallback effective date from page-1 header e.g. "Effective Date 01 Jul, 2025"
    _months = {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
    header_effective_date: str | None = None
    m = DATE_EFFECTIVE_HEADER_RX.search(first_page_text)
    if m:
        day = m.group(1) or m.group(4)
        mon = m.group(2) or m.group(3)
        yr = m.group(5)
        mon_num = _months.get(mon[:3].lower(), 0)
        if mon_num:
            header_effective_date = f"{mon_num:02d}/{int(day):02d}/{yr}"

    extracted_tables: list[LogicalTable] = []
    current_section = "RATES"
    current_context: dict[str, Any] = {}
    running_texts = running_page_texts(kids_array)
    # Trailing table that may continue on the next page, and the page of the
    # most recent table node (used to tell whether a table leads its page).
    open_table: LogicalTable | None = None
    last_table_page: int | None = None

    def apply_backward(key: str, value: str):
        for tbl in reversed(extracted_tables):
            if tbl.section != current_section:
                break
            if not tbl.metadata.get(key):
                tbl.metadata[key] = value
            else:
                break

    for node in kids_array:
        ntype = node.get("type", "")

        # Evaluate all text found in this node
        for txt in filter(None, _node_texts(node)):
            if _is_page_boilerplate(txt, running_texts):
                continue

            # Any recognized context line ends the open table; only unrecognized
            # prose falls through to the bottom of this loop and restores it.
            carried_table, open_table = open_table, None
            upper_text = txt.upper()

            # Detect ORIGIN_ARBITRARIES and DESTINATION_ARBITRARIES section change
            if ORIGIN_ARBIT_RX.search(upper_text):
                current_section = "ORIGIN_ARBITRARIES"
                current_context.clear()
                continue
            if DEST_ARBIT_RX.search(upper_text):
                current_section = "DESTINATION_ARBITRARIES"
                current_context.clear()
                continue

            # Detect SCOPE such as "[NORTH AMERICA - ASIA (WB)]"
            m = SCOPE_RX.match(txt)
            if m:
                current_context["Scope"] = WHITESPACE_RX.sub(" ", m.group(1).strip())
                for k in (
                    "origin_city",
                    "origin_via_city",
                    "destination_city",
                    "destination_via_city",
                ):
                    current_context.pop(k, None)
                continue

            m = COMMODITY_RX.match(txt)
            if m:
                raw_group = m.group(1)
                origin_hit = re.search(r"(?i)ORIGIN\s*(?:VIA\s*)?:", raw_group)
                if origin_hit:
                    commodity_raw = raw_group[: origin_hit.start()].strip()
                    txt = raw_group[origin_hit.start() :].strip()
                else:
                    commodity_raw = raw_group.strip()

                current_context["commodity"] = WHITESPACE_RX.sub(
                    " ", commodity_raw
                ).strip()
                current_context["_commodity_open"] = (
                    not bool(re.search(r"[;.]\s*$", commodity_raw))
                    and not origin_hit
                )

                if not origin_hit:
                    continue

            # Detect single-line ORIGIN / ORIGIN VIA cities
            combo_match = ORIGIN_VIA_SPLIT_RX.split(txt)
            if len(combo_match) == 2 and combo_match[0].upper().startswith("ORIGIN"):
                current_context["origin_city"] = clean_city(
                    re.sub(r"(?i)^ORIGIN\s*:?\s*", "", combo_match[0])
                )
                current_context["origin_via_city"] = clean_city(combo_match[1])
                if (
                    current_context["origin_city"].lower()
                    == current_context["origin_via_city"].lower()
                ):
                    current_context["origin_via_city"] = None
                continue

            # Detect multi-line ORIGIN / ORIGIN VIA cities
            m = ORIGIN_RX.match(txt)
            if m:
                current_context["origin_city"] = clean_city(m.group(1))
                current_context.pop("origin_via_city", None)
                continue

            m = ORIGIN_VIA_RX.search(txt)
            if m:
                current_context["origin_via_city"] = clean_city(m.group(1))
                continue

            m = RATE_OVER_RX.match(txt)
            if m:
                if current_section == "ORIGIN_ARBITRARIES":
                    current_context["origin_via_city"] = clean_city(m.group(1))
                elif current_section == "DESTINATION_ARBITRARIES":
                    current_context["destination_via_city"] = clean_city(m.group(1))
                continue

            # COMMODITY CONTINUATION
            if not m and current_context.get("_commodity_open"):
                if re.search(r"(?i)\bvalid\b", txt) or txt.lstrip().startswith("<"):
                    current_context["_commodity_open"] = False
                else:
                    combined = (current_context.get("commodity") or "") + " " + txt
                    current_context["commodity"] = WHITESPACE_RX.sub(
                        " ", combined
                    ).strip()
                    current_context["_commodity_open"] = not bool(
                        re.search(r"[;.]\s*$", txt)
                    )
                    continue

            # DETECT "valid from yyyymmdd to yyyymmdd" date format in RATES
            m = DATE_RANGE_COMPACT_RX.search(txt)
            if m and current_section == "RATES":
                apply_backward("effective_date", parse_date(m.group(1)))
                apply_backward("expiration_date", parse_date(m.group(2)))
                continue

            # DETECT "valid to yyyymmdd" (expiration only) date format in RATES
            m = DATE_EXPIRY_COMPACT_RX.search(txt)
            if m and current_section == "RATES":
                apply_backward("expiration_date", parse_date(m.group(1)))
                continue

            # DETECT "valid yyyy-mm-dd to yyyy-mm-dd" date format in ARBITRARIES
            m = DATE_RANGE_ISO_RX.search(txt)
            if m and current_section in (
                "ORIGIN_ARBITRARIES",
                "DESTINATION_ARBITRARIES",
            ):
                apply_backward("effective_date", parse_date(m.group(1)))
                apply_backward("expiration_date", parse_date(m.group(2)))
                continue

            # Unrecognized prose (notes, remarks) does not interrupt a table.
            open_table = carried_table

        # Process Tables
        if ntype == "table":
            page = node.get("page number") or 1
            grid = table_grid(node, page)
            leads_page = last_table_page != page
            last_table_page = page

            skip = (
                continuation_offset(open_table, grid)
                if open_table is not None and leads_page
                else None
            )
            if skip is not None:
                append_continuation(open_table, grid, skip, running_texts)
                continue

            metadata = {
                k: v for k, v in current_context.items() if not k.startswith("_")
            }
            open_table = start_logical_table(
                grid, current_section, metadata, running_texts
            )
            if open_table is not None:
                extracted_tables.append(open_table)

    if header_effective_date:
        for tbl in extracted_tables:
            if not tbl.metadata.get("effective_date"):
                tbl.metadata["effective_date"] = header_effective_date

    return {
        "contract_id": contract_id,
        "carrier": carrier,
        "tables": [logical_table_payload(tbl) for tbl in extracted_tables],
    }
