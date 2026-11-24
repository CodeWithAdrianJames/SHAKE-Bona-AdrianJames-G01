from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

import pymupdf
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from contracts.engine.errors import IngestionError, ShakeError, UnsupportedDocumentError
from contracts.engine.extraction import extract
from contracts.engine.ingestion import classify_document, ingest_file
from contracts.engine.mapping import map_payload
from contracts.engine.models import DocumentType, IngestedDocument, MappingResult
from contracts.models import (
    ArbitraryCharge,
    BatchUpload,
    CarrierProfile,
    ContractMetadata,
    DocumentFile,
    EquipmentType,
    FreightRate,
    ProcessingJob,
)
from contracts.utils.logger import get_shared_logger

logger = get_shared_logger(__name__)

DEFAULT_CARRIERS: tuple[tuple[str, str, str], ...] = (
    ("MSCU", "Mediterranean Shipping Company", "v1.0"),
    ("CMDU", "CMA CGM", "v1.0"),
    ("COSU", "COSCO SHIPPING", "v1.0"),
    ("MAEU", "Maersk", "v1.0"),
    ("UNKN", "General / Unassigned Carrier", "v1.0"),
)

RATE_COLUMN_TO_EQUIPMENT: tuple[tuple[str, str], ...] = (
    ("BaseRate 20", EquipmentType.GP20),
    ("BaseRate 40", EquipmentType.GP40),
    ("BaseRate 40H", EquipmentType.HC40),
    ("BaseRate 45", EquipmentType.HC45),
)

KNOWN_PORT_CODES: dict[str, str] = {
    "ATLANTA": "USATL",
    "ANTWERP": "BEANR",
    "BUSAN": "KRPUS",
    "CEBU": "PHCEB",
    "CHARLESTON": "USCHS",
    "CHARLOTTE": "USCLT",
    "DALIAN": "CNDLC",
    "HAMBURG": "DEHAM",
    "HONG KONG": "HKHKG",
    "HOUSTON": "USHOU",
    "KAOHSIUNG": "TWKHH",
    "KEELUNG": "TWKEL",
    "KOBE": "JPUKB",
    "LIRQUEN": "CLLQN",
    "LONG BEACH": "USLGB",
    "LOS ANGELES": "USLAX",
    "MANILA": "PHMNL",
    "MIAMI": "USMIA",
    "NEW YORK": "USNYC",
    "NINGBO": "CNNGB",
    "NORFOLK": "USORF",
    "OAKLAND": "USOAK",
    "OSAKA": "JPOSA",
    "QINGDAO": "CNTAO",
    "ROTTERDAM": "NLRTM",
    "SAVANNAH": "USSAV",
    "SEATTLE": "USSEA",
    "SHANGHAI": "CNSHA",
    "SHENZHEN": "CNSZX",
    "SINGAPORE": "SGSIN",
    "TACOMA": "USTIW",
    "TOKYO": "JPTYO",
    "VANCOUVER": "CAVAN",
    "XIAMEN": "CNXMN",
    "YANTIAN": "CNYTN",
    "YOKOHAMA": "JPYOK",
}


class DuplicateDocumentError(ShakeError):
    """Raised when an uploaded PDF matches an existing SHA-256 checksum (BR-06)."""


@dataclass
class ValidatedUploadPayload:
    original_name: str
    content: bytes
    file_size_bytes: int
    sha256_hex: str
    page_count: int


@dataclass
class BatchIngestionOutcome:
    batch: BatchUpload | None = None
    succeeded: list[ContractMetadata] = field(default_factory=list)
    failed_documents: list[tuple[str, str]] = field(default_factory=list)
    rejected_files: list[tuple[str, str]] = field(default_factory=list)


def ensure_default_carriers() -> None:
    """Ensure the standard shipping carrier profiles (including UNKN fallback) exist."""
    for code, name, version in DEFAULT_CARRIERS:
        CarrierProfile.objects.get_or_create(
            carrier_code=code,
            defaults={
                "carrier_name": name,
                "template_version": version,
                "is_active": True,
            },
        )


