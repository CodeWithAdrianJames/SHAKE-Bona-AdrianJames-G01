"""
PD3 hardening tests: custom 404/500 pages, environment-driven settings,
server-side validation, IDOR guards, POST-only mutations, data integrity
(on_delete / validators / transactions), and query budgets.
"""
from __future__ import annotations

import io
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection
from django.db.models import RestrictedError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.views.defaults import server_error

from accounts.models import APIToken, CustomUser
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
from contracts.services.pipeline import ensure_default_carriers
from shake.settings import env_bool

PASSWORD = "Str0ngShake!2026"


class HardeningFixtureMixin:
    """Two encoders and one admin; encoder A and encoder B each own one contract."""

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.temp_media)
        self.media_override.enable()
        ensure_default_carriers()
        self.admin_user = CustomUser.objects.create_user(
            username="hard_admin",
            email="hard_admin@shake.local",
            password=PASSWORD,
            role=CustomUser.Role.ADMIN,
        )
        self.encoder_a = CustomUser.objects.create_user(
            username="hard_encoder_a",
            email="hard_a@shake.local",
            password=PASSWORD,
            role=CustomUser.Role.ENCODER,
        )
        self.encoder_b = CustomUser.objects.create_user(
            username="hard_encoder_b",
            email="hard_b@shake.local",
            password=PASSWORD,
            role=CustomUser.Role.ENCODER,
        )
        self.carrier = CarrierProfile.objects.get(carrier_code="MSCU")
        self.contract_a, self.doc_failed_a = self._make_contract(
            self.encoder_a, "HARD-A-001", "a", "BATCH-HARD-A"
        )
        self.contract_b, _ = self._make_contract(
            self.encoder_b, "HARD-B-001", "b", "BATCH-HARD-B"
        )
        self.rate_a = self.contract_a.freight_rates.get()
        self.rate_b = self.contract_b.freight_rates.get()

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    def _make_contract(self, user, number, hash_char, batch_number):
        batch = BatchUpload.objects.create(
            user=user,
            batch_number=batch_number,
            total_files=2,
            status=BatchUpload.Status.COMPLETED,
        )
        doc = DocumentFile.objects.create(
            batch=batch,
            uploaded_file=f"contracts/pdfs/2026/11/{number}.pdf",
            original_file_name=f"{number}.pdf",
            file_hash_sha256=hash_char * 64,
            file_size_bytes=2048,
            page_count=2,
            status=DocumentFile.Status.EXTRACTED,
        )
        failed = DocumentFile.objects.create(
            batch=batch,
            uploaded_file=f"contracts/pdfs/2026/11/{number}-failed.pdf",
            original_file_name=f"{number}-failed.pdf",
            file_hash_sha256=hash_char * 63 + "f",
            file_size_bytes=1024,
            page_count=1,
            status=DocumentFile.Status.FAILED,
        )
        contract = ContractMetadata.objects.create(
            document=doc,
            carrier=self.carrier,
            contract_number=number,
            trade_scope="ASIA - NORTH AMERICA (EB)",
            commodity_desc="General cargo",
            effective_date=date(2026, 1, 1),
            expiration_date=date(2026, 12, 31),
        )
        FreightRate.objects.create(
            contract=contract,
            line_item_sequence=1,
            origin_port_code="CNSHA",
            origin_port_name="Shanghai",
            destination_port_code="USLAX",
            destination_port_name="Los Angeles",
            equipment_type=EquipmentType.HC40,
            currency_code="USD",
            rate_amount=Decimal("1500.00"),
        )
        ArbitraryCharge.objects.create(
            contract=contract,
            line_item_sequence=1,
            charge_type=ArbitraryCharge.ChargeType.ORIGIN,
            location_code="CNWUH",
            location_name="Wuhan",
            via_gateway_port="CNSHA",
            equipment_type=EquipmentType.HC40,
            currency_code="USD",
            charge_amount=Decimal("250.00"),
        )
        return contract, failed

    def _valid_rate_post(self, **overrides):
        data = {
            "origin_port_code": "cnngb",
            "origin_port_name": "Ningbo",
            "destination_port_code": "uslgb",
            "destination_port_name": "Long Beach",
            "equipment_type": EquipmentType.GP40,
            "currency_code": "usd",
            "rate_amount": "1800.00",
        }
        data.update(overrides)
        return data

    def _valid_contract_post(self, contract, **overrides):
        data = {
            "contract_number": contract.contract_number,
            "carrier": contract.carrier_id,
            "trade_scope": contract.trade_scope,
            "commodity_desc": contract.commodity_desc,
            "effective_date": "2026-01-01",
            "expiration_date": "2026-12-31",
        }
        data.update(overrides)
        return data


