from datetime import date
from decimal import Decimal

from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import CustomUser
from contracts.models import (
    BatchUpload,
    CarrierProfile,
    ContractMetadata,
    DocumentFile,
    EquipmentType,
    ExportRecord,
    FreightRate,
    ProcessingJob,
)
from contracts.services.pipeline import ensure_default_carriers
from dashboard.views import UNAUTHORIZED_DASHBOARD_MESSAGE, role_required


class RoleBasedDashboardAccessTests(TestCase):
    """
    Stage 3 test suite verifying role-specific dashboard routing, post-login redirects,
    and strict cross-role URL access control between Operations Admins and Freight Encoders.
    """

    def setUp(self):
        self.password = "Str0ngShake!2026"
        self.admin_user = CustomUser.objects.create_user(
            username="ops_admin",
            email="admin@shakelogistics.com",
            password=self.password,
            first_name="Elena",
            last_name="Vance",
            role=CustomUser.Role.ADMIN,
            department="IT Operations & Governance",
        )
        self.encoder_user = CustomUser.objects.create_user(
            username="freight_encoder",
            email="encoder@shakelogistics.com",
            password=self.password,
            first_name="Adrian James",
            last_name="Bona",
            role=CustomUser.Role.ENCODER,
            department="Pricing & Tariff Management",
        )

    def test_unauthenticated_visitors_redirect_to_login(self):
        for route_name in ("dashboard", "admin_dashboard", "encoder_dashboard"):
            with self.subTest(route=route_name):
                target_url = reverse(route_name)
                response = self.client.get(target_url)
                self.assertRedirects(
                    response,
                    f"{reverse('login')}?next={target_url}",
                )

    def test_admin_login_redirects_to_admin_dashboard_and_renders_content(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.admin_user.username, "password": self.password},
            follow=True,
        )
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/admin_dashboard.html")
        self.assertContains(response, "Operations Admin Control Center")
        self.assertContains(response, "MSC")
        self.assertContains(response, "CMA CGM")
        self.assertContains(response, "COSCO")
        self.assertContains(response, self.encoder_user.username)

    def test_encoder_login_redirects_to_encoder_dashboard_and_renders_content(self):
        response = self.client.post(
            reverse("login"),
            {"username": self.encoder_user.username, "password": self.password},
            follow=True,
        )
        self.assertRedirects(response, reverse("encoder_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard/encoder_dashboard.html")
        self.assertContains(response, "Upload Ocean Freight Contract PDF")
        self.assertContains(response, ".xlsx")
        self.assertContains(response, ".csv")
        self.assertContains(response, ".json")

    def test_root_dashboard_redirect_view_routes_by_user_role(self):
        self.client.force_login(self.admin_user)
        admin_resp = self.client.get(reverse("dashboard"))
        self.assertRedirects(admin_resp, reverse("admin_dashboard"))

        self.client.force_login(self.encoder_user)
        encoder_resp = self.client.get(reverse("dashboard"))
        self.assertRedirects(encoder_resp, reverse("encoder_dashboard"))

    def test_encoder_cannot_access_admin_dashboard(self):
        self.client.force_login(self.encoder_user)
        response = self.client.get(reverse("admin_dashboard"), follow=True)
        self.assertRedirects(response, reverse("encoder_dashboard"))
        self.assertContains(response, UNAUTHORIZED_DASHBOARD_MESSAGE)
        self.assertTemplateNotUsed(response, "dashboard/admin_dashboard.html")

    def test_admin_cannot_access_encoder_dashboard(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("encoder_dashboard"), follow=True)
        self.assertRedirects(response, reverse("admin_dashboard"))
        self.assertContains(response, UNAUTHORIZED_DASHBOARD_MESSAGE)
        self.assertTemplateNotUsed(response, "dashboard/encoder_dashboard.html")

    def test_role_required_decorator_blocks_wrong_role_with_403_option(self):
        @role_required(CustomUser.Role.ADMIN, return_403=True)
        def sample_admin_only_view(request):
            return HttpResponse("Admin secret")

        factory = RequestFactory()
        request = factory.get("/dashboard/admin/custom/")
        request.user = self.encoder_user

        # Attach message storage fallback via client session
        self.client.force_login(self.encoder_user)
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.contrib.sessions.middleware import SessionMiddleware

        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        setattr(request, "_messages", FallbackStorage(request))

        response = sample_admin_only_view(request)
        self.assertEqual(response.status_code, 403)
        self.assertIn(UNAUTHORIZED_DASHBOARD_MESSAGE, response.content.decode())


class LiveDashboardMetricsTests(TestCase):
    """Verify Spec 02 live PostgreSQL querysets and navbar wiring on both role dashboards."""

    def setUp(self):
        ensure_default_carriers()
        self.password = "Str0ngShake!2026"
        self.admin_user = CustomUser.objects.create_user(
            username="live_admin",
            email="live_admin@shake.local",
            password=self.password,
            role=CustomUser.Role.ADMIN,
        )
        self.encoder_1 = CustomUser.objects.create_user(
            username="live_encoder_1",
            email="live_enc1@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )
        self.encoder_2 = CustomUser.objects.create_user(
            username="live_encoder_2",
            email="live_enc2@shake.local",
            password=self.password,
            role=CustomUser.Role.ENCODER,
        )

        carrier = CarrierProfile.objects.get(carrier_code="MSCU")

        batch_1 = BatchUpload.objects.create(
            user=self.encoder_1,
            batch_number="BATCH-20261118-501",
            total_files=1,
            status=BatchUpload.Status.COMPLETED,
        )
        doc_1 = DocumentFile.objects.create(
            batch=batch_1,
            uploaded_file="contracts/pdfs/2026/11/enc1.pdf",
            original_file_name="enc1_contract.pdf",
            file_hash_sha256="a" * 64,
            file_size_bytes=2048,
            page_count=2,
            status=DocumentFile.Status.EXTRACTED,
        )
        ProcessingJob.objects.create(
            document=doc_1,
            job_type=ProcessingJob.JobType.FULL_PIPELINE,
            status=ProcessingJob.Status.COMPLETED,
        )
        self.contract_1 = ContractMetadata.objects.create(
            document=doc_1,
            carrier=carrier,
            contract_number="ENC1-LIVE-01",
            trade_scope="TRANS-PACIFIC",
            commodity_desc="Electronics",
            effective_date=date(2025, 7, 1),
            expiration_date=date(2025, 12, 31),
        )
        FreightRate.objects.create(
            contract=self.contract_1,
            line_item_sequence=1,
            origin_port_code="CNSHA",
            origin_port_name="Shanghai",
            destination_port_code="USLAX",
            destination_port_name="Los Angeles",
            equipment_type=EquipmentType.GP40,
            rate_amount=Decimal("2200.00"),
        )
        ExportRecord.objects.create(
            user=self.encoder_1,
            contract=self.contract_1,
            export_format=ExportRecord.ExportFormat.XLSX,
            file_path="contracts/exports/enc1_mapped.xlsx",
        )

        batch_2 = BatchUpload.objects.create(
            user=self.encoder_2,
            batch_number="BATCH-20261118-502",
            total_files=1,
            status=BatchUpload.Status.COMPLETED,
        )
        doc_2 = DocumentFile.objects.create(
            batch=batch_2,
            uploaded_file="contracts/pdfs/2026/11/enc2.pdf",
            original_file_name="enc2_secret_contract.pdf",
            file_hash_sha256="b" * 64,
            file_size_bytes=2048,
            page_count=2,
            status=DocumentFile.Status.EXTRACTED,
        )
        self.contract_2 = ContractMetadata.objects.create(
            document=doc_2,
            carrier=carrier,
            contract_number="ENC2-SECRET-99",
            trade_scope="ASIA - EUROPE",
            commodity_desc="Textiles",
            effective_date=date(2025, 8, 1),
            expiration_date=date(2025, 12, 31),
        )

    def test_encoder_dashboard_displays_live_scoped_metrics_and_nav_links(self):
        self.client.force_login(self.encoder_1)
        resp = self.client.get(reverse("encoder_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["user_batches_count"], 1)
        self.assertEqual(resp.context["extracted_contracts_count"], 1)
        self.assertEqual(resp.context["total_rate_rows_count"], 1)
        self.assertEqual(resp.context["exports_generated_count"], 1)

        # Renders own contract & navbar links, excludes encoder_2's contract
        self.assertContains(resp, "enc1_contract.pdf")
        self.assertContains(resp, "ENC1-LIVE-01")
        self.assertNotContains(resp, "ENC2-SECRET-99")
        self.assertNotContains(resp, "enc2_secret_contract.pdf")
        self.assertContains(resp, reverse("contract_upload"))
        self.assertContains(resp, reverse("contract_list"))

    def test_admin_dashboard_displays_live_system_metrics_and_nav_links(self):
        self.client.force_login(self.admin_user)
        resp = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_users_count"], 3)
        self.assertEqual(resp.context["total_batches_count"], 2)
        self.assertEqual(resp.context["extracted_contracts_count"], 2)
        self.assertEqual(resp.context["total_rate_rows_count"], 1)
        self.assertEqual(resp.context["total_exports_count"], 1)
        self.assertGreaterEqual(resp.context["active_carriers_count"], 5)

        self.assertContains(resp, "enc1_contract.pdf")
        self.assertContains(resp, "ENC1-LIVE-01")
        self.assertContains(resp, reverse("carrier_list"))
        self.assertContains(resp, reverse("contract_list"))
        self.assertContains(resp, reverse("contract_upload"))