def resolve_carrier(raw_carrier: str | None) -> CarrierProfile:
    """
    Resolve an extracted carrier string against active CarrierProfile records,
    falling back to UNKN so BR-11 is always satisfied.
    """
    ensure_default_carriers()
    active_carriers = list(CarrierProfile.objects.filter(is_active=True))
    cleaned = (raw_carrier or "").strip()
    upper = cleaned.upper()

    if upper:
        for profile in active_carriers:
            if profile.carrier_code.upper() == upper:
                return profile

        for profile in active_carriers:
            if (
                profile.carrier_code != "UNKN"
                and (
                    profile.carrier_code.upper() in upper
                    or profile.carrier_name.upper() in upper
                    or upper in profile.carrier_name.upper()
                )
            ):
                return profile

        alias_map = {
            "MSC": "MSCU",
            "MEDITERRANEAN": "MSCU",
            "CMA": "CMDU",
            "COSCO": "COSU",
            "MAERSK": "MAEU",
        }
        for keyword, target_code in alias_map.items():
            if keyword in upper:
                match = next(
                    (p for p in active_carriers if p.carrier_code == target_code),
                    None,
                )
                if match:
                    return match

    fallback = CarrierProfile.objects.filter(carrier_code="UNKN").first()
    if fallback:
        return fallback
    return CarrierProfile.objects.first()


def normalize_port_code(port_name: str | None, fallback: str = "UNSPEC") -> tuple[str, str]:
    """Normalize a port/city string to a <=10-char uppercase code and clean display name."""
    cleaned = re.sub(r"\s+", " ", (port_name or "").strip(" ,;-"))
    if not cleaned:
        return fallback, "Unspecified Location"

    upper = cleaned.upper()
    if upper in KNOWN_PORT_CODES:
        return KNOWN_PORT_CODES[upper], cleaned[:100]

    for known_name, unlocode in KNOWN_PORT_CODES.items():
        if known_name in upper:
            return unlocode, cleaned[:100]

    if re.fullmatch(r"[A-Z]{5}", upper):
        return upper, cleaned[:100]

    alnum = re.sub(r"[^A-Z0-9]", "", upper)
    code = alnum[:10] if alnum else fallback
    return code, cleaned[:100]


def parse_contract_date(raw_value: str | None) -> date | None:
    """Parse extracted date strings across MM/DD/YYYY, YYYY-MM-DD, and YYYYMMDD."""
    if not raw_value:
        return None
    text = raw_value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal_amount(raw_value: Any) -> Decimal | None:
    """Parse monetary rate/charge strings into Decimal, returning None for blanks or non-numbers."""
    if raw_value is None:
        return None
    if isinstance(raw_value, Decimal):
        return raw_value
    text = str(raw_value).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    if not cleaned or cleaned in {".", "-", "-."}:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _infer_transport_mode(row: dict[str, Any]) -> str:
    combined = " ".join(
        str(row.get(k, "") or "") for k in ("service", "Remarks", "Note", "Mode")
    ).upper()
    for mode in (
        ArbitraryCharge.TransportMode.RAIL,
        ArbitraryCharge.TransportMode.TRUCK,
        ArbitraryCharge.TransportMode.BARGE,
        ArbitraryCharge.TransportMode.FEEDER,
    ):
        if mode in combined:
            return mode
    return ArbitraryCharge.TransportMode.INTERMODAL


def _row_page_span(row: dict[str, Any]) -> tuple[int, int]:
    """
    Resolve a mapped row's (source_page_start, source_page_end), keeping
    end >= start. Accepts the legacy single ``source_page`` key as a fallback.
    """
    start = max(1, int(row.get("source_page_start") or row.get("source_page") or 1))
    end = max(start, int(row.get("source_page_end") or start))
    return start, end


def _extract_currency(row: dict[str, Any]) -> str:
    raw = (
        row.get("Cur")
        or row.get("Currency")
        or row.get("currency")
        or row.get("currency_code")
        or "USD"
    )
    cleaned = re.sub(r"[^A-Z]", "", str(raw).strip().upper())
    return cleaned[:3] if len(cleaned) == 3 else "USD"


def _generate_batch_number() -> str:
    today_prefix = f"BATCH-{timezone.localdate().strftime('%Y%m%d')}-"
    existing_count = BatchUpload.objects.filter(
        batch_number__startswith=today_prefix
    ).count()
    seq = existing_count + 1
    while True:
        candidate = f"{today_prefix}{seq:03d}"
        if not BatchUpload.objects.filter(batch_number=candidate).exists():
            return candidate
        seq += 1


