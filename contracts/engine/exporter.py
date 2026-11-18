import json
import shutil
from pathlib import Path

import pandas as pd

from contracts.engine.mapping import (
    COLUMNS_DEST_ARB,
    COLUMNS_ORIGIN_ARB,
    COLUMNS_RATES,
)
from contracts.engine.models import MappingResult
from contracts.utils.logger import get_shared_logger

logger = get_shared_logger(__name__)


def export_result(result: MappingResult, output_dir: Path | str, stem: str) -> None:
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
            empty_df = pd.DataFrame(columns=COLUMNS_RATES)
            empty_df.to_excel(writer, sheet_name="Rates", index=False)
            empty_df.to_csv(out_dir / f"{stem}_Rates.csv", index=False)
        else:
            for sheet_name, (rows, columns) in buckets.items():
                if not rows:
                    continue
                df = pd.DataFrame(rows).reindex(columns=columns)
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                df.to_csv(out_dir / f"{stem}_{sheet_name}.csv", index=False)

    logger.info("Exported %s -> %s", stem, out_dir)
