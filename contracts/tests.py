from __future__ import annotations

import csv
import io
import json
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

import openpyxl
import pymupdf
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from contracts.engine.errors import IngestionError
from contracts.engine.extraction import extract
from contracts.engine.ingestion import ingest_file
from contracts.engine.mapping import map_payload
from contracts.engine.models import DocumentType, IngestedDocument, MappingResult
from contracts.models import (
    ArbitraryCharge,
    BatchUpload,
    CarrierProfile,
    ContractMetadata,
    DocumentFile,
    EquipmentType,
    ExportRecord,
    FreightRate,
    ProcessingJob,
)
from contracts.services.pipeline import (
    _build_pymupdf_fallback_document,
    ensure_default_carriers,
    ingest_uploaded_files,
)
from dashboard.views import UNAUTHORIZED_DASHBOARD_MESSAGE

def _create_digital_pdf_bytes(
    text_lines: list[str] | None = None,
    filename_hint: str = "contract.pdf",
) -> bytes:
    """Create an in-memory digital vector-text PDF using PyMuPDF."""
    lines = text_lines or [
        'SERVICE CONTRACT NO. ATL0347N25 between Shipper and "MSC Mediterranean Shipping Company"',
        "Effective Date 01 Jul, 2025",
        "[NORTH AMERICA - ASIA (WB)]",
        "COMMODITY: Electronics and Machinery Parts;",
        "ORIGIN: CHARLESTON",
        "Destination | Term | Type | Cur | 20' | 40' | 40HC | 45'",
        "DALIAN | CY | Dry | USD | 360 | 450 | 450 | 800",
        "NINGBO | CY | Dry | USD | 245 | 260 | 260 | 300",
        "valid from 20250701 to 20250930",
    ]
    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for line in lines:
        page.insert_text((50, y), line, fontsize=10)
        y += 18
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _create_scanned_like_pdf_bytes() -> bytes:
    """Create a PDF with < 150 characters of selectable text (triggers SCANNED_PDF)."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 60), "Scan page 1", fontsize=10)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


MULTIPAGE_CONTRACT_NAME = "SAV0412N25_Contract.pdf"
_RATE_HEADER = ["Destination", "Destination Via", "Term", "Cur", "20'", "40'", "40HC", "45'"]
_ARB_HEADER = ["Point", "Via", "Term", "Cur", "20'", "40'", "40HC", "45'"]
_PDF_COLUMN_X = [40, 140, 240, 300, 345, 410, 475, 535, 572]
_PDF_ROW_HEIGHT = 18
_RUNNING_HEADER = "Confidential Service Contract SAV0412N25"


def _draw_ruled_table(page, top: float, rows: list[list[str]]) -> float:
    """Draw a vector table with ruling lines (detectable by PyMuPDF and OpenDataLoader)."""
    for row_idx, row in enumerate(rows):
        for col_idx, text in enumerate(row):
            if text:
                page.insert_text(
                    (_PDF_COLUMN_X[col_idx] + 3, top + row_idx * _PDF_ROW_HEIGHT + 13),
                    text,
                    fontsize=9,
                )
    bottom = top + len(rows) * _PDF_ROW_HEIGHT
    for row_idx in range(len(rows) + 1):
        y = top + row_idx * _PDF_ROW_HEIGHT
        page.draw_line((_PDF_COLUMN_X[0], y), (_PDF_COLUMN_X[-1], y), width=0.6)
    for x in _PDF_COLUMN_X:
        page.draw_line((x, top), (x, bottom), width=0.6)
    return bottom


def _create_multipage_rate_contract_pdf_bytes() -> bytes:
    """
    Build a 3-page vector service contract:
      - p1: contract headers + base rate table whose last line item (YANTIAN) is split
            vertically across the page break (40HC/45' rates continue on p2).
      - p2: repeated running header, repeated rate header row, the orphan continuation
            line, two more rate rows, then the ORIGIN ARBITRARIES table.
      - p3: DESTINATION ARBITRARIES table.
    Every page also carries a "Page N of 3" footer.
    """
    doc = pymupdf.open()

    def text_line(page, y: float, text: str, size: float = 10) -> float:
        page.insert_text((40, y), text, fontsize=size)
        return y + 30

    def page_furniture(page, number: int) -> None:
        page.insert_text((40, 30), _RUNNING_HEADER, fontsize=8)
        page.insert_text((40, 770), f"Page {number} of 3", fontsize=8)

    page1 = doc.new_page(width=612, height=792)
    page_furniture(page1, 1)
    y = 70
    y = text_line(page1, y, "SERVICE CONTRACT NO. SAV0412N25")
    y = text_line(
        page1,
        y,
        'This contract is made with MSC (hereinafter called "Mediterranean Shipping Company").',
    )
    y = text_line(page1, y, "Effective Date 01 Jul, 2025")
    y = text_line(page1, y, "[NORTH AMERICA - ASIA (WB)]")
    y = text_line(page1, y, "COMMODITY: Electronics and Machinery Parts;")
    y = text_line(page1, y, "ORIGIN: SAVANNAH")
    _draw_ruled_table(
        page1,
        y + 4,
        [
            _RATE_HEADER,
            ["SHANGHAI", "", "CY", "USD", "1000", "1200", "1250", "1500"],
            ["NINGBO", "", "CY", "USD", "1010", "1210", "1260", "1510"],
            ["QINGDAO", "", "CY", "USD", "1020", "1220", "1270", "1520"],
            ["YANTIAN", "", "CY", "USD", "1200", "1500", "", ""],
        ],
    )

    page2 = doc.new_page(width=612, height=792)
    page_furniture(page2, 2)
    y = _draw_ruled_table(
        page2,
        60,
        [
            _RATE_HEADER,
            ["", "", "", "", "", "", "1500", "1900"],
            ["KAOHSIUNG", "", "CY", "USD", "1100", "1300", "1300", "1600"],
            ["HONG KONG", "", "CY", "USD", "900", "1100", "1100", "1400"],
        ],
    )
    y = text_line(page2, y + 20, "valid from 20250701 to 20250930")
    y = text_line(page2, y + 10, "6-3. ORIGIN ARBITRARIES")
    y = _draw_ruled_table(
        page2,
        y + 4,
        [
            _ARB_HEADER,
            ["ATLANTA", "SAVANNAH", "CY RAIL", "USD", "450", "525", "525", "600"],
            ["CHARLOTTE", "SAVANNAH", "CY TRUCK", "USD", "380", "420", "420", ""],
        ],
    )
    text_line(page2, y + 20, "valid 2025-07-01 to 2026-06-30")

    page3 = doc.new_page(width=612, height=792)
    page_furniture(page3, 3)
    y = text_line(page3, 70, "6-4. DESTINATION ARBITRARIES")
    y = _draw_ruled_table(
        page3,
        y + 4,
        [
            _ARB_HEADER,
            ["CHONGQING", "SHANGHAI", "CY BARGE", "USD", "300", "350", "350", ""],
        ],
    )
    text_line(page3, y + 20, "valid 2025-07-01 to 2026-06-30")

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


_AST_COLUMN_LEFTS = (40.0, 140.0, 240.0, 340.0)
_AST_RATE_HEADER = ["Destination", "Term", "20'", "40'"]
_AST_ARB_HEADER = ["Point", "Via", "20'", "40'"]


def _ast_text(page: int, content: str) -> dict:
    return {"type": "paragraph", "page number": page, "content": content}


def _ast_table(page: int, rows: list[list[str]], lefts=_AST_COLUMN_LEFTS) -> dict:
    """Build an OpenDataLoader-shaped table node with per-cell bounding boxes."""
    return {
        "type": "table",
        "page number": page,
        "rows": [
            {
                "cells": [
                    {
                        "column number": col_idx + 1,
                        "bounding box": [lefts[col_idx], 500.0, lefts[col_idx] + 100.0, 518.0],
                        "kids": [{"content": value}] if value else [],
                    }
                    for col_idx, value in enumerate(row)
                ]
            }
            for row in rows
        ],
    }


class ContractModelConstraintTests(TestCase):
    """Verify PostgreSQL schema constraints BR-03 through BR-13."""

    def setUp(self):
        ensure_default_carriers()
        self.user = CustomUser.objects.create_user(
            username="constraint_encoder",
            email="constraint@shake.local",
            password="Str0ngPassword!123",
            role=CustomUser.Role.ENCODER,
        )
        self.carrier = CarrierProfile.objects.get(carrier_code="MSCU")
        self.batch = BatchUpload.objects.create(
            user=self.user,
            batch_number="BATCH-20261118-001",
            total_files=1,
            status=BatchUpload.Status.PROCESSING,
        )
        self.doc = DocumentFile.objects.create(
            batch=self.batch,
            uploaded_file="contracts/pdfs/2026/11/sample.pdf",
            original_file_name="sample.pdf",
            file_hash_sha256="a" * 64,
            file_size_bytes=2048,
            page_count=2,
            status=DocumentFile.Status.EXTRACTED,
        )
        self.contract = ContractMetadata.objects.create(
            document=self.doc,
            carrier=self.carrier,
            contract_number="ATL0347N25",
            trade_scope="NORTH AMERICA - ASIA (WB)",
            commodity_desc="General Cargo",
            effective_date=date(2025, 7, 1),
            expiration_date=date(2025, 9, 30),
        )

    def test_br03_duplicate_carrier_code_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CarrierProfile.objects.create(
                    carrier_code="MSCU",
                    carrier_name="Duplicate Carrier",
                )

    def test_br04_br05_batch_constraints(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BatchUpload.objects.create(
                    user=self.user,
                    batch_number="BATCH-20261118-002",
                    total_files=0,
                    status=BatchUpload.Status.QUEUED,
                )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BatchUpload.objects.create(
                    user=self.user,
                    batch_number="BATCH-20261118-003",
                    total_files=1,
                    status="INVALID_STATUS",
                )

    def test_br06_br07_br08_document_constraints(self):
        # Duplicate SHA-256 (BR-06)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentFile.objects.create(
                    batch=self.batch,
                    uploaded_file="contracts/pdfs/2026/11/dup.pdf",
                    original_file_name="dup.pdf",
                    file_hash_sha256="a" * 64,
                    file_size_bytes=1024,
                    page_count=1,
                    status=DocumentFile.Status.PENDING,
                )

        # Zero file size (BR-08)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentFile.objects.create(
                    batch=self.batch,
                    uploaded_file="contracts/pdfs/2026/11/empty.pdf",
                    original_file_name="empty.pdf",
                    file_hash_sha256="b" * 64,
                    file_size_bytes=0,
                    page_count=1,
                    status=DocumentFile.Status.PENDING,
                )

        # Invalid status (BR-07)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentFile.objects.create(
                    batch=self.batch,
                    uploaded_file="contracts/pdfs/2026/11/badstatus.pdf",
                    original_file_name="badstatus.pdf",
                    file_hash_sha256="c" * 64,
                    file_size_bytes=512,
                    page_count=1,
                    status="UNKNOWN_STATE",
                )

    def test_br09_document_cannot_be_hard_deleted_when_contract_exists(self):
        with self.assertRaises(RestrictedError):
            self.doc.delete()

    def test_br10_expiration_before_effective_rejected(self):
        doc2 = DocumentFile.objects.create(
            batch=self.batch,
            uploaded_file="contracts/pdfs/2026/11/other.pdf",
            original_file_name="other.pdf",
            file_hash_sha256="d" * 64,
            file_size_bytes=1024,
            page_count=1,
            status=DocumentFile.Status.PENDING,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ContractMetadata.objects.create(
                    document=doc2,
                    carrier=self.carrier,
                    contract_number="BADDATES01",
                    trade_scope="ASIA - EU",
                    commodity_desc="Textiles",
                    effective_date=date(2025, 10, 1),
                    expiration_date=date(2025, 9, 1),
                )

    def test_br12_br13_freight_rate_constraints(self):
        # Non-positive rate (BR-12)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FreightRate.objects.create(
                    contract=self.contract,
                    line_item_sequence=1,
                    origin_port_code="USCHS",
                    origin_port_name="Charleston",
                    destination_port_code="CNDLC",
                    destination_port_name="Dalian",
                    equipment_type=EquipmentType.GP20,
                    rate_amount=Decimal("0.00"),
                )

        # Identical origin and destination ports (BR-13)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FreightRate.objects.create(
                    contract=self.contract,
                    line_item_sequence=2,
                    origin_port_code="USCHS",
                    origin_port_name="Charleston",
                    destination_port_code="USCHS",
                    destination_port_name="Charleston",
                    equipment_type=EquipmentType.GP40,
                    rate_amount=Decimal("500.00"),
                )

        # Invalid equipment type (BR-13)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FreightRate.objects.create(
                    contract=self.contract,
                    line_item_sequence=3,
                    origin_port_code="USCHS",
                    origin_port_name="Charleston",
                    destination_port_code="CNDLC",
                    destination_port_name="Dalian",
                    equipment_type="99XX",
                    rate_amount=Decimal("500.00"),
                )


class ContractIngestionPipelineTests(TestCase):
    """Verify PDF ingestion, SHA-256 deduplication, scanned rejection, and rate unpivoting."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        ensure_default_carriers()
        self.encoder = CustomUser.objects.create_user(
            username="pipe_encoder",
            email="pipe@shake.local",
            password="Str0ngPassword!123",
            role=CustomUser.Role.ENCODER,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_pipeline_unpivots_rates_and_arbitraries_atomically(self):
        pdf_bytes = _create_digital_pdf_bytes()
        upload = SimpleUploadedFile(
            "ATL0347N25_Contract.pdf",
            pdf_bytes,
            content_type="application/pdf",
        )

        mocked_mapping = MappingResult(
            contract_id="ATL0347N25",
            carrier="Mediterranean Shipping Company",
            rates=[
                {
                    "Carrier": "Mediterranean Shipping Company",
                    "Contract ID": "ATL0347N25",
                    "effective_date": "07/01/2025",
                    "expiration_date": "09/30/2025",
                    "commodity": "Electronics",
                    "Scope": "NORTH AMERICA - ASIA (WB)",
                    "origin_city": "CHARLESTON",
                    "destination_city": "DALIAN",
                    "Cur": "USD",
                    "BaseRate 20": "360",
                    "BaseRate 40": "450",
                    "BaseRate 40H": "450",
                    "BaseRate 45": "800",
                    "source_page": 2,
                }
            ],
            origin_arb=[
                {
                    "Carrier": "Mediterranean Shipping Company",
                    "Contract ID": "ATL0347N25",
                    "effective_date": "07/01/2025",
                    "expiration_date": "06/30/2026",
                    "origin_city": "ATLANTA",
                    "origin_via_city": "CHARLESTON, SC",
                    "service": "CY RAIL",
                    "Cur": "USD",
                    "BaseRate 20": "450",
                    "BaseRate 40": "525",
                    "source_page": 5,
                }
            ],
            dest_arb=[],
        )

        def fake_runner(payload):
            doc = IngestedDocument(
                source_path=Path(payload.original_name),
                doc_type=DocumentType.DIGITAL_PDF,
                total_pages=payload.page_count,
                json={},
                markdown="",
            )
            return doc, {}, mocked_mapping

        with override_settings(MEDIA_ROOT=self.temp_media):
            outcome = ingest_uploaded_files(
                user=self.encoder,
                uploaded_files=[upload],
                runner=fake_runner,
            )

        self.assertEqual(len(outcome.succeeded), 1)
        self.assertEqual(len(outcome.rejected_files), 0)
        self.assertEqual(len(outcome.failed_documents), 0)

        contract = outcome.succeeded[0]
        self.assertEqual(contract.contract_number, "ATL0347N25")
        self.assertEqual(contract.carrier.carrier_code, "MSCU")
        self.assertEqual(contract.document.status, DocumentFile.Status.EXTRACTED)
        self.assertEqual(outcome.batch.status, BatchUpload.Status.COMPLETED)

        rates = list(contract.freight_rates.order_by("line_item_sequence"))
        self.assertEqual(len(rates), 4)
        self.assertEqual(
            [(r.equipment_type, r.rate_amount) for r in rates],
            [
                ("20GP", Decimal("360.00")),
                ("40GP", Decimal("450.00")),
                ("40HC", Decimal("450.00")),
                ("45HC", Decimal("800.00")),
            ],
        )
        self.assertEqual(rates[0].origin_port_code, "USCHS")
        self.assertEqual(rates[0].destination_port_code, "CNDLC")
        self.assertEqual(rates[0].source_page_start, 2)

        arbs = list(contract.arbitrary_charges.order_by("line_item_sequence"))
        self.assertEqual(len(arbs), 2)
        self.assertEqual(arbs[0].charge_type, ArbitraryCharge.ChargeType.ORIGIN)
        self.assertEqual(arbs[0].transport_mode, ArbitraryCharge.TransportMode.RAIL)
        self.assertEqual(arbs[0].location_code, "USATL")
        self.assertEqual(arbs[0].charge_amount, Decimal("450.00"))

        job = contract.document.jobs.get()
        self.assertEqual(job.status, ProcessingJob.Status.COMPLETED)

    def test_duplicate_sha256_is_blocked_br06(self):
        pdf_bytes = _create_digital_pdf_bytes()
        upload1 = SimpleUploadedFile("first.pdf", pdf_bytes, content_type="application/pdf")
        upload2 = SimpleUploadedFile("second.pdf", pdf_bytes, content_type="application/pdf")

        def fake_runner(payload):
            doc = IngestedDocument(
                source_path=Path(payload.original_name),
                doc_type=DocumentType.DIGITAL_PDF,
                total_pages=1,
                json={},
                markdown="",
            )
            return doc, {}, MappingResult(contract_id="DUP001N25", carrier="MAEU")

        with override_settings(MEDIA_ROOT=self.temp_media):
            first_outcome = ingest_uploaded_files(self.encoder, [upload1], runner=fake_runner)
            second_outcome = ingest_uploaded_files(self.encoder, [upload2], runner=fake_runner)

        self.assertEqual(len(first_outcome.succeeded), 1)
        self.assertEqual(len(second_outcome.succeeded), 0)
        self.assertEqual(len(second_outcome.rejected_files), 1)
        self.assertIn("Duplicate PDF blocked (BR-06)", second_outcome.rejected_files[0][1])
        self.assertEqual(DocumentFile.objects.count(), 1)
        self.assertEqual(ContractMetadata.objects.count(), 1)

    def test_scanned_pdf_and_non_pdf_rejected_without_orphans(self):
        scanned_upload = SimpleUploadedFile(
            "scanned.pdf",
            _create_scanned_like_pdf_bytes(),
            content_type="application/pdf",
        )
        txt_upload = SimpleUploadedFile(
            "not_a_pdf.txt",
            b"plain text",
            content_type="text/plain",
        )

        with override_settings(MEDIA_ROOT=self.temp_media):
            outcome = ingest_uploaded_files(self.encoder, [scanned_upload, txt_upload])

        self.assertIsNone(outcome.batch)
        self.assertEqual(len(outcome.succeeded), 0)
        self.assertEqual(len(outcome.rejected_files), 2)
        self.assertEqual(BatchUpload.objects.count(), 0)
        self.assertEqual(DocumentFile.objects.count(), 0)
        self.assertEqual(ContractMetadata.objects.count(), 0)

    def test_java_ingestion_error_falls_back_to_pymupdf_cleanly(self):
        pdf_bytes = _create_digital_pdf_bytes()
        upload = SimpleUploadedFile("fallback.pdf", pdf_bytes, content_type="application/pdf")

        with override_settings(MEDIA_ROOT=self.temp_media):
            with patch(
                "contracts.services.pipeline.ingest_file",
                side_effect=IngestionError("Simulated Java missing"),
            ):
                outcome = ingest_uploaded_files(self.encoder, [upload])

        self.assertEqual(len(outcome.succeeded), 1)
        self.assertEqual(len(outcome.failed_documents), 0)
        contract = outcome.succeeded[0]
        self.assertEqual(contract.contract_number, "ATL0347N25")


class CrossPageStitchingExtractionTests(SimpleTestCase):
    """Verify F-04 cross-page table stitching on OpenDataLoader-shaped ASTs."""

    def _extract(self, kids: list[dict]) -> dict:
        return extract({"kids": kids}, filename_stem="SAV0412N25")

    def test_repeated_header_pruned_and_split_row_reconnected(self):
        extracted = self._extract(
            [
                _ast_text(1, "ORIGIN: SAVANNAH"),
                _ast_table(
                    1,
                    [
                        _AST_RATE_HEADER,
                        ["SHANGHAI", "CY", "1000", "1200"],
                        ["YANTIAN", "CY", "1200", ""],
                    ],
                ),
                _ast_text(1, "Page 1 of 2"),
                _ast_text(2, "Page 2 of 2"),
                _ast_table(
                    2,
                    [
                        _AST_RATE_HEADER,
                        ["", "", "", "1500"],
                        ["BUSAN", "CY", "900", "1100"],
                        ["Page 2 of 2", "", "", ""],
                    ],
                ),
            ]
        )

        self.assertEqual(len(extracted["tables"]), 1)
        table = extracted["tables"][0]
        self.assertEqual((table["source_page_start"], table["source_page_end"]), (1, 2))
        self.assertEqual(
            [row["Destination"] for row in table["rows"]],
            ["SHANGHAI", "YANTIAN", "BUSAN"],
        )
        self.assertEqual(table["rows"][1]["40'"], "1500")
        self.assertEqual(table["row_page_spans"], [[1, 1], [1, 2], [2, 2]])

        mapped = map_payload(extracted)
        self.assertEqual(len(mapped.rates), 3)
        yantian = mapped.rates[1]
        self.assertEqual(yantian["destination_city"], "YANTIAN")
        self.assertEqual((yantian["BaseRate 20"], yantian["BaseRate 40"]), ("1200", "1500"))
        self.assertEqual(
            (yantian["source_page_start"], yantian["source_page_end"]), (1, 2)
        )
        self.assertEqual(
            (mapped.rates[2]["source_page_start"], mapped.rates[2]["source_page_end"]),
            (2, 2),
        )

    def test_headerless_continuation_is_stitched(self):
        extracted = self._extract(
            [
                _ast_table(1, [_AST_RATE_HEADER, ["SHANGHAI", "CY", "1000", "1200"]]),
                _ast_table(
                    2,
                    [["BUSAN", "CY", "900", "1100"], ["KOBE", "CY", "950", "1150"]],
                ),
            ]
        )
        self.assertEqual(len(extracted["tables"]), 1)
        self.assertEqual(
            [row["Destination"] for row in extracted["tables"][0]["rows"]],
            ["SHANGHAI", "BUSAN", "KOBE"],
        )

    def test_distinct_schema_on_next_page_is_not_merged(self):
        extracted = self._extract(
            [
                _ast_table(1, [_AST_RATE_HEADER, ["SHANGHAI", "CY", "1000", "1200"]]),
                _ast_table(2, [_AST_ARB_HEADER, ["ATLANTA", "SAVANNAH", "450", "525"]]),
            ]
        )
        self.assertEqual(len(extracted["tables"]), 2)
        first, second = extracted["tables"]
        self.assertEqual((first["source_page_start"], first["source_page_end"]), (1, 1))
        self.assertEqual((second["source_page_start"], second["source_page_end"]), (2, 2))
        self.assertIn("Point", second["rows"][0])

    def test_misaligned_columns_are_not_merged(self):
        extracted = self._extract(
            [
                _ast_table(1, [_AST_RATE_HEADER, ["SHANGHAI", "CY", "1000", "1200"]]),
                _ast_table(
                    2,
                    [_AST_RATE_HEADER, ["BUSAN", "CY", "900", "1100"]],
                    lefts=(40.0, 200.0, 320.0, 430.0),
                ),
            ]
        )
        self.assertEqual(len(extracted["tables"]), 2)

    def test_context_change_between_pages_starts_new_table(self):
        extracted = self._extract(
            [
                _ast_text(1, "ORIGIN: SAVANNAH"),
                _ast_table(1, [_AST_RATE_HEADER, ["SHANGHAI", "CY", "1000", "1200"]]),
                _ast_text(2, "ORIGIN: NORFOLK"),
                _ast_table(2, [_AST_RATE_HEADER, ["BUSAN", "CY", "900", "1100"]]),
            ]
        )
        self.assertEqual(len(extracted["tables"]), 2)
        self.assertEqual(extracted["tables"][1]["metadata"]["origin_city"], "NORFOLK")

    def test_non_adjacent_pages_are_not_merged(self):
        extracted = self._extract(
            [
                _ast_table(1, [_AST_RATE_HEADER, ["SHANGHAI", "CY", "1000", "1200"]]),
                _ast_table(3, [_AST_RATE_HEADER, ["BUSAN", "CY", "900", "1100"]]),
            ]
        )
        self.assertEqual(len(extracted["tables"]), 2)


class MultiPageVectorPdfPipelineTests(TestCase):
    """
    End-to-end F-04–F-07 verification on a synthetic multi-page vector PDF:
    ingest -> extract() -> map_payload() -> persist, with no external fixture files.
    """

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        ensure_default_carriers()
        self.encoder = CustomUser.objects.create_user(
            username="stitch_encoder",
            email="stitch@shake.local",
            password="Str0ngPassword!123",
            role=CustomUser.Role.ENCODER,
        )
        self.pdf_bytes = _create_multipage_rate_contract_pdf_bytes()

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def _ingest(self) -> ContractMetadata:
        upload = SimpleUploadedFile(
            MULTIPAGE_CONTRACT_NAME, self.pdf_bytes, content_type="application/pdf"
        )
        with override_settings(MEDIA_ROOT=self.temp_media):
            outcome = ingest_uploaded_files(self.encoder, [upload])
        self.assertEqual(outcome.rejected_files, [])
        self.assertEqual(outcome.failed_documents, [])
        self.assertEqual(len(outcome.succeeded), 1)
        return outcome.succeeded[0]

    def _assert_extraction_payload(self, extracted: dict) -> None:
        self.assertEqual(extracted["contract_id"], "SAV0412N25")
        self.assertEqual(
            [(t["section"], t["source_page_start"], t["source_page_end"]) for t in extracted["tables"]],
            [
                ("RATES", 1, 2),
                ("ORIGIN_ARBITRARIES", 2, 2),
                ("DESTINATION_ARBITRARIES", 3, 3),
            ],
        )
        rate_table = extracted["tables"][0]
        destinations = [row["Destination"] for row in rate_table["rows"]]
        self.assertEqual(
            destinations,
            ["SHANGHAI", "NINGBO", "QINGDAO", "YANTIAN", "KAOHSIUNG", "HONG KONG"],
        )
        self.assertEqual(
            rate_table["row_page_spans"],
            [[1, 1], [1, 1], [1, 1], [1, 2], [2, 2], [2, 2]],
        )

    def _assert_persisted_contract(self, contract: ContractMetadata) -> None:
        # F-05 / F-08: context-aware contract headers
        self.assertEqual(contract.contract_number, "SAV0412N25")
        self.assertEqual(contract.carrier.carrier_code, "MSCU")
        self.assertEqual(contract.trade_scope, "NORTH AMERICA - ASIA (WB)")
        self.assertTrue(contract.commodity_desc.startswith("Electronics and Machinery Parts"))
        self.assertEqual(contract.effective_date, date(2025, 7, 1))
        self.assertEqual(contract.expiration_date, date(2026, 6, 30))
        self.assertEqual(contract.document.page_count, 3)
        self.assertEqual(contract.document.status, DocumentFile.Status.EXTRACTED)

        # F-06: base rates — 6 line items x 4 equipment columns, no header/orphan rows
        rates = contract.freight_rates.all()
        self.assertEqual(rates.count(), 24)
        self.assertEqual(set(rates.values_list("origin_port_code", flat=True)), {"USSAV"})
        self.assertEqual(
            set(rates.values_list("destination_port_code", flat=True)),
            {"CNSHA", "CNNGB", "CNTAO", "CNYTN", "TWKHH", "HKHKG"},
        )
        self.assertFalse(rates.filter(destination_port_name__iexact="Destination").exists())

        # F-04: the vertically split YANTIAN line item is one coherent record set p. 1–2
        yantian = {
            r.equipment_type: r for r in rates.filter(destination_port_code="CNYTN")
        }
        self.assertEqual(
            {eq: r.rate_amount for eq, r in yantian.items()},
            {
                EquipmentType.GP20: Decimal("1200.00"),
                EquipmentType.GP40: Decimal("1500.00"),
                EquipmentType.HC40: Decimal("1500.00"),
                EquipmentType.HC45: Decimal("1900.00"),
            },
        )
        for rate in yantian.values():
            self.assertEqual((rate.source_page_start, rate.source_page_end), (1, 2))
            self.assertGreater(rate.source_page_end, rate.source_page_start)
        for rate in rates.filter(destination_port_code="CNSHA"):
            self.assertEqual((rate.source_page_start, rate.source_page_end), (1, 1))
        for rate in rates.filter(destination_port_code="HKHKG"):
            self.assertEqual((rate.source_page_start, rate.source_page_end), (2, 2))

        # F-07: origin/destination arbitraries stay separated from base rates
        origin = contract.arbitrary_charges.filter(charge_type=ArbitraryCharge.ChargeType.ORIGIN)
        dest = contract.arbitrary_charges.filter(
            charge_type=ArbitraryCharge.ChargeType.DESTINATION
        )
        self.assertEqual(origin.count(), 7)
        self.assertEqual(dest.count(), 3)
        atlanta = origin.filter(location_code="USATL")
        self.assertEqual(atlanta.count(), 4)
        self.assertEqual(set(atlanta.values_list("via_gateway_port", flat=True)), {"SAVANNAH"})
        self.assertEqual(
            set(atlanta.values_list("transport_mode", flat=True)),
            {ArbitraryCharge.TransportMode.RAIL},
        )
        self.assertEqual(
            set(origin.filter(location_code="USCLT").values_list("transport_mode", flat=True)),
            {ArbitraryCharge.TransportMode.TRUCK},
        )
        self.assertEqual(set(origin.values_list("source_page_num", flat=True)), {2})
        self.assertEqual(set(dest.values_list("location_name", flat=True)), {"CHONGQING"})
        self.assertEqual(set(dest.values_list("via_gateway_port", flat=True)), {"SHANGHAI"})
        self.assertEqual(
            set(dest.values_list("transport_mode", flat=True)),
            {ArbitraryCharge.TransportMode.BARGE},
        )
        self.assertEqual(set(dest.values_list("source_page_num", flat=True)), {3})
        self.assertFalse(rates.filter(destination_port_code__in=["USATL", "CHONGQING"]).exists())

    def test_pymupdf_vector_pipeline_stitches_and_persists_multi_page_contract(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / MULTIPAGE_CONTRACT_NAME
            pdf_path.write_bytes(self.pdf_bytes)
            ingested = _build_pymupdf_fallback_document(pdf_path)
        self.assertEqual(ingested.total_pages, 3)
        self._assert_extraction_payload(extract(ingested, filename_stem="SAV0412N25_Contract"))

        with patch(
            "contracts.services.pipeline.ingest_file",
            side_effect=IngestionError("Force the offline PyMuPDF vector path"),
        ):
            contract = self._ingest()
        self._assert_persisted_contract(contract)

    @skipUnless(shutil.which("java"), "OpenDataLoader requires a local Java runtime.")
    def test_opendataloader_pipeline_stitches_and_persists_multi_page_contract(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            pdf_path = Path(tmp_dir) / MULTIPAGE_CONTRACT_NAME
            pdf_path.write_bytes(self.pdf_bytes)
            ingested = ingest_file(pdf_path, Path(tmp_dir) / "ast")
        self._assert_extraction_payload(extract(ingested, filename_stem="SAV0412N25_Contract"))

        with patch(
            "contracts.services.pipeline._build_pymupdf_fallback_document",
            side_effect=AssertionError("OpenDataLoader path must not fall back"),
        ):
            contract = self._ingest()
        self._assert_persisted_contract(contract)


class ContractViewAndOwnershipTests(TestCase):
    """Verify upload, list, detail views and ENCODER vs. ADMIN isolation."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        ensure_default_carriers()
        self.password = "Str0ngShake!2026"
        self.admin_user = CustomUser.objects.create_user(
            username="contracts_admin",
            email="cadmin@shake.local",
            password=self.password,
            role=CustomUser.Role.ADMIN,
        )
        self.encoder_a = CustomUser.objects.create_user(
            username="encoder_a",
            email="enc_a@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )
        self.encoder_b = CustomUser.objects.create_user(
            username="encoder_b",
            email="enc_b@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )

        carrier = CarrierProfile.objects.get(carrier_code="COSU")
        batch_a = BatchUpload.objects.create(
            user=self.encoder_a,
            batch_number="BATCH-20261118-101",
            total_files=1,
            status=BatchUpload.Status.COMPLETED,
        )
        doc_a = DocumentFile.objects.create(
            batch=batch_a,
            uploaded_file="contracts/pdfs/2026/11/a.pdf",
            original_file_name="contract_a.pdf",
            file_hash_sha256="1" * 64,
            file_size_bytes=1200,
            page_count=1,
            status=DocumentFile.Status.EXTRACTED,
        )
        self.contract_a = ContractMetadata.objects.create(
            document=doc_a,
            carrier=carrier,
            contract_number="CHI0120N25",
            trade_scope="TRANS-PACIFIC",
            commodity_desc="Auto Parts",
            effective_date=date(2025, 5, 1),
            expiration_date=date(2026, 4, 30),
        )
        FreightRate.objects.create(
            contract=self.contract_a,
            line_item_sequence=1,
            origin_port_code="CNSHA",
            origin_port_name="Shanghai",
            destination_port_code="USLAX",
            destination_port_name="Los Angeles",
            equipment_type=EquipmentType.HC40,
            rate_amount=Decimal("2400.00"),
        )

        batch_b = BatchUpload.objects.create(
            user=self.encoder_b,
            batch_number="BATCH-20261118-102",
            total_files=1,
            status=BatchUpload.Status.COMPLETED,
        )
        doc_b = DocumentFile.objects.create(
            batch=batch_b,
            uploaded_file="contracts/pdfs/2026/11/b.pdf",
            original_file_name="contract_b.pdf",
            file_hash_sha256="2" * 64,
            file_size_bytes=1500,
            page_count=1,
            status=DocumentFile.Status.EXTRACTED,
        )
        self.contract_b = ContractMetadata.objects.create(
            document=doc_b,
            carrier=carrier,
            contract_number="NYC0154N25",
            trade_scope="ASIA - US EAST COAST",
            commodity_desc="Furniture",
            effective_date=date(2025, 6, 1),
            expiration_date=date(2026, 5, 31),
        )

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_anonymous_users_redirected_to_login(self):
        for url in (
            reverse("contract_list"),
            reverse("contract_upload"),
            reverse("contract_detail", kwargs={"pk": self.contract_a.pk}),
        ):
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('login')}?next={url}")

    def test_encoder_sees_only_own_contracts_and_cannot_inspect_others(self):
        self.client.force_login(self.encoder_a)
        list_resp = self.client.get(reverse("contract_list"))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, "CHI0120N25")
        self.assertNotContains(list_resp, "NYC0154N25")

        own_detail = self.client.get(
            reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
        )
        self.assertEqual(own_detail.status_code, 200)
        self.assertContains(own_detail, "Shanghai")
        self.assertContains(own_detail, "2400.00")

        other_detail = self.client.get(
            reverse("contract_detail", kwargs={"pk": self.contract_b.pk})
        )
        self.assertEqual(other_detail.status_code, 404)

    def test_admin_sees_all_contracts(self):
        self.client.force_login(self.admin_user)
        list_resp = self.client.get(reverse("contract_list"))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, "CHI0120N25")
        self.assertContains(list_resp, "NYC0154N25")

        detail_resp = self.client.get(
            reverse("contract_detail", kwargs={"pk": self.contract_b.pk})
        )
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "NYC0154N25")

    def test_upload_view_persists_and_blocks_duplicate_upload(self):
        self.client.force_login(self.encoder_a)
        pdf_bytes = _create_digital_pdf_bytes()
        upload1 = SimpleUploadedFile(
            "LAX0079N25_Contract.pdf",
            pdf_bytes,
            content_type="application/pdf",
        )

        mocked_mapping = MappingResult(
            contract_id="LAX0079N25",
            carrier="COSCO SHIPPING",
            rates=[
                {
                    "effective_date": "07/01/2025",
                    "expiration_date": "09/30/2025",
                    "commodity": "Electronics",
                    "Scope": "NORTH AMERICA - ASIA (WB)",
                    "origin_city": "BUSAN",
                    "destination_city": "LONG BEACH",
                    "Cur": "USD",
                    "BaseRate 40": "1950",
                    "source_page": 1,
                }
            ],
        )

        def fake_runner(payload):
            doc = IngestedDocument(
                source_path=Path(payload.original_name),
                doc_type=DocumentType.DIGITAL_PDF,
                total_pages=1,
                json={},
                markdown="",
            )
            return doc, {}, mocked_mapping

        with override_settings(MEDIA_ROOT=self.temp_media):
            with patch(
                "contracts.services.pipeline._run_engine_on_bytes",
                side_effect=fake_runner,
            ):
                response = self.client.post(
                    reverse("contract_upload"),
                    {"carrier_profile": "AUTO", "pdf_files": [upload1]},
                    follow=True,
                )

        created = ContractMetadata.objects.get(contract_number="LAX0079N25")
        self.assertRedirects(
            response, reverse("contract_detail", kwargs={"pk": created.pk})
        )
        self.assertContains(response, "LAX0079N25")
        self.assertEqual(created.freight_rates.count(), 1)
        self.assertContains(response, "1950.00")

        # Re-upload exact same PDF -> blocked by BR-06
        upload_dup = SimpleUploadedFile(
            "LAX0079N25_Duplicate.pdf",
            pdf_bytes,
            content_type="application/pdf",
        )
        with override_settings(MEDIA_ROOT=self.temp_media):
            dup_resp = self.client.post(
                reverse("contract_upload"),
                {"carrier_profile": "AUTO", "pdf_files": [upload_dup]},
            )
        self.assertEqual(dup_resp.status_code, 200)
        self.assertContains(dup_resp, "Duplicate PDF blocked (BR-06)")


class ContractCrudAndArchiveTests(TestCase):
    """Verify Spec 02 Update, FreightRate CRUD, Document Delete, and Archive (BR-09–BR-13)."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        ensure_default_carriers()
        self.password = "Str0ngShake!2026"
        self.admin_user = CustomUser.objects.create_user(
            username="crud_admin",
            email="crud_admin@shake.local",
            password=self.password,
            role=CustomUser.Role.ADMIN,
        )
        self.encoder_a = CustomUser.objects.create_user(
            username="crud_encoder_a",
            email="crud_a@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )
        self.encoder_b = CustomUser.objects.create_user(
            username="crud_encoder_b",
            email="crud_b@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )

        self.carrier_mscu = CarrierProfile.objects.get(carrier_code="MSCU")
        self.carrier_cosu = CarrierProfile.objects.get(carrier_code="COSU")

        batch_a = BatchUpload.objects.create(
            user=self.encoder_a,
            batch_number="BATCH-20261118-201",
            total_files=2,
            status=BatchUpload.Status.COMPLETED,
        )
        self.doc_extracted = DocumentFile.objects.create(
            batch=batch_a,
            uploaded_file="contracts/pdfs/2026/11/extracted.pdf",
            original_file_name="extracted.pdf",
            file_hash_sha256="3" * 64,
            file_size_bytes=2048,
            page_count=3,
            status=DocumentFile.Status.EXTRACTED,
        )
        self.doc_failed = DocumentFile.objects.create(
            batch=batch_a,
            uploaded_file="contracts/pdfs/2026/11/failed.pdf",
            original_file_name="failed.pdf",
            file_hash_sha256="4" * 64,
            file_size_bytes=1024,
            page_count=1,
            status=DocumentFile.Status.FAILED,
        )
        self.contract_a = ContractMetadata.objects.create(
            document=self.doc_extracted,
            carrier=self.carrier_mscu,
            contract_number="ATL0347N25",
            trade_scope="NORTH AMERICA - ASIA (WB)",
            commodity_desc="Electronics",
            effective_date=date(2025, 7, 1),
            expiration_date=date(2025, 9, 30),
        )
        self.rate_1 = FreightRate.objects.create(
            contract=self.contract_a,
            line_item_sequence=1,
            origin_port_code="USCHS",
            origin_port_name="Charleston",
            destination_port_code="CNDLC",
            destination_port_name="Dalian",
            equipment_type=EquipmentType.GP20,
            currency_code="USD",
            rate_amount=Decimal("360.00"),
        )

        batch_b = BatchUpload.objects.create(
            user=self.encoder_b,
            batch_number="BATCH-20261118-202",
            total_files=1,
            status=BatchUpload.Status.COMPLETED,
        )
        self.doc_b = DocumentFile.objects.create(
            batch=batch_b,
            uploaded_file="contracts/pdfs/2026/11/other_b.pdf",
            original_file_name="other_b.pdf",
            file_hash_sha256="5" * 64,
            file_size_bytes=1024,
            page_count=1,
            status=DocumentFile.Status.EXTRACTED,
        )
        self.contract_b = ContractMetadata.objects.create(
            document=self.doc_b,
            carrier=self.carrier_cosu,
            contract_number="LAX9999N25",
            trade_scope="TRANS-PACIFIC",
            commodity_desc="Machinery",
            effective_date=date(2025, 7, 1),
            expiration_date=date(2025, 12, 31),
        )

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_contract_metadata_update_and_br10_validation(self):
        self.client.force_login(self.encoder_a)
        edit_url = reverse("contract_edit", kwargs={"pk": self.contract_a.pk})

        # Invalid expiration_date < effective_date (BR-10)
        bad_resp = self.client.post(
            edit_url,
            {
                "contract_number": "ATL0347N25-REV",
                "carrier": self.carrier_cosu.pk,
                "trade_scope": "ASIA - EUROPE",
                "commodity_desc": "Updated Commodity",
                "effective_date": "2025-10-01",
                "expiration_date": "2025-09-01",
            },
        )
        self.assertEqual(bad_resp.status_code, 200)
        self.assertContains(bad_resp, "BR-10")
        self.contract_a.refresh_from_db()
        self.assertEqual(self.contract_a.contract_number, "ATL0347N25")

        # Valid update
        good_resp = self.client.post(
            edit_url,
            {
                "contract_number": "ATL0347N25-REV",
                "carrier": self.carrier_cosu.pk,
                "trade_scope": "ASIA - EUROPE",
                "commodity_desc": "Updated Commodity",
                "effective_date": "2025-07-01",
                "expiration_date": "2025-12-31",
            },
            follow=True,
        )
        self.assertRedirects(
            good_resp, reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
        )
        self.contract_a.refresh_from_db()
        self.assertEqual(self.contract_a.contract_number, "ATL0347N25-REV")
        self.assertEqual(self.contract_a.carrier, self.carrier_cosu)
        self.assertEqual(self.contract_a.trade_scope, "ASIA - EUROPE")

        # ENCODER cannot edit another user's contract
        other_resp = self.client.get(
            reverse("contract_edit", kwargs={"pk": self.contract_b.pk})
        )
        self.assertEqual(other_resp.status_code, 404)

    def test_freight_rate_create_update_delete_and_validation(self):
        self.client.force_login(self.encoder_a)
        add_url = reverse("rate_create", kwargs={"pk": self.contract_a.pk})

        # Reject non-positive rate (BR-12) and identical POL/POD (BR-13)
        invalid_resp = self.client.post(
            add_url,
            {
                "origin_port_code": "uschs",
                "origin_port_name": "Charleston",
                "destination_port_code": "USCHS",
                "destination_port_name": "Charleston",
                "equipment_type": EquipmentType.GP40,
                "currency_code": "usd",
                "rate_amount": "0.00",
            },
        )
        self.assertEqual(invalid_resp.status_code, 200)
        self.assertContains(invalid_resp, "BR-12")
        self.assertContains(invalid_resp, "BR-13")
        self.assertEqual(self.contract_a.freight_rates.count(), 1)

        # Create valid rate row -> line_item_sequence auto-assigned as max + 1 (2)
        create_resp = self.client.post(
            add_url,
            {
                "origin_port_code": "cnsha",
                "origin_port_name": "Shanghai",
                "destination_port_code": "uslax",
                "destination_port_name": "Los Angeles",
                "equipment_type": EquipmentType.HC40,
                "currency_code": "usd",
                "rate_amount": "2450.50",
            },
            follow=True,
        )
        self.assertRedirects(
            create_resp, reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
        )
        created_rate = FreightRate.objects.get(
            contract=self.contract_a, line_item_sequence=2
        )
        self.assertEqual(created_rate.origin_port_code, "CNSHA")
        self.assertEqual(created_rate.destination_port_code, "USLAX")
        self.assertEqual(created_rate.currency_code, "USD")
        self.assertEqual(created_rate.rate_amount, Decimal("2450.50"))

        # Update rate row
        edit_url = reverse(
            "rate_edit",
            kwargs={"pk": self.contract_a.pk, "rate_id": created_rate.pk},
        )
        edit_resp = self.client.post(
            edit_url,
            {
                "origin_port_code": "CNSHA",
                "origin_port_name": "Shanghai",
                "destination_port_code": "USLGB",
                "destination_port_name": "Long Beach",
                "equipment_type": EquipmentType.HC45,
                "currency_code": "USD",
                "rate_amount": "2800.00",
            },
            follow=True,
        )
        self.assertRedirects(
            edit_resp, reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
        )
        created_rate.refresh_from_db()
        self.assertEqual(created_rate.destination_port_code, "USLGB")
        self.assertEqual(created_rate.equipment_type, EquipmentType.HC45)
        self.assertEqual(created_rate.rate_amount, Decimal("2800.00"))

        # Delete rate row (POST only)
        delete_url = reverse(
            "rate_delete",
            kwargs={"pk": self.contract_a.pk, "rate_id": created_rate.pk},
        )
        get_del = self.client.get(delete_url)
        self.assertEqual(get_del.status_code, 405)

        del_resp = self.client.post(delete_url, follow=True)
        self.assertRedirects(
            del_resp, reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
        )
        self.assertFalse(FreightRate.objects.filter(pk=created_rate.pk).exists())

        # ENCODER cannot add rate to another user's contract
        other_add = self.client.post(
            reverse("rate_create", kwargs={"pk": self.contract_b.pk}),
            {
                "origin_port_code": "CNSHA",
                "origin_port_name": "Shanghai",
                "destination_port_code": "USLAX",
                "destination_port_name": "Los Angeles",
                "equipment_type": EquipmentType.GP20,
                "currency_code": "USD",
                "rate_amount": "1500.00",
            },
        )
        self.assertEqual(other_add.status_code, 404)

    def test_br09_blocks_extracted_doc_delete_allows_failed_delete_and_archive(self):
        self.client.force_login(self.encoder_a)

        # Blocking hard deletion of EXTRACTED document (BR-09)
        blocked_resp = self.client.post(
            reverse("document_delete", kwargs={"doc_id": self.doc_extracted.pk}),
            follow=True,
        )
        self.assertRedirects(
            blocked_resp, reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
        )
        self.assertContains(blocked_resp, "BR-09")
        self.assertTrue(DocumentFile.objects.filter(pk=self.doc_extracted.pk).exists())
        self.assertTrue(ContractMetadata.objects.filter(pk=self.contract_a.pk).exists())

        # Failed document without metadata can be deleted by owner
        with override_settings(MEDIA_ROOT=self.temp_media):
            failed_del_resp = self.client.post(
                reverse("document_delete", kwargs={"doc_id": self.doc_failed.pk}),
                follow=True,
            )
        self.assertRedirects(failed_del_resp, reverse("contract_list"))
        self.assertFalse(DocumentFile.objects.filter(pk=self.doc_failed.pk).exists())

        # ENCODER cannot delete or archive another user's document/contract
        self.assertEqual(
            self.client.post(
                reverse("document_delete", kwargs={"doc_id": self.doc_b.pk})
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("contract_archive", kwargs={"pk": self.contract_b.pk})
            ).status_code,
            404,
        )

        # Archive sets DocumentFile.status = ARCHIVED without deleting ContractMetadata
        archive_resp = self.client.post(
            reverse("contract_archive", kwargs={"pk": self.contract_a.pk}),
            follow=True,
        )
        self.assertRedirects(
            archive_resp, reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
        )
        self.doc_extracted.refresh_from_db()
        self.assertEqual(self.doc_extracted.status, DocumentFile.Status.ARCHIVED)
        self.assertTrue(ContractMetadata.objects.filter(pk=self.contract_a.pk).exists())


class ContractExportAndAuditTests(TestCase):
    """Verify Spec 02 JSON, XLSX, and CSV exports and ExportRecord logging (F-09, F-10)."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        ensure_default_carriers()
        self.password = "Str0ngShake!2026"
        self.admin_user = CustomUser.objects.create_user(
            username="exp_admin",
            email="exp_admin@shake.local",
            password=self.password,
            role=CustomUser.Role.ADMIN,
        )
        self.encoder_a = CustomUser.objects.create_user(
            username="exp_encoder_a",
            email="exp_a@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )
        self.encoder_b = CustomUser.objects.create_user(
            username="exp_encoder_b",
            email="exp_b@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )

        carrier = CarrierProfile.objects.get(carrier_code="MSCU")
        batch = BatchUpload.objects.create(
            user=self.encoder_a,
            batch_number="BATCH-20261118-301",
            total_files=1,
            status=BatchUpload.Status.COMPLETED,
        )
        doc = DocumentFile.objects.create(
            batch=batch,
            uploaded_file="contracts/pdfs/2026/11/exp.pdf",
            original_file_name="exp.pdf",
            file_hash_sha256="6" * 64,
            file_size_bytes=4096,
            page_count=2,
            status=DocumentFile.Status.EXTRACTED,
        )
        self.contract = ContractMetadata.objects.create(
            document=doc,
            carrier=carrier,
            contract_number="EXP001N25",
            trade_scope="NORTH AMERICA - ASIA (WB)",
            commodity_desc="Consumer Goods",
            effective_date=date(2025, 7, 1),
            expiration_date=date(2025, 12, 31),
        )
        FreightRate.objects.create(
            contract=self.contract,
            line_item_sequence=1,
            origin_port_code="USCHS",
            origin_port_name="Charleston",
            destination_port_code="CNDLC",
            destination_port_name="Dalian",
            equipment_type=EquipmentType.GP20,
            currency_code="USD",
            rate_amount=Decimal("360.00"),
        )
        FreightRate.objects.create(
            contract=self.contract,
            line_item_sequence=2,
            origin_port_code="USCHS",
            origin_port_name="Charleston",
            destination_port_code="CNDLC",
            destination_port_name="Dalian",
            equipment_type=EquipmentType.GP40,
            currency_code="USD",
            rate_amount=Decimal("450.00"),
        )
        ArbitraryCharge.objects.create(
            contract=self.contract,
            line_item_sequence=1,
            charge_type=ArbitraryCharge.ChargeType.ORIGIN,
            location_code="USATL",
            location_name="Atlanta",
            via_gateway_port="CHARLESTON, SC",
            equipment_type=EquipmentType.GP20,
            currency_code="USD",
            charge_amount=Decimal("450.00"),
            transport_mode=ArbitraryCharge.TransportMode.RAIL,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def test_json_xlsx_csv_exports_create_valid_files_and_audit_records(self):
        self.client.force_login(self.encoder_a)

        with override_settings(MEDIA_ROOT=self.temp_media):
            # 1. JSON Export
            json_resp = self.client.get(
                reverse("contract_export", kwargs={"pk": self.contract.pk, "fmt": "json"})
            )
            self.assertEqual(json_resp.status_code, 200)
            self.assertIn("attachment;", json_resp["Content-Disposition"])
            self.assertIn(".json", json_resp["Content-Disposition"])
            payload = json.loads(json_resp.content.decode("utf-8"))
            self.assertEqual(payload["contract_id"], "EXP001N25")
            self.assertEqual(len(payload["Rates"]), 1)
            self.assertEqual(payload["Rates"][0]["BaseRate 20"], "360.00")
            self.assertEqual(payload["Rates"][0]["BaseRate 40"], "450.00")
            self.assertEqual(len(payload["Origin_Arbitraries"]), 1)

            # 2. XLSX Export
            xlsx_resp = self.client.get(
                reverse("contract_export", kwargs={"pk": self.contract.pk, "fmt": "xlsx"})
            )
            self.assertEqual(xlsx_resp.status_code, 200)
            self.assertIn(".xlsx", xlsx_resp["Content-Disposition"])
            wb = openpyxl.load_workbook(io.BytesIO(xlsx_resp.content))
            self.assertIn("Rates", wb.sheetnames)
            self.assertIn("Origin_Arbitraries", wb.sheetnames)
            ws = wb["Rates"]
            self.assertGreaterEqual(ws.max_row, 2)

            # 3. CSV Export
            csv_resp = self.client.get(
                reverse("contract_export", kwargs={"pk": self.contract.pk, "fmt": "csv"})
            )
            self.assertEqual(csv_resp.status_code, 200)
            self.assertIn(".csv", csv_resp["Content-Disposition"])
            rows = list(csv.reader(io.StringIO(csv_resp.content.decode("utf-8"))))
            self.assertGreaterEqual(len(rows), 2)
            self.assertIn("Contract ID", rows[0])
            self.assertIn("EXP001N25", rows[1])

            # 4. Invalid format returns 404
            bad_resp = self.client.get(
                reverse("contract_export", kwargs={"pk": self.contract.pk, "fmt": "xml"})
            )
            self.assertEqual(bad_resp.status_code, 404)

        records = ExportRecord.objects.filter(contract=self.contract).order_by("export_id")
        self.assertEqual(records.count(), 3)
        self.assertEqual(
            [r.export_format for r in records],
            [
                ExportRecord.ExportFormat.JSON,
                ExportRecord.ExportFormat.XLSX,
                ExportRecord.ExportFormat.CSV,
            ],
        )
        self.assertTrue(all(r.user == self.encoder_a for r in records))

        # Audit log renders on contract_detail
        detail_resp = self.client.get(
            reverse("contract_detail", kwargs={"pk": self.contract.pk})
        )
        self.assertContains(detail_resp, "Export Audit Log")
        self.assertContains(detail_resp, "XLSX")
        self.assertContains(detail_resp, self.encoder_a.username)

    def test_export_ownership_isolation_and_empty_rates_safe(self):
        # Other encoder cannot export
        self.client.force_login(self.encoder_b)
        other_resp = self.client.get(
            reverse("contract_export", kwargs={"pk": self.contract.pk, "fmt": "json"})
        )
        self.assertEqual(other_resp.status_code, 404)
        self.assertEqual(ExportRecord.objects.count(), 0)

        # Remove all rates & arbitraries, then verify ADMIN export still produces valid files
        self.contract.freight_rates.all().delete()
        self.contract.arbitrary_charges.all().delete()
        self.client.force_login(self.admin_user)
        with override_settings(MEDIA_ROOT=self.temp_media):
            for fmt in ("json", "xlsx", "csv"):
                resp = self.client.get(
                    reverse("contract_export", kwargs={"pk": self.contract.pk, "fmt": fmt})
                )
                self.assertEqual(resp.status_code, 200)
                self.assertGreater(len(resp.content), 0)
        self.assertEqual(ExportRecord.objects.filter(user=self.admin_user).count(), 3)


class CarrierProfileAdminCrudTests(TestCase):
    """Verify Spec 02 Admin-only CarrierProfile CRUD and BR-03 enforcement."""

    def setUp(self):
        ensure_default_carriers()
        self.password = "Str0ngShake!2026"
        self.admin_user = CustomUser.objects.create_user(
            username="carrier_admin",
            email="c_admin@shake.local",
            password=self.password,
            role=CustomUser.Role.ADMIN,
        )
        self.encoder_user = CustomUser.objects.create_user(
            username="carrier_encoder",
            email="c_enc@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )
        self.carrier = CarrierProfile.objects.get(carrier_code="MSCU")

    def test_anonymous_and_encoder_blocked_from_carrier_routes(self):
        routes = [
            reverse("carrier_list"),
            reverse("carrier_create"),
            reverse("carrier_edit", kwargs={"pk": self.carrier.pk}),
        ]
        for url in routes:
            anon_resp = self.client.get(url)
            self.assertRedirects(anon_resp, f"{reverse('login')}?next={url}")

        self.client.force_login(self.encoder_user)
        for url in routes:
            enc_resp = self.client.get(url, follow=True)
            self.assertRedirects(enc_resp, reverse("encoder_dashboard"))
            self.assertContains(enc_resp, UNAUTHORIZED_DASHBOARD_MESSAGE)

        toggle_resp = self.client.post(
            reverse("carrier_toggle", kwargs={"pk": self.carrier.pk}),
            follow=True,
        )
        self.assertRedirects(toggle_resp, reverse("encoder_dashboard"))
        self.carrier.refresh_from_db()
        self.assertTrue(self.carrier.is_active)

    def test_admin_can_create_edit_and_toggle_carrier_profiles(self):
        self.client.force_login(self.admin_user)

        # List
        list_resp = self.client.get(reverse("carrier_list"))
        self.assertEqual(list_resp.status_code, 200)
        self.assertContains(list_resp, "MSCU")

        # Duplicate carrier code rejected (BR-03)
        dup_resp = self.client.post(
            reverse("carrier_create"),
            {
                "carrier_code": "mscu",
                "carrier_name": "Another MSC",
                "template_version": "v2.0",
                "is_active": True,
            },
        )
        self.assertEqual(dup_resp.status_code, 200)
        self.assertContains(dup_resp, "BR-03")

        # Create new carrier
        create_resp = self.client.post(
            reverse("carrier_create"),
            {
                "carrier_code": "oney",
                "carrier_name": "Ocean Network Express",
                "template_version": "v1.2",
                "is_active": True,
            },
            follow=True,
        )
        self.assertRedirects(create_resp, reverse("carrier_list"))
        created = CarrierProfile.objects.get(carrier_code="ONEY")
        self.assertEqual(created.carrier_name, "Ocean Network Express")
        self.assertTrue(created.is_active)

        # Edit carrier
        edit_resp = self.client.post(
            reverse("carrier_edit", kwargs={"pk": created.pk}),
            {
                "carrier_code": "ONEY",
                "carrier_name": "ONE Line Shipping",
                "template_version": "v2.0",
                "is_active": True,
            },
            follow=True,
        )
        self.assertRedirects(edit_resp, reverse("carrier_list"))
        created.refresh_from_db()
        self.assertEqual(created.carrier_name, "ONE Line Shipping")
        self.assertEqual(created.template_version, "v2.0")

        # Toggle active -> inactive -> active
        toggle_url = reverse("carrier_toggle", kwargs={"pk": created.pk})
        self.assertEqual(self.client.get(toggle_url).status_code, 405)

        t1 = self.client.post(toggle_url, follow=True)
        self.assertRedirects(t1, reverse("carrier_list"))
        created.refresh_from_db()
        self.assertFalse(created.is_active)

        self.client.post(toggle_url, follow=True)
        created.refresh_from_db()
        self.assertTrue(created.is_active)