def _words_in_rect(words: list[tuple], rect: pymupdf.Rect) -> str:
    """Join the page words whose centers fall inside ``rect`` in reading order."""
    inside = [
        w
        for w in words
        if pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2) in rect
    ]
    inside.sort(key=lambda w: (w[5], w[6], w[7]))  # block, line, word numbers
    return " ".join(w[4] for w in inside)


def _pymupdf_table_node(
    table: Any, page_number: int, words: list[tuple]
) -> dict[str, Any] | None:
    """Convert a PyMuPDF table into an OpenDataLoader-shaped AST table node."""
    raw_rows = table.extract() or []
    if len(raw_rows) < 2:
        return None

    ast_rows = []
    for row_idx, row in enumerate(raw_rows):
        row_cells = table.rows[row_idx].cells if row_idx < len(table.rows) else []
        cells = []
        for col_idx, cell_val in enumerate(row, start=1):
            bbox = row_cells[col_idx - 1] if col_idx - 1 < len(row_cells) else None
            # table.extract() can drop inter-word spaces ("HONGKONG"), so rebuild
            # the text from positioned words whenever the cell geometry is known.
            text = _words_in_rect(words, pymupdf.Rect(bbox)) if bbox else str(cell_val or "")
            cell: dict[str, Any] = {
                "column number": col_idx,
                "kids": [{"content": " ".join(text.split())}],
            }
            if bbox:
                # Only x-coordinates are compared across pages, so the top-left
                # origin of PyMuPDF does not need converting to PDF space.
                cell["bounding box"] = [float(v) for v in bbox]
            cells.append(cell)
        ast_rows.append({"cells": cells})

    return {
        "type": "table",
        "page number": page_number,
        "bounding box": [float(v) for v in table.bbox],
        "number of columns": max(len(r) for r in raw_rows),
        "rows": ast_rows,
    }


def _build_pymupdf_fallback_document(pdf_path: Path) -> IngestedDocument:
    """
    Fallback AST builder using PyMuPDF when Java/OpenDataLoader is unavailable (Q6).

    Emits text lines and tables in top-to-bottom reading order per page, excludes
    text that sits inside a detected table, and records cell bounding boxes so
    cross-page stitching can compare column alignment (F-04).
    """
    kids: list[dict[str, Any]] = []
    md_parts: list[str] = []

    with pymupdf.open(str(pdf_path)) as pdf_doc:
        total_pages = len(pdf_doc)
        for idx, page in enumerate(pdf_doc, start=1):
            md_parts.append(page.get_text("text") or "")
            positioned: list[tuple[float, float, dict[str, Any]]] = []
            table_rects: list[pymupdf.Rect] = []

            try:
                words = page.get_text("words")
                for table in page.find_tables().tables:
                    node = _pymupdf_table_node(table, idx, words)
                    if node is None:
                        continue
                    rect = pymupdf.Rect(table.bbox)
                    table_rects.append(rect)
                    positioned.append((rect.y0, rect.x0, node))
            except Exception as exc:
                logger.warning("PyMuPDF table fallback failed on page %d: %s", idx, exc)

            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    content = "".join(span.get("text", "") for span in line.get("spans", []))
                    content = content.strip()
                    if not content:
                        continue
                    rect = pymupdf.Rect(line["bbox"])
                    center = pymupdf.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
                    if any(center in table_rect for table_rect in table_rects):
                        continue
                    positioned.append(
                        (
                            rect.y0,
                            rect.x0,
                            {
                                "type": "paragraph",
                                "page number": idx,
                                "bounding box": [rect.x0, rect.y0, rect.x1, rect.y1],
                                "content": content,
                            },
                        )
                    )

            positioned.sort(key=lambda item: (item[0], item[1]))
            kids.extend(node for _, _, node in positioned)

    return IngestedDocument(
        source_path=pdf_path,
        doc_type=DocumentType.DIGITAL_PDF,
        total_pages=total_pages,
        json={"number of pages": total_pages, "kids": kids},
        markdown="\n".join(md_parts),
    )


