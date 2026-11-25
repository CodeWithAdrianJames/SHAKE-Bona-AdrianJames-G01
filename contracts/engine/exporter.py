import csv
import json
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from contracts.engine.mapping import (
    COLUMNS_DEST_ARB,
    COLUMNS_ORIGIN_ARB,
    COLUMNS_RATES,
)
from contracts.engine.models import MappingResult
from contracts.utils.logger import get_shared_logger

logger = get_shared_logger(__name__)

# Discriminator values for the unified CSV export (F-09).
CSV_RECORD_FREIGHT_RATE = "FREIGHT_RATE"
CSV_RECORD_ARBITRARY_CHARGE = "ARBITRARY_CHARGE"

# One CSV row per persisted FreightRate / ArbitraryCharge row. Columns that do not
# apply to a record type are left blank so both record types share one header.
COLUMNS_CSV_EXPORT: list[str] = [
    "record_type",
    "carrier_code",
    "carrier_name",
    "contract_number",
    "trade_scope",
    "commodity_desc",
    "effective_date",
    "expiration_date",
    "line_item_sequence",
    # FREIGHT_RATE lane
    "origin_port_code",
    "origin_port_name",
    "destination_port_code",
    "destination_port_name",
    # ARBITRARY_CHARGE leg
    "direction",
    "location_code",
    "location_name",
    "via_gateway_port",
    "transport_mode",
    # Shared charge / amount fields
    "charge_type",
    "basis",
    "equipment_type",
    "currency_code",
    "amount",
    "source_page_start",
    "source_page_end",
    "confidence_score",
]


def write_csv_export(
    records: Iterable[Mapping[str, Any]], output_path: Path | str
) -> Path:
    """
    Write an RFC-4180 CSV with the COLUMNS_CSV_EXPORT header followed by one line
    per record. The header is always written, so an empty record set still
    yields a valid file. Unknown keys raise ValueError instead of being dropped.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=COLUMNS_CSV_EXPORT,
            restval="",
            extrasaction="raise",
            lineterminator="\r\n",
        )
        writer.writeheader()
        for record in records:
            writer.writerow(record)
    logger.info("Exported CSV -> %s", path)
    return path


def export_result(result: MappingResult, output_dir: Path | str, stem: str) -> None:
    """Write the canonical JSON payload and the multi-sheet XLSX workbook."""
    out_dir = Path(output_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    buckets = {
        "Rates": (result.rates, COLUMNS_RATES),
        "Origin_Arbitraries": (result.origin_arb, COLUMNS_ORIGIN_ARB),
        "Destination_Arbitraries": (result.dest_arb, COLUMNS_DEST_ARB),
    }

    payload = {
        "carrier": result.carrier,
        "contract_id": result.contract_id,
        "Rates": result.rates,
        "Origin_Arbitraries": result.origin_arb,
        "Destination_Arbitraries": result.dest_arb,
    }
    (out_dir / f"{stem}_mapped.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    has_any_rows = any(bool(rows) for rows, _ in buckets.values())

    excel_path = out_dir / f"{stem}_mapped.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        if not has_any_rows:
            pd.DataFrame(columns=COLUMNS_RATES).to_excel(
                writer, sheet_name="Rates", index=False
            )
        else:
            for sheet_name, (rows, columns) in buckets.items():
                if not rows:
                    continue
                df = pd.DataFrame(rows).reindex(columns=columns)
                df.to_excel(writer, sheet_name=sheet_name, index=False)

    logger.info("Exported %s -> %s", stem, out_dir)
