from __future__ import annotations

import shutil
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pymupdf
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import RestrictedError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser
from contracts.engine.errors import IngestionError
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
from contracts.services.pipeline import (
    ensure_default_carriers,
    ingest_uploaded_files,
)

SAMPLE_DIGITAL_DIR = Path(
    r"C:\Users\l13x16w10\Downloads\Shake--main\Shake--main\input\data\digital"
)


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

    def test_real_sample_pdf_extraction_if_available(self):
        sample_pdf = SAMPLE_DIGITAL_DIR / "test_orig_arb.pdf"
        if not sample_pdf.exists():
            self.skipTest("Sample digital PDF fixture not found on disk.")

        upload = SimpleUploadedFile(
            sample_pdf.name,
            sample_pdf.read_bytes(),
            content_type="application/pdf",
        )
        with override_settings(MEDIA_ROOT=self.temp_media):
            outcome = ingest_uploaded_files(self.encoder, [upload])

        self.assertEqual(len(outcome.succeeded), 1)
        contract = outcome.succeeded[0]
        self.assertGreater(contract.freight_rates.count(), 0)
        self.assertGreater(contract.arbitrary_charges.count(), 0)


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