# ---------------------------------------------------------------------------
# Custom error pages (PD3 Req 2)
# ---------------------------------------------------------------------------


class CustomErrorPageTests(HardeningFixtureMixin, TestCase):
    def test_unknown_url_renders_custom_404_for_anonymous_user(self):
        response = self.client.get("/this-route-does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "Page not found", status_code=404)
        self.assertContains(response, 'href="/accounts/login/"', status_code=404)
        self.assertNotContains(response, "Traceback", status_code=404)
        self.assertNotContains(response, "this-route-does-not-exist", status_code=404)

    def test_invalid_contract_id_renders_custom_404_for_signed_in_user(self):
        self.client.force_login(self.encoder_a)
        response = self.client.get(reverse("contract_detail", kwargs={"pk": 987654}))
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, 'href="/dashboard/"', status_code=404)
        self.assertNotContains(response, "ContractMetadata", status_code=404)

    def test_500_page_is_standalone_and_needs_no_database(self):
        request = RequestFactory().get("/contracts/")
        with self.assertNumQueries(0):
            response = server_error(request)
        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        self.assertIn("Something went wrong", body)
        self.assertIn('href="/dashboard/"', body)
        self.assertIn('href="/accounts/login/"', body)
        self.assertNotIn("Traceback", body)
        # Standalone: no base.html navbar and no CDN assets.
        self.assertNotIn("cdn.jsdelivr.net", body)
        self.assertNotIn("shakeNavbar", body)

    def test_unhandled_exception_returns_custom_500_without_leaking_details(self):
        self.client.force_login(self.encoder_a)
        self.client.raise_request_exception = False
        with patch(
            "contracts.views.ContractDetailView.get_context_data",
            side_effect=RuntimeError("secret-internal-detail"),
        ), self.assertLogs("django.request", level="ERROR"):
            response = self.client.get(
                reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
            )
        self.assertEqual(response.status_code, 500)
        self.assertNotContains(response, "secret-internal-detail", status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)
        self.assertContains(response, "Something went wrong", status_code=500)


