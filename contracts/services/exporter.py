from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings

from contracts.engine.exporter import (
    CSV_RECORD_ARBITRARY_CHARGE,
    CSV_RECORD_FREIGHT_RATE,
    build_canonical_payload,
    export_result,
    write_csv_export,
)
from contracts.engine.models import MappingResult
from contracts.models import (
    ArbitraryCharge,
    ContractMetadata,
    EquipmentType,
    ExportRecord,
)

EQUIPMENT_TO_RATE_COLUMN: dict[str, str] = {
    EquipmentType.GP20: "BaseRate 20",
    EquipmentType.GP40: "BaseRate 40",
    EquipmentType.HC40: "BaseRate 40H",
    EquipmentType.HC45: "BaseRate 45",
}

FORMAT_METADATA: dict[str, tuple[str, str]] = {
    "json": (ExportRecord.ExportFormat.JSON, "application/json; charset=utf-8"),
    "xlsx": (
        ExportRecord.ExportFormat.XLSX,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    "csv": (ExportRecord.ExportFormat.CSV, "text/csv; charset=utf-8"),
}

# Every persisted amount is quoted per unit of its equipment_type.
CSV_AMOUNT_BASIS = "PER_CONTAINER"
CSV_FREIGHT_CHARGE_TYPE = "BASE_OCEAN_FREIGHT"
CSV_ARBITRARY_CHARGE_TYPES: dict[str, str] = {
    ArbitraryCharge.ChargeType.ORIGIN: "ORIGIN_ARBITRARY",
    ArbitraryCharge.ChargeType.DESTINATION: "DESTINATION_ARBITRARY",
}


@dataclass(frozen=True)
class ExportedArtifact:
    record: ExportRecord
    file_path: Path
    filename: str
    content_type: str
    content_bytes: bytes


def _base_contract_row(contract: ContractMetadata) -> dict[str, Any]:
    return {
        "Carrier": contract.carrier.carrier_code,
        "Contract ID": contract.contract_number,
        "effective_date": contract.effective_date.isoformat(),
        "expiration_date": contract.expiration_date.isoformat(),
        "commodity": contract.commodity_desc,
        "Scope": contract.trade_scope,
    }


def _format_port_label(code: str, name: str) -> str:
    clean_name = (name or "").strip()
    clean_code = (code or "").strip()
    if clean_name and clean_code and clean_code not in clean_name.upper():
        return f"{clean_name} ({clean_code})"
    return clean_name or clean_code


def build_mapping_result_from_contract(contract: ContractMetadata) -> MappingResult:
    """Reconstruct a canonical MappingResult payload from normalized PostgreSQL rows."""
    base = _base_contract_row(contract)

    # Group normalized FreightRate rows by lane + currency + source pages into wide rows
    rate_rows: list[dict[str, Any]] = []
    rate_buckets: dict[tuple[Any, ...], dict[str, Any]] = {}

    for rate in contract.freight_rates.order_by("line_item_sequence"):
        col_key = EQUIPMENT_TO_RATE_COLUMN.get(rate.equipment_type)
        lane_key = (
            rate.origin_port_code,
            rate.origin_port_name,
            rate.destination_port_code,
            rate.destination_port_name,
            rate.currency_code,
            rate.source_page_start,
            rate.source_page_end,
        )

        if col_key:
            bucket = rate_buckets.get(lane_key)
            if bucket is None or col_key in bucket:
                bucket = {
                    **base,
                    "origin_city": _format_port_label(
                        rate.origin_port_code, rate.origin_port_name
                    ),
                    "origin_via_city": "",
                    "destination_city": _format_port_label(
                        rate.destination_port_code, rate.destination_port_name
                    ),
                    "destination_via_city": "",
                    "service": "CY",
                    "Remarks": f"Currency: {rate.currency_code}",
                    "Cur": rate.currency_code,
                }
                rate_buckets[lane_key] = bucket
                rate_rows.append(bucket)
            bucket[col_key] = str(rate.rate_amount)
        else:
            rate_rows.append(
                {
                    **base,
                    "origin_city": _format_port_label(
                        rate.origin_port_code, rate.origin_port_name
                    ),
                    "origin_via_city": "",
                    "destination_city": _format_port_label(
                        rate.destination_port_code, rate.destination_port_name
                    ),
                    "destination_via_city": "",
                    "service": rate.equipment_type,
                    "Remarks": f"{rate.equipment_type}: {rate.currency_code} {rate.rate_amount}",
                    "Cur": rate.currency_code,
                }
            )

    origin_arb_rows: list[dict[str, Any]] = []
    dest_arb_rows: list[dict[str, Any]] = []
    arb_buckets: dict[tuple[Any, ...], dict[str, Any]] = {}

    for charge in contract.arbitrary_charges.order_by("line_item_sequence"):
        is_origin = charge.charge_type == ArbitraryCharge.ChargeType.ORIGIN
        col_key = EQUIPMENT_TO_RATE_COLUMN.get(charge.equipment_type)
        arb_key = (
            charge.charge_type,
            charge.location_code,
            charge.location_name,
            charge.via_gateway_port,
            charge.currency_code,
            charge.transport_mode,
            charge.source_page_num,
        )

        target_list = origin_arb_rows if is_origin else dest_arb_rows
        loc_field = "origin_city" if is_origin else "destination_city"
        via_field = "origin_via_city" if is_origin else "destination_via_city"

        if col_key:
            bucket = arb_buckets.get(arb_key)
            if bucket is None or col_key in bucket:
                bucket = {
                    **base,
                    loc_field: _format_port_label(
                        charge.location_code, charge.location_name
                    ),
                    via_field: charge.via_gateway_port,
                    "service": charge.transport_mode,
                    "Remarks": f"Currency: {charge.currency_code}",
                    "Cur": charge.currency_code,
                }
                arb_buckets[arb_key] = bucket
                target_list.append(bucket)
            bucket[col_key] = str(charge.charge_amount)
        else:
            target_list.append(
                {
                    **base,
                    loc_field: _format_port_label(
                        charge.location_code, charge.location_name
                    ),
                    via_field: charge.via_gateway_port,
                    "service": f"{charge.transport_mode} ({charge.equipment_type})",
                    "Remarks": f"{charge.equipment_type}: {charge.currency_code} {charge.charge_amount}",
                    "Cur": charge.currency_code,
                }
            )

    return MappingResult(
        contract_id=contract.contract_number,
        carrier=contract.carrier.carrier_name,
        rates=rate_rows,
        origin_arb=origin_arb_rows,
        dest_arb=dest_arb_rows,
    )


def build_csv_records_from_contract(contract: ContractMetadata) -> list[dict[str, Any]]:
    """
    Flatten a contract into one CSV record per FreightRate row followed by one per
    ArbitraryCharge row (origin and destination), each in line_item_sequence order.
    """
    base = {
        "carrier_code": contract.carrier.carrier_code,
        "carrier_name": contract.carrier.carrier_name,
        "contract_number": contract.contract_number,
        "trade_scope": contract.trade_scope,
        "commodity_desc": contract.commodity_desc,
        "effective_date": contract.effective_date.isoformat(),
        "expiration_date": contract.expiration_date.isoformat(),
    }

    records: list[dict[str, Any]] = []
    for rate in contract.freight_rates.order_by("line_item_sequence"):
        records.append(
            {
                "record_type": CSV_RECORD_FREIGHT_RATE,
                **base,
                "line_item_sequence": rate.line_item_sequence,
                "origin_port_code": rate.origin_port_code,
                "origin_port_name": rate.origin_port_name,
                "destination_port_code": rate.destination_port_code,
                "destination_port_name": rate.destination_port_name,
                "charge_type": CSV_FREIGHT_CHARGE_TYPE,
                "basis": CSV_AMOUNT_BASIS,
                "equipment_type": rate.equipment_type,
                "currency_code": rate.currency_code,
                "amount": str(rate.rate_amount),
                "source_page_start": rate.source_page_start,
                "source_page_end": rate.source_page_end,
                "confidence_score": str(rate.confidence_score),
            }
        )

    for charge in contract.arbitrary_charges.order_by("line_item_sequence"):
        records.append(
            {
                "record_type": CSV_RECORD_ARBITRARY_CHARGE,
                **base,
                "line_item_sequence": charge.line_item_sequence,
                "direction": charge.charge_type,
                "location_code": charge.location_code,
                "location_name": charge.location_name,
                "via_gateway_port": charge.via_gateway_port,
                "transport_mode": charge.transport_mode,
                "charge_type": CSV_ARBITRARY_CHARGE_TYPES.get(
                    charge.charge_type, charge.charge_type
                ),
                "basis": CSV_AMOUNT_BASIS,
                "equipment_type": charge.equipment_type,
                "currency_code": charge.currency_code,
                "amount": str(charge.charge_amount),
                "source_page_start": charge.source_page_num,
                "source_page_end": charge.source_page_num,
                "confidence_score": str(charge.confidence_score),
            }
        )

    return records


def build_contract_api_payload(contract: ContractMetadata) -> dict[str, Any]:
    """
    JSON body for GET /api/v1/contracts/<pk> (F-11): document identity, carrier,
    contract metadata, the normalized FreightRate / ArbitraryCharge rows, and the
    same canonical structure the JSON export writes (F-09). Amounts and scores
    are strings so decimals survive JSON unchanged.
    """
    document = contract.document
    return {
        "contract_id": contract.pk,
        "document_id": document.pk,
        "batch_id": document.batch_id,
        "document_status": document.status,
        "original_file_name": document.original_file_name,
        "file_hash_sha256": document.file_hash_sha256,
        "page_count": document.page_count,
        "carrier": {
            "carrier_code": contract.carrier.carrier_code,
            "carrier_name": contract.carrier.carrier_name,
        },
        "metadata": {
            "contract_number": contract.contract_number,
            "trade_scope": contract.trade_scope,
            "commodity_desc": contract.commodity_desc,
            "effective_date": contract.effective_date.isoformat(),
            "expiration_date": contract.expiration_date.isoformat(),
            "extracted_at": contract.extracted_at.isoformat(),
        },
        "freight_rates": [
            {
                "rate_id": rate.pk,
                "line_item_sequence": rate.line_item_sequence,
                "origin_port_code": rate.origin_port_code,
                "origin_port_name": rate.origin_port_name,
                "destination_port_code": rate.destination_port_code,
                "destination_port_name": rate.destination_port_name,
                "equipment_type": rate.equipment_type,
                "currency_code": rate.currency_code,
                "rate_amount": str(rate.rate_amount),
                "source_page_start": rate.source_page_start,
                "source_page_end": rate.source_page_end,
                "confidence_score": str(rate.confidence_score),
            }
            for rate in contract.freight_rates.order_by("line_item_sequence")
        ],
        "arbitrary_charges": [
            {
                "charge_id": charge.pk,
                "line_item_sequence": charge.line_item_sequence,
                "charge_type": charge.charge_type,
                "location_code": charge.location_code,
                "location_name": charge.location_name,
                "via_gateway_port": charge.via_gateway_port,
                "transport_mode": charge.transport_mode,
                "equipment_type": charge.equipment_type,
                "currency_code": charge.currency_code,
                "charge_amount": str(charge.charge_amount),
                "source_page_num": charge.source_page_num,
                "confidence_score": str(charge.confidence_score),
            }
            for charge in contract.arbitrary_charges.order_by("line_item_sequence")
        ],
        "canonical": build_canonical_payload(build_mapping_result_from_contract(contract)),
    }


def export_contract_artifact(
    contract: ContractMetadata,
    user,
    fmt: str,
) -> ExportedArtifact:
    """
    Generate a JSON or XLSX artifact via contracts.engine.exporter.export_result(),
    or a unified freight-rate + arbitrary-charge CSV via write_csv_export(), from
    the contract's database rows, and log an ExportRecord row.
    """
    fmt_key = (fmt or "").strip().lower()
    if fmt_key not in FORMAT_METADATA:
        raise ValueError(f"Unsupported export format: {fmt}")

    export_format, content_type = FORMAT_METADATA[fmt_key]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", contract.contract_number).strip("_")
    if not stem:
        stem = f"contract_{contract.pk}"

    media_root = Path(settings.MEDIA_ROOT)
    export_dir = (
        media_root
        / "contracts"
        / "exports"
        / f"contract_{contract.pk}_{uuid.uuid4().hex[:8]}"
    )

    target_file = export_dir / f"{stem}_mapped.{fmt_key}"
    if fmt_key == "csv":
        write_csv_export(build_csv_records_from_contract(contract), target_file)
    else:
        export_result(build_mapping_result_from_contract(contract), export_dir, stem)

    rel_path = target_file.relative_to(media_root).as_posix()[:255]
    record = ExportRecord.objects.create(
        user=user,
        contract=contract,
        export_format=export_format,
        file_path=rel_path,
    )

    return ExportedArtifact(
        record=record,
        file_path=target_file,
        filename=target_file.name,
        content_type=content_type,
        content_bytes=target_file.read_bytes(),
    )