def validate_uploaded_file(uploaded_file) -> ValidatedUploadPayload:
    """
    Validate extension, non-zero byte size (BR-08), SHA-256 uniqueness (BR-06),
    and digital vector-text PDF classification.
    """
    original_name = Path(getattr(uploaded_file, "name", "document.pdf")).name
    if Path(original_name).suffix.lower() != ".pdf":
        raise UnsupportedDocumentError(
            f"Unsupported file '{original_name}': only .pdf contract files are allowed."
        )

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    content = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)

    file_size = len(content)
    if file_size <= 0:
        raise UnsupportedDocumentError(
            f"Empty file '{original_name}': uploaded PDF must be non-empty (BR-08)."
        )

    sha256_hex = hashlib.sha256(content).hexdigest()
    if DocumentFile.objects.filter(file_hash_sha256=sha256_hex).exists():
        raise DuplicateDocumentError(
            f"Duplicate PDF blocked (BR-06): '{original_name}' has already been ingested "
            f"(SHA-256: {sha256_hex[:12]}...)."
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_pdf = Path(tmp_dir) / original_name
        tmp_pdf.write_bytes(content)

        doc_type = classify_document(tmp_pdf)
        if doc_type != DocumentType.DIGITAL_PDF:
            raise UnsupportedDocumentError(
                f"Rejected '{original_name}': scanned PDFs or low-text images are not supported. "
                "Please upload a digitally generated vector-text PDF."
            )

        try:
            with pymupdf.open(str(tmp_pdf)) as pdf_doc:
                page_count = len(pdf_doc)
        except Exception as exc:
            raise UnsupportedDocumentError(
                f"Could not read '{original_name}' as a valid PDF: {exc}"
            ) from exc

        if page_count <= 0:
            raise UnsupportedDocumentError(
                f"Rejected '{original_name}': PDF must contain at least 1 page (BR-08)."
            )

    return ValidatedUploadPayload(
        original_name=original_name,
        content=content,
        file_size_bytes=file_size,
        sha256_hex=sha256_hex,
        page_count=page_count,
    )


def _run_engine_on_bytes(payload: ValidatedUploadPayload) -> tuple[IngestedDocument, dict[str, Any], MappingResult]:
    """Run OpenDataLoader ingestion (with PyMuPDF fallback on Java errors), extraction, and mapping."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        tmp_pdf = tmp_dir_path / payload.original_name
        tmp_pdf.write_bytes(payload.content)
        ast_out = tmp_dir_path / "ast_output"

        try:
            ingested_doc = ingest_file(tmp_pdf, ast_out)
        except IngestionError as exc:
            logger.warning(
                "OpenDataLoader failed for %s (%s); using PyMuPDF fallback.",
                payload.original_name,
                exc,
            )
            ingested_doc = _build_pymupdf_fallback_document(tmp_pdf)

        extracted = extract(ingested_doc, filename_stem=Path(payload.original_name).stem)
        mapped = map_payload(extracted)
        return ingested_doc, extracted, mapped


def _determine_contract_dates(mapped: MappingResult) -> tuple[date, date]:
    """Determine contract-level effective and expiration dates satisfying BR-10 (Q5)."""
    eff_dates: list[date] = []
    exp_dates: list[date] = []

    for row in (*mapped.rates, *mapped.origin_arb, *mapped.dest_arb):
        eff = parse_contract_date(row.get("effective_date"))
        exp = parse_contract_date(row.get("expiration_date"))
        if eff:
            eff_dates.append(eff)
        if exp:
            exp_dates.append(exp)

    effective_date = min(eff_dates) if eff_dates else timezone.localdate()
    expiration_date = max(exp_dates) if exp_dates else effective_date
    if expiration_date < effective_date:
        expiration_date = effective_date
    return effective_date, expiration_date


def _determine_contract_summary(mapped: MappingResult) -> tuple[str, str]:
    """Extract representative trade_scope and commodity_desc from mapped rows."""
    scopes = [
        str(r["Scope"]).strip()
        for r in (*mapped.rates, *mapped.origin_arb, *mapped.dest_arb)
        if r.get("Scope")
    ]
    commodities = [
        str(r["commodity"]).strip()
        for r in (*mapped.rates, *mapped.origin_arb, *mapped.dest_arb)
        if r.get("commodity")
    ]
    trade_scope = scopes[0][:255] if scopes else "Ocean Freight Service Contract"
    commodity_desc = (
        commodities[0] if commodities else "General Freight / Unspecified Commodity"
    )
    return trade_scope, commodity_desc


def persist_mapped_contract(
    document: DocumentFile,
    mapped: MappingResult,
    carrier_override_code: str | None = None,
) -> ContractMetadata:
    """
    Persist ContractMetadata plus unpivoted FreightRate and ArbitraryCharge ORM rows.
    """
    if carrier_override_code and carrier_override_code != "AUTO":
        carrier = (
            CarrierProfile.objects.filter(
                carrier_code=carrier_override_code, is_active=True
            ).first()
            or resolve_carrier(mapped.carrier)
        )
    else:
        carrier = resolve_carrier(mapped.carrier)

    contract_number = (
        mapped.contract_id
        if mapped.contract_id and mapped.contract_id != "UNKNOWN"
        else Path(document.original_file_name).stem[:100]
    )
    effective_date, expiration_date = _determine_contract_dates(mapped)
    trade_scope, commodity_desc = _determine_contract_summary(mapped)

    contract = ContractMetadata.objects.create(
        document=document,
        carrier=carrier,
        contract_number=contract_number[:100],
        trade_scope=trade_scope,
        commodity_desc=commodity_desc,
        effective_date=effective_date,
        expiration_date=expiration_date,
    )

    freight_rows: list[FreightRate] = []
    rate_seq = 1
    for row in mapped.rates:
        raw_origin = row.get("origin_city")
        raw_dest = row.get("destination_city")
        if not raw_origin and not raw_dest:
            continue

        orig_code, orig_name = normalize_port_code(raw_origin, fallback="UNSPEC")
        dest_code, dest_name = normalize_port_code(raw_dest, fallback="UNSPEC")
        if orig_code == dest_code:
            continue

        currency = _extract_currency(row)
        page_start, page_end = _row_page_span(row)

        for col_key, eq_type in RATE_COLUMN_TO_EQUIPMENT:
            amount = parse_decimal_amount(row.get(col_key))
            if amount is None or amount <= Decimal("0.00"):
                continue

            freight_rows.append(
                FreightRate(
                    contract=contract,
                    line_item_sequence=rate_seq,
                    origin_port_code=orig_code,
                    origin_port_name=orig_name,
                    destination_port_code=dest_code,
                    destination_port_name=dest_name,
                    equipment_type=eq_type,
                    currency_code=currency,
                    rate_amount=amount.quantize(Decimal("0.01")),
                    source_page_start=page_start,
                    source_page_end=page_end,
                    confidence_score=Decimal("0.950"),
                )
            )
            rate_seq += 1

    if freight_rows:
        FreightRate.objects.bulk_create(freight_rows)

    arb_rows: list[ArbitraryCharge] = []
    arb_seq = 1
    arb_sources = (
        (ArbitraryCharge.ChargeType.ORIGIN, mapped.origin_arb, "origin_city", "origin_via_city"),
        (
            ArbitraryCharge.ChargeType.DESTINATION,
            mapped.dest_arb,
            "destination_city",
            "destination_via_city",
        ),
    )
    for charge_type, source_rows, loc_key, via_key in arb_sources:
        for row in source_rows:
            loc_code, loc_name = normalize_port_code(row.get(loc_key), fallback="INLAND")
            via_gateway = re.sub(
                r"\s+", " ", str(row.get(via_key) or "DIRECT").strip()
            )[:100]
            currency = _extract_currency(row)
            transport_mode = _infer_transport_mode(row)
            page_num, _ = _row_page_span(row)

            for col_key, eq_type in RATE_COLUMN_TO_EQUIPMENT:
                amount = parse_decimal_amount(row.get(col_key))
                if amount is None or amount < Decimal("0.00"):
                    continue

                arb_rows.append(
                    ArbitraryCharge(
                        contract=contract,
                        line_item_sequence=arb_seq,
                        charge_type=charge_type,
                        location_code=loc_code,
                        location_name=loc_name,
                        via_gateway_port=via_gateway or "DIRECT",
                        equipment_type=eq_type,
                        currency_code=currency,
                        charge_amount=amount.quantize(Decimal("0.01")),
                        transport_mode=transport_mode,
                        source_page_num=page_num,
                        confidence_score=Decimal("0.950"),
                    )
                )
                arb_seq += 1

    if arb_rows:
        ArbitraryCharge.objects.bulk_create(arb_rows)

    return contract


def ingest_uploaded_files(
    user,
    uploaded_files: Iterable[Any],
    carrier_override_code: str | None = None,
    runner=None,
) -> BatchIngestionOutcome:
    """
    Validate, hash-deduplicate, extract, and persist a batch of uploaded contract PDFs.
    """
    engine_runner = runner or _run_engine_on_bytes
    ensure_default_carriers()
    outcome = BatchIngestionOutcome()

    validated_payloads: list[ValidatedUploadPayload] = []
    seen_hashes_in_batch: set[str] = set()

    for uploaded_file in uploaded_files:
        name = Path(getattr(uploaded_file, "name", "document.pdf")).name
        try:
            payload = validate_uploaded_file(uploaded_file)
            if payload.sha256_hex in seen_hashes_in_batch:
                raise DuplicateDocumentError(
                    f"Duplicate PDF blocked (BR-06): '{name}' appears multiple times in the same upload."
                )
            seen_hashes_in_batch.add(payload.sha256_hex)
            validated_payloads.append(payload)
        except ShakeError as exc:
            outcome.rejected_files.append((name, str(exc)))

    if not validated_payloads:
        return outcome

    batch = BatchUpload.objects.create(
        user=user,
        batch_number=_generate_batch_number(),
        total_files=len(validated_payloads),
        status=BatchUpload.Status.PROCESSING,
    )
    outcome.batch = batch

    for payload in validated_payloads:
        try:
            with transaction.atomic():
                document = DocumentFile.objects.create(
                    batch=batch,
                    uploaded_file=ContentFile(payload.content, name=payload.original_name),
                    original_file_name=payload.original_name,
                    file_hash_sha256=payload.sha256_hex,
                    file_size_bytes=payload.file_size_bytes,
                    page_count=payload.page_count,
                    status=DocumentFile.Status.PARSING,
                )
                job = ProcessingJob.objects.create(
                    document=document,
                    job_type=ProcessingJob.JobType.FULL_PIPELINE,
                    status=ProcessingJob.Status.RUNNING,
                )

                try:
                    _, _, mapped = engine_runner(payload)
                    document.status = DocumentFile.Status.STITCHING
                    document.save(update_fields=["status"])

                    contract = persist_mapped_contract(
                        document=document,
                        mapped=mapped,
                        carrier_override_code=carrier_override_code,
                    )

                    document.status = DocumentFile.Status.EXTRACTED
                    document.save(update_fields=["status"])

                    job.status = ProcessingJob.Status.COMPLETED
                    job.completed_at = timezone.now()
                    job.save(update_fields=["status", "completed_at"])

                    outcome.succeeded.append(contract)
                except Exception as inner_exc:
                    logger.exception(
                        "Pipeline extraction failed for %s", payload.original_name
                    )
                    # Roll back partial ContractMetadata/rates via savepoint if needed,
                    # then record FAILED status cleanly outside the inner atomic block.
                    raise RuntimeError(str(inner_exc)) from inner_exc
        except IntegrityError as exc:
            outcome.failed_documents.append(
                (payload.original_name, f"Database integrity error: {exc}")
            )
        except Exception as exc:
            # Record clean FAILED DocumentFile + ProcessingJob diagnostic without orphaned ContractMetadata
            try:
                with transaction.atomic():
                    failed_doc = DocumentFile.objects.create(
                        batch=batch,
                        uploaded_file=ContentFile(
                            payload.content, name=payload.original_name
                        ),
                        original_file_name=payload.original_name,
                        file_hash_sha256=payload.sha256_hex,
                        file_size_bytes=payload.file_size_bytes,
                        page_count=payload.page_count,
                        status=DocumentFile.Status.FAILED,
                    )
                    ProcessingJob.objects.create(
                        document=failed_doc,
                        job_type=ProcessingJob.JobType.FULL_PIPELINE,
                        status=ProcessingJob.Status.FAILED,
                        error_message=str(exc),
                        completed_at=timezone.now(),
                    )
            except Exception:
                pass
            outcome.failed_documents.append((payload.original_name, str(exc)))

    batch.status = (
        BatchUpload.Status.COMPLETED
        if outcome.succeeded
        else BatchUpload.Status.FAILED
    )
    batch.save(update_fields=["status"])
    return outcome