class EnvironmentSettingsTests(SimpleTestCase):
    def test_env_bool_defaults_false_when_unset_or_blank(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(env_bool("DEBUG"))
        with patch.dict("os.environ", {"DEBUG": "   "}, clear=True):
            self.assertFalse(env_bool("DEBUG"))

    def test_env_bool_parses_explicit_values(self):
        for raw, expected in [("True", True), ("1", True), ("on", True), ("False", False), ("0", False)]:
            with self.subTest(raw=raw), patch.dict("os.environ", {"DEBUG": raw}, clear=True):
                self.assertIs(env_bool("DEBUG"), expected)

    def test_settings_source_has_no_hardcoded_secret_and_debug_defaults_false(self):
        source = (Path(__file__).resolve().parent.parent / "shake" / "settings.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("django-insecure", source)
        self.assertIn("DEBUG = env_bool('DEBUG', default=False)", source)

    def test_env_file_is_git_ignored(self):
        gitignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("\n.env\n", f"\n{gitignore}")


# ---------------------------------------------------------------------------
# Access control and IDOR guards (PD3 Req 3)
# ---------------------------------------------------------------------------


class AccessControlHardeningTests(HardeningFixtureMixin, TestCase):
    def test_anonymous_users_are_redirected_from_every_core_view(self):
        pk = self.contract_a.pk
        rate_id = self.rate_a.pk
        get_urls = [
            reverse("dashboard_root"),
            reverse("encoder_dashboard"),
            reverse("admin_dashboard"),
            reverse("contract_list"),
            reverse("contract_upload"),
            reverse("contract_detail", kwargs={"pk": pk}),
            reverse("contract_edit", kwargs={"pk": pk}),
            reverse("rate_create", kwargs={"pk": pk}),
            reverse("rate_edit", kwargs={"pk": pk, "rate_id": rate_id}),
            reverse("contract_export", kwargs={"pk": pk, "fmt": "json"}),
            reverse("carrier_list"),
            reverse("carrier_create"),
            reverse("carrier_edit", kwargs={"pk": self.carrier.pk}),
            reverse("profile"),
            reverse("profile_edit"),
            reverse("password_change"),
        ]
        post_urls = [
            reverse("rate_delete", kwargs={"pk": pk, "rate_id": rate_id}),
            reverse("contract_archive", kwargs={"pk": pk}),
            reverse("document_delete", kwargs={"doc_id": self.doc_failed_a.pk}),
            reverse("carrier_toggle", kwargs={"pk": self.carrier.pk}),
            reverse("api_token_create"),
        ]
        login_url = reverse("login")
        for url in get_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(login_url))
        for url in post_urls:
            with self.subTest(url=url):
                response = self.client.post(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(login_url))
        self.assertTrue(FreightRate.objects.filter(pk=rate_id).exists())
        self.assertTrue(DocumentFile.objects.filter(pk=self.doc_failed_a.pk).exists())

    def test_encoder_cannot_read_or_mutate_another_encoders_records_by_id(self):
        self.client.force_login(self.encoder_b)
        pk = self.contract_a.pk
        rate_id = self.rate_a.pk
        exports_before = ExportRecord.objects.count()

        blocked_gets = [
            reverse("contract_detail", kwargs={"pk": pk}),
            reverse("contract_edit", kwargs={"pk": pk}),
            reverse("rate_create", kwargs={"pk": pk}),
            reverse("rate_edit", kwargs={"pk": pk, "rate_id": rate_id}),
            reverse("contract_export", kwargs={"pk": pk, "fmt": "json"}),
            reverse("contract_export", kwargs={"pk": pk, "fmt": "xlsx"}),
            reverse("contract_export", kwargs={"pk": pk, "fmt": "csv"}),
        ]
        for url in blocked_gets:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

        blocked_posts = [
            (reverse("contract_edit", kwargs={"pk": pk}),
             self._valid_contract_post(self.contract_a, contract_number="HIJACKED")),
            (reverse("rate_create", kwargs={"pk": pk}), self._valid_rate_post()),
            (reverse("rate_edit", kwargs={"pk": pk, "rate_id": rate_id}),
             self._valid_rate_post(rate_amount="1.00")),
            (reverse("rate_delete", kwargs={"pk": pk, "rate_id": rate_id}), {}),
            (reverse("contract_archive", kwargs={"pk": pk}), {}),
            (reverse("document_delete", kwargs={"doc_id": self.doc_failed_a.pk}), {}),
        ]
        for url, data in blocked_posts:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 404)

        self.contract_a.refresh_from_db()
        self.rate_a.refresh_from_db()
        self.assertEqual(self.contract_a.contract_number, "HARD-A-001")
        self.assertEqual(self.contract_a.document.status, DocumentFile.Status.EXTRACTED)
        self.assertEqual(self.rate_a.rate_amount, Decimal("1500.00"))
        self.assertEqual(self.contract_a.freight_rates.count(), 1)
        self.assertTrue(DocumentFile.objects.filter(pk=self.doc_failed_a.pk).exists())
        self.assertEqual(ExportRecord.objects.count(), exports_before)

    def test_child_rate_cannot_be_reached_through_another_parent_contract(self):
        # Encoder B owns contract B but targets encoder A's rate via B's URL.
        self.client.force_login(self.encoder_b)
        pk_b = self.contract_b.pk
        foreign_rate = self.rate_a.pk
        self.assertEqual(
            self.client.get(
                reverse("rate_edit", kwargs={"pk": pk_b, "rate_id": foreign_rate})
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("rate_edit", kwargs={"pk": pk_b, "rate_id": foreign_rate}),
                self._valid_rate_post(rate_amount="1.00"),
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("rate_delete", kwargs={"pk": pk_b, "rate_id": foreign_rate})
            ).status_code,
            404,
        )
        self.rate_a.refresh_from_db()
        self.assertEqual(self.rate_a.rate_amount, Decimal("1500.00"))

    def test_admin_can_manage_any_contract(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(
            reverse("rate_edit", kwargs={"pk": self.contract_a.pk, "rate_id": self.rate_a.pk})
        )
        self.assertEqual(response.status_code, 200)

    def test_encoder_cannot_reach_admin_carrier_management(self):
        self.client.force_login(self.encoder_a)
        self.assertRedirects(
            self.client.get(reverse("carrier_list")),
            reverse("encoder_dashboard"),
        )
        response = self.client.post(reverse("carrier_toggle", kwargs={"pk": self.carrier.pk}))
        self.assertEqual(response.status_code, 302)
        self.carrier.refresh_from_db()
        self.assertTrue(self.carrier.is_active)

    def test_state_changing_actions_reject_get(self):
        self.client.force_login(self.admin_user)
        token = APIToken.objects.create(user=self.admin_user, name="cli")
        get_blocked = [
            reverse("rate_delete", kwargs={"pk": self.contract_a.pk, "rate_id": self.rate_a.pk}),
            reverse("contract_archive", kwargs={"pk": self.contract_a.pk}),
            reverse("document_delete", kwargs={"doc_id": self.doc_failed_a.pk}),
            reverse("carrier_toggle", kwargs={"pk": self.carrier.pk}),
            reverse("api_token_create"),
            reverse("api_token_revoke", kwargs={"pk": token.pk}),
            reverse("logout"),
        ]
        for url in get_blocked:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
        self.assertTrue(FreightRate.objects.filter(pk=self.rate_a.pk).exists())
        self.assertTrue(DocumentFile.objects.filter(pk=self.doc_failed_a.pk).exists())
        self.contract_a.document.refresh_from_db()
        self.assertEqual(self.contract_a.document.status, DocumentFile.Status.EXTRACTED)
        token.refresh_from_db()
        self.assertTrue(token.is_active)

    def test_post_forms_require_csrf_token(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.encoder_a)
        response = csrf_client.post(
            reverse("rate_delete", kwargs={"pk": self.contract_a.pk, "rate_id": self.rate_a.pk})
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(FreightRate.objects.filter(pk=self.rate_a.pk).exists())

    def test_destructive_forms_carry_confirmation_prompts_and_csrf(self):
        self.client.force_login(self.encoder_a)
        detail = self.client.get(reverse("contract_detail", kwargs={"pk": self.contract_a.pk}))
        self.assertContains(detail, "data-confirm=\"Permanently delete rate row #1")
        self.assertContains(detail, "data-confirm=\"Archive contract HARD-A-001?")
        listing = self.client.get(reverse("contract_list"))
        self.assertContains(listing, "data-confirm=\"Permanently delete the failed document")
        self.assertContains(listing, "csrfmiddlewaretoken")


class TemplateSecurityAuditTests(SimpleTestCase):
    """Static audit: CSRF on every POST form and no |safe on user-supplied data."""

    templates_dir = Path(__file__).resolve().parent.parent / "templates"

    def test_every_post_form_contains_csrf_token(self):
        import re

        form_pattern = re.compile(
            r"<form\b[^>]*method=\"post\"[^>]*>(.*?)</form>", re.IGNORECASE | re.DOTALL
        )
        for template in self.templates_dir.rglob("*.html"):
            text = template.read_text(encoding="utf-8")
            for match in form_pattern.finditer(text):
                with self.subTest(template=template.name):
                    self.assertIn("{% csrf_token %}", match.group(1))

    def test_safe_filter_is_only_used_on_developer_defined_help_text(self):
        import re

        for template in self.templates_dir.rglob("*.html"):
            text = template.read_text(encoding="utf-8")
            for match in re.finditer(r"\{\{\s*([^}|]+)\|safe\s*\}\}", text):
                with self.subTest(template=template.name, expr=match.group(1)):
                    self.assertTrue(match.group(1).strip().endswith(".help_text"))


# ---------------------------------------------------------------------------
# Server-side validation and feedback (PD3 Req 2)
# ---------------------------------------------------------------------------


class ServerSideValidationTests(HardeningFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.encoder_a)

    def test_contract_dates_rejected_server_side_with_single_error(self):
        url = reverse("contract_edit", kwargs={"pk": self.contract_a.pk})
        response = self.client.post(
            url,
            self._valid_contract_post(
                self.contract_a, effective_date="2026-10-01", expiration_date="2026-08-01"
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Expiration date must be on or after the effective date (BR-10).",
            count=1,
        )
        self.assertContains(response, "Contract metadata could not be updated")
        self.contract_a.refresh_from_db()
        self.assertEqual(self.contract_a.expiration_date, date(2026, 12, 31))

    def test_contract_same_day_validity_and_missing_fields(self):
        url = reverse("contract_edit", kwargs={"pk": self.contract_a.pk})
        ok = self.client.post(
            url,
            self._valid_contract_post(
                self.contract_a, effective_date="2026-05-05", expiration_date="2026-05-05"
            ),
        )
        self.assertRedirects(ok, reverse("contract_detail", kwargs={"pk": self.contract_a.pk}))
        missing = self.client.post(
            url,
            self._valid_contract_post(
                self.contract_a, effective_date="", trade_scope="   ", expiration_date="not-a-date"
            ),
        )
        self.assertEqual(missing.status_code, 200)
        form = missing.context["form"]
        self.assertIn("effective_date", form.errors)
        self.assertIn("expiration_date", form.errors)
        self.assertIn("trade_scope", form.errors)

    def test_rate_amount_rejects_zero_negative_and_non_numeric(self):
        url = reverse("rate_create", kwargs={"pk": self.contract_a.pk})
        for bad in ["0", "0.00", "-5", "abc", "NaN", "1e999", "12345678901234.00"]:
            with self.subTest(rate_amount=bad):
                response = self.client.post(url, self._valid_rate_post(rate_amount=bad))
                self.assertEqual(response.status_code, 200)
                self.assertIn("rate_amount", response.context["form"].errors)
                self.assertContains(response, "Freight rate could not be saved")
        self.assertEqual(self.contract_a.freight_rates.count(), 1)

    def test_rate_ports_compared_case_insensitively_and_error_reported_once(self):
        url = reverse("rate_edit", kwargs={"pk": self.contract_a.pk, "rate_id": self.rate_a.pk})
        response = self.client.post(
            url,
            self._valid_rate_post(origin_port_code="uslax", destination_port_code="USLAX"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Destination port code must differ from origin port code (BR-13).",
            count=1,
        )

    def test_rate_rejects_invalid_equipment_and_currency(self):
        url = reverse("rate_create", kwargs={"pk": self.contract_a.pk})
        response = self.client.post(
            url, self._valid_rate_post(equipment_type="99XX", currency_code="US1")
        )
        self.assertEqual(response.status_code, 200)
        errors = response.context["form"].errors
        self.assertIn("equipment_type", errors)
        self.assertIn("currency_code", errors)

    def test_valid_rate_create_normalizes_codes_and_flashes_success(self):
        url = reverse("rate_create", kwargs={"pk": self.contract_a.pk})
        response = self.client.post(url, self._valid_rate_post(), follow=True)
        self.assertRedirects(response, reverse("contract_detail", kwargs={"pk": self.contract_a.pk}))
        self.assertContains(response, "Added rate row #2")
        new_rate = self.contract_a.freight_rates.get(line_item_sequence=2)
        self.assertEqual(new_rate.origin_port_code, "CNNGB")
        self.assertEqual(new_rate.currency_code, "USD")

    def test_rate_create_integrity_error_shows_message_instead_of_500(self):
        url = reverse("rate_create", kwargs={"pk": self.contract_a.pk})
        with patch.object(
            FreightRate, "save", side_effect=IntegrityError("duplicate seq")
        ), self.assertLogs("contracts.views", level="ERROR"):
            response = self.client.post(url, self._valid_rate_post())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "could not be saved because the contract changed")
        self.assertNotContains(response, "duplicate seq")
        self.assertEqual(self.contract_a.freight_rates.count(), 1)

    def test_unknown_export_format_is_clean_404(self):
        response = self.client.get(
            reverse("contract_export", kwargs={"pk": self.contract_a.pk, "fmt": "exe"})
        )
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")

    def test_export_write_failure_redirects_with_error_message(self):
        with patch(
            "contracts.views.export_contract_artifact", side_effect=OSError("disk full")
        ), self.assertLogs("contracts.views", level="ERROR"):
            response = self.client.get(
                reverse("contract_export", kwargs={"pk": self.contract_a.pk, "fmt": "csv"}),
                follow=True,
            )
        self.assertRedirects(response, reverse("contract_detail", kwargs={"pk": self.contract_a.pk}))
        self.assertContains(response, "could not be written to disk")
        self.assertNotContains(response, "disk full")

    def test_mutations_flash_feedback(self):
        delete = self.client.post(
            reverse("rate_delete", kwargs={"pk": self.contract_a.pk, "rate_id": self.rate_a.pk}),
            follow=True,
        )
        self.assertContains(delete, "Deleted freight rate row #1")
        archive = self.client.post(
            reverse("contract_archive", kwargs={"pk": self.contract_a.pk}), follow=True
        )
        self.assertContains(archive, "has been archived")
        again = self.client.post(
            reverse("contract_archive", kwargs={"pk": self.contract_a.pk}), follow=True
        )
        self.assertContains(again, "is already archived")

    def test_profile_photo_size_is_validated_server_side(self):
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (4, 4), "white").save(buffer, format="PNG")
        photo = SimpleUploadedFile("avatar.png", buffer.getvalue(), content_type="image/png")
        with patch("accounts.forms.MAX_PROFILE_PHOTO_BYTES", 10):
            response = self.client.post(
                reverse("profile_edit"),
                {
                    "first_name": "Hard",
                    "last_name": "Encoder",
                    "email": "hard_a@shake.local",
                    "profile_photo": photo,
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("profile_photo", response.context["form"].errors)
        self.encoder_a.refresh_from_db()
        self.assertFalse(self.encoder_a.profile_photo)


# ---------------------------------------------------------------------------
# Data integrity and query optimization (PD3 Req 4)
# ---------------------------------------------------------------------------


class DataIntegrityHardeningTests(HardeningFixtureMixin, TestCase):
    def test_model_validators_reject_out_of_range_values(self):
        charge = self.contract_a.arbitrary_charges.get()
        charge.charge_amount = Decimal("-0.01")
        with self.assertRaises(ValidationError) as ctx:
            charge.full_clean()
        self.assertIn("charge_amount", ctx.exception.message_dict)

        charge.charge_amount = Decimal("0.00")  # zero arbitraries are allowed
        charge.confidence_score = Decimal("1.200")
        with self.assertRaises(ValidationError) as ctx:
            charge.full_clean()
        self.assertIn("confidence_score", ctx.exception.message_dict)

        rate = self.rate_a
        rate.rate_amount = Decimal("0.00")
        rate.source_page_start = 3
        rate.source_page_end = 2
        with self.assertRaises(ValidationError) as ctx:
            rate.full_clean()
        self.assertIn("rate_amount", ctx.exception.message_dict)
        self.assertIn("source_page_end", ctx.exception.message_dict)

    def test_contract_model_clean_enforces_br10(self):
        self.contract_a.effective_date = date(2026, 6, 1)
        self.contract_a.expiration_date = date(2026, 5, 31)
        with self.assertRaises(ValidationError) as ctx:
            self.contract_a.full_clean()
        self.assertIn("expiration_date", ctx.exception.message_dict)

    def test_export_audit_records_block_contract_hard_delete(self):
        ExportRecord.objects.create(
            user=self.encoder_a,
            contract=self.contract_a,
            export_format=ExportRecord.ExportFormat.JSON,
            file_path="contracts/exports/x.json",
        )
        with self.assertRaises(RestrictedError):
            self.contract_a.delete()
        self.assertTrue(ContractMetadata.objects.filter(pk=self.contract_a.pk).exists())

    def test_failed_document_delete_removes_rows_then_file_after_commit(self):
        self.client.force_login(self.encoder_a)
        doc = self.doc_failed_a
        doc.uploaded_file.save("failed-a.pdf", ContentFile(b"%PDF-1.4 test"), save=True)
        stored_path = Path(doc.uploaded_file.path)
        ProcessingJob.objects.create(
            document=doc,
            status=ProcessingJob.Status.FAILED,
            error_message="parse error",
        )
        self.assertTrue(stored_path.exists())

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client.post(
                reverse("document_delete", kwargs={"doc_id": doc.pk}), follow=True
            )
        self.assertEqual(len(callbacks), 1)
        self.assertContains(response, "Deleted unextracted document")
        self.assertFalse(DocumentFile.objects.filter(pk=doc.pk).exists())
        self.assertFalse(ProcessingJob.objects.filter(document_id=doc.pk).exists())
        self.assertFalse(stored_path.exists())

    def test_contract_detail_query_count_does_not_grow_with_rows(self):
        self.client.force_login(self.encoder_a)
        url = reverse("contract_detail", kwargs={"pk": self.contract_a.pk})
        # One export row up front so the baseline already includes the
        # export_records__user prefetch (Django skips it for empty relations).
        ExportRecord.objects.create(
            user=self.encoder_a,
            contract=self.contract_a,
            export_format=ExportRecord.ExportFormat.JSON,
            file_path="contracts/exports/baseline.json",
        )
        self.client.get(url)  # warm session/content-type caches

        with CaptureQueriesContext(connection) as baseline:
            self.assertEqual(self.client.get(url).status_code, 200)

        for seq in range(2, 8):
            FreightRate.objects.create(
                contract=self.contract_a,
                line_item_sequence=seq,
                origin_port_code="CNSHA",
                origin_port_name="Shanghai",
                destination_port_code=f"USX{seq:02d}",
                destination_port_name="Somewhere",
                equipment_type=EquipmentType.GP20,
                rate_amount=Decimal("100.00"),
            )
            ExportRecord.objects.create(
                user=self.encoder_a,
                contract=self.contract_a,
                export_format=ExportRecord.ExportFormat.CSV,
                file_path=f"contracts/exports/{seq}.csv",
            )

        with CaptureQueriesContext(connection) as grown:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(len(grown), len(baseline))

    def test_contract_list_query_count_does_not_grow_with_contracts(self):
        self.client.force_login(self.admin_user)
        url = reverse("contract_list")
        self.client.get(url)
        with CaptureQueriesContext(connection) as baseline:
            self.assertEqual(self.client.get(url).status_code, 200)
        for idx in range(3):
            self._make_contract(self.encoder_a, f"HARD-EXTRA-{idx}", str(idx), f"BATCH-X-{idx}")
        with CaptureQueriesContext(connection) as grown:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(len(grown), len(baseline))
