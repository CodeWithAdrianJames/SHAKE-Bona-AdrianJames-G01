from __future__ import annotations

import re
from typing import Any

from contracts.utils.logger import get_shared_logger
from contracts.utils.patterns import (
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


def _cell_text_city(cell: dict) -> str:
    kids = cell.get("kids", [])
    if not kids:
        return ""
    raw_text = " ".join(k.get("content", "").strip() for k in kids if "content" in k)
    return clean_city(raw_text)


def extract_table(table: dict) -> list[dict[str, str]]:
    raw_rows = table.get("rows", [])
    if not raw_rows or len(raw_rows) < 2:
        return []

    headers = []
    for cell in raw_rows[0].get("cells", []):
        header_text = _cell_text(cell)
        headers.append(
            header_text
            if header_text
            else f"col_{cell.get('column number', len(headers) + 1)}"
        )

    extracted_rows = []
    for row in raw_rows[1:]:
        row_dict = {h: "" for h in headers}

        for cell in row.get("cells", []):
            col_index = cell.get("column number", 1) - 1
            if col_index < len(headers):
                if col_index == 0:
                    row_dict[headers[col_index]] = _cell_text_city(cell)
                    continue
                row_dict[headers[col_index]] = _cell_text(cell)

        if any(val.strip() for val in row_dict.values()):
            extracted_rows.append(row_dict)

    return extracted_rows


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

    extracted_tables = []
    current_section = "RATES"
    current_context: dict[str, Any] = {}

    def apply_backward(key: str, value: str):
        for tbl in reversed(extracted_tables):
            if tbl["section"] != current_section:
                break
            if not tbl["metadata"].get(key):
                tbl["metadata"][key] = value
            else:
                break

    for node in kids_array:
        ntype = node.get("type", "")

        node_texts = []
        if ntype in {"paragraph", "heading", "caption", "list item"}:
            node_texts.append(clean_text(node.get("content", "").strip()))
        elif ntype == "list":
            for item in node.get("list items", []):
                node_texts.append(clean_text(item.get("content", "").strip()))

        # Evaluate all text found in this node
        for txt in filter(None, node_texts):
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

        # Process Tables
        if ntype == "table":
            table_rows = extract_table(node)
            if table_rows:
                metadata = {
                    k: v for k, v in current_context.items() if not k.startswith("_")
                }
                extracted_tables.append(
                    {
                        "section": current_section,
                        "page_number": node.get("page number") or 1,
                        "metadata": metadata,
                        "rows": table_rows,
                    }
                )

    if header_effective_date:
        for tbl in extracted_tables:
            if not tbl["metadata"].get("effective_date"):
                tbl["metadata"]["effective_date"] = header_effective_date

    return {
        "contract_id": contract_id,
        "carrier": carrier,
        "tables": extracted_tables,
    }
