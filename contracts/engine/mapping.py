from __future__ import annotations

from typing import Any

from contracts.engine.models import MappingResult
from contracts.utils.logger import get_shared_logger

logger = get_shared_logger(__name__)

BASE_COLUMNS_FIRST: list[str] = [
    "Carrier",
    "Contract ID",
    "effective_date",
    "expiration_date",
    "commodity",
]
BASE_COLUMNS_SECOND: list[str] = [
    "service",
    "Remarks",
    "Scope",
    "BaseRate 20",
    "BaseRate 40",
    "BaseRate 40H",
    "BaseRate 45",
]

COLUMNS_RATES = (
    BASE_COLUMNS_FIRST
    + ["origin_city", "origin_via_city", "destination_city", "destination_via_city"]
    + BASE_COLUMNS_SECOND
)
COLUMNS_ORIGIN_ARB = (
    BASE_COLUMNS_FIRST + ["origin_city", "origin_via_city"] + BASE_COLUMNS_SECOND
)
COLUMNS_DEST_ARB = (
    BASE_COLUMNS_FIRST
    + ["destination_city", "destination_via_city"]
    + BASE_COLUMNS_SECOND
)

HEADER_MAP: dict[str, str] = {
    "Term": "service",
    "20'": "BaseRate 20",
    "40'": "BaseRate 40",
    "40HC": "BaseRate 40H",
    "45'": "BaseRate 45",
}

MAPPED_RATE_KEYS = ["BaseRate 20", "BaseRate 40", "BaseRate 40H", "BaseRate 45"]


def map_table(
    table: dict, carrier: str, contract_id: str, section: str
) -> list[dict]:
    rows = table.get("rows", [])
    if not rows:
        return []

    header_map = HEADER_MAP.copy()
    absent_columns = set()

    if section == "ORIGIN_ARBITRARIES":
        header_map["Point"] = "origin_city"
        header_map["Via"] = "origin_via_city"
        absent_columns = {"destination_city", "destination_via_city"}
    elif section == "DESTINATION_ARBITRARIES":
        header_map["Point"] = "destination_city"
        header_map["Via"] = "destination_via_city"
        absent_columns = {"origin_city", "origin_via_city"}
    else:
        header_map["Destination"] = "destination_city"
        header_map["Destination Via"] = "destination_via_city"

    meta = table.get("metadata") or {}
    base_row = {
        "Carrier": carrier,
        "Contract ID": contract_id,
        "effective_date": meta.get("effective_date"),
        "expiration_date": meta.get("expiration_date"),
        "commodity": meta.get("commodity"),
        "Scope": meta.get("Scope"),
        "source_page": table.get("page_number") or 1,
    }

    variable_columns = [
        "origin_city",
        "origin_via_city",
        "destination_city",
        "destination_via_city",
    ]
    for key in variable_columns:
        if key not in absent_columns and meta.get(key):
            base_row[key] = meta.get(key)

    mapped_rows = []
    for row in rows:
        new_row = base_row.copy()
        for raw_key, value in row.items():
            header_key = header_map.get(raw_key, raw_key)
            if header_key in absent_columns:
                continue

            if value:
                if header_key in variable_columns and meta.get(header_key):
                    continue
                new_row[header_key] = value

        has_rate = any(new_row.get(rate_col) for rate_col in MAPPED_RATE_KEYS)
        if has_rate:
            mapped_rows.append(new_row)

    return mapped_rows


def map_payload(data: dict[str, Any]) -> MappingResult:
    carrier = data.get("carrier", "UNKNOWN")
    contract_id = data.get("contract_id", "UNKNOWN")
    result = MappingResult(contract_id=contract_id, carrier=carrier)

    for table in data.get("tables", []):
        section_type = table.get("section", "RATES")
        rows = map_table(table, carrier, contract_id, section_type)

        if section_type == "DESTINATION_ARBITRARIES":
            result.dest_arb.extend(rows)
        elif section_type == "ORIGIN_ARBITRARIES":
            result.origin_arb.extend(rows)
        else:
            result.rates.extend(rows)

    return result
