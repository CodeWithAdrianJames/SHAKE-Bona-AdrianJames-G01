"""
PD3 hardening verification suite.

One test class per PD3 rubric requirement, plus a PD1 standard-feature
regression suite, so each requirement can be checked by name:

1. ``PD3ErrorPageTests``            custom 404/500 pages with DEBUG=False
2. ``PD3ServerSideValidationTests`` model/form business rules (BR-10, BR-12, BR-13),
                                     page spans, profile photo limits
   ``PD3MessagesAndPRGTests``       django.contrib.messages feedback and
                                     Post/Redirect/Get on every form
3. ``PD3AuthenticationGuardTests``  anonymous access redirects to login
   ``PD3IDORIsolationTests``        ENCODER-to-ENCODER isolation (404) and ADMIN scope
   ``PD3RequestSafetyTests``        GET -> 405 on state-changing endpoints,
                                     POST without CSRF token -> 403
4. ``PD1RegistrationTests``, ``PD1LoginLogoutTests``, ``PD1RoleDashboardTests``,
   ``PD1ProfileAndTokenTests``      PD1 standard features end to end

Run with: ``$env:DATABASE_URL=" "; .\\.venv\\Scripts\\python.exe manage.py test -v 2``

Notes on scope (see docs/context/architecture-context.md):
- There is no contract hard-delete view. Contracts are archived (BR-09); the only
  delete endpoints are ``rate_delete`` and ``document_delete`` (PENDING/FAILED
  documents only), and both are covered here.
- ``ArbitraryCharge`` rows have no web edit/delete views. Their amount rule is
  verified at the model-validator and database-constraint layers, and their
  read paths (detail, export, API) are covered by the IDOR tests.
- The edit views (``contract_edit``, ``rate_edit``) render their form on GET by
  design. The ``405`` checks cover the POST-only action endpoints.
"""
from __future__ import annotations

import io
import shutil
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.messages import ERROR, INFO, SUCCESS, get_messages
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.template.loader import get_template
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.views.defaults import server_error

from accounts.forms import MAX_PROFILE_PHOTO_BYTES
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
)
from contracts.services.pipeline import ensure_default_carriers

PASSWORD = "Pd3Verify!Shake2026"
NEW_PASSWORD = "Pd3Rotated!Shake2027"

# Strings that only appear on Django's technical (DEBUG=True) error pages or in
# raw exception text. None of them may reach a user-facing error page.
DEBUG_PAGE_MARKERS = (
    "Traceback",
    "Request Method:",
    "Django tried these URL patterns",
    "You're seeing this error because you have",
    "matches the given query",
    "Http404",
)


def _png_bytes(size=(4, 4)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=(63, 40, 112)).save(buffer, format="PNG")
    return buffer.getvalue()


def _oversized_bmp_bytes() -> bytes:
    """A genuine, decodable image larger than the 5 MB profile photo cap."""
    from PIL import Image

    buffer = io.BytesIO()
    # 1400 x 1400 x 3 bytes of uncompressed pixels is about 5.9 MB.
    Image.new("RGB", (1400, 1400), color=(13, 71, 161)).save(buffer, format="BMP")
    data = buffer.getvalue()
    assert len(data) > MAX_PROFILE_PHOTO_BYTES
    return data


def _flash(response) -> list[tuple[int, str]]:
    """Return (level, message) pairs queued for the client after `response`.

    Levels are compared numerically because MESSAGE_TAGS maps ERROR to the
    Bootstrap "danger" class.
    """
    return [(m.level, str(m)) for m in get_messages(response.wsgi_request)]


class PD3FixtureMixin:
    """
    One ADMIN and two ENCODERs. Each encoder owns one batch containing an
    extracted contract (one freight rate, one origin arbitrary) and one FAILED
    document, plus one active API token.
    """

    def setUp(self):
        self.temp_media = tempfile.mkdtemp()
        self.media_override = override_settings(MEDIA_ROOT=self.temp_media)
        self.media_override.enable()
        ensure_default_carriers()
        self.carrier = CarrierProfile.objects.get(carrier_code="MSCU")

        self.admin_user = self._make_user("pd3_admin", "pd3_admin@shake.local", CustomUser.Role.ADMIN)
        self.encoder_a = self._make_user("pd3_encoder_a", "pd3_a@shake.local", CustomUser.Role.ENCODER)
        self.encoder_b = self._make_user("pd3_encoder_b", "pd3_b@shake.local", CustomUser.Role.ENCODER)

        self.contract_a, self.failed_doc_a = self._make_contract(self.encoder_a, "PD3-A-001", "a")
        self.contract_b, self.failed_doc_b = self._make_contract(self.encoder_b, "PD3-B-001", "b")
        self.rate_a = self.contract_a.freight_rates.get()
        self.rate_b = self.contract_b.freight_rates.get()
        self.token_a = APIToken.objects.create(user=self.encoder_a, name="A CLI")
        self.token_b = APIToken.objects.create(user=self.encoder_b, name="B CLI")

    def tearDown(self):
        self.media_override.disable()
        shutil.rmtree(self.temp_media, ignore_errors=True)

    # -- builders -----------------------------------------------------------

    @staticmethod
    def _make_user(username, email, role):
        return CustomUser.objects.create_user(
            username=username,
            email=email,
            password=PASSWORD,
            role=role,
            first_name=username.split("_")[-1].title(),
            last_name="Tester",
        )

    def _make_contract(self, user, number, hash_char):
        batch = BatchUpload.objects.create(
            user=user,
            batch_number=f"BATCH-{number}",
            total_files=2,
            status=BatchUpload.Status.COMPLETED,
        )
        doc = DocumentFile.objects.create(
            batch=batch,
            uploaded_file=f"contracts/pdfs/2026/11/{number}.pdf",
            original_file_name=f"{number}.pdf",
            file_hash_sha256=hash_char * 64,
            file_size_bytes=4096,
            page_count=3,
            status=DocumentFile.Status.EXTRACTED,
        )
        failed = DocumentFile.objects.create(
            batch=batch,
            uploaded_file=f"contracts/pdfs/2026/11/{number}-failed.pdf",
            original_file_name=f"{number}-failed.pdf",
            file_hash_sha256=hash_char * 63 + "e",
            file_size_bytes=1024,
            page_count=1,
            status=DocumentFile.Status.FAILED,
        )
        contract = ContractMetadata.objects.create(
            document=doc,
            carrier=self.carrier,
            contract_number=number,
            trade_scope="ASIA - NORTH AMERICA (EB)",
            commodity_desc="FAK general cargo",
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

    # -- POST payloads ------------------------------------------------------

    def contract_post(self, contract, **overrides):
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

    @staticmethod
    def rate_post(**overrides):
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

    @staticmethod
    def profile_post(user, **overrides):
        data = {
            "first_name": user.first_name or "First",
            "last_name": user.last_name or "Last",
            "email": user.email,
            "contact_number": "+63 917 000 0000",
            "department": "Pricing",
        }
        data.update(overrides)
        return data

    # -- assertions ---------------------------------------------------------

    def assertCustom404(self, response):
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "Page not found", status_code=404)
        for marker in DEBUG_PAGE_MARKERS:
            self.assertNotContains(response, marker, status_code=404)


# ===========================================================================
# 1. Custom error pages and DEBUG hardening
# ===========================================================================


@override_settings(DEBUG=False)
class PD3ErrorPageTests(PD3FixtureMixin, TestCase):
    def test_debug_is_disabled_and_error_templates_exist(self):
        self.assertFalse(settings.DEBUG)
        for name in ("404.html", "500.html"):
            with self.subTest(template=name):
                self.assertIsNotNone(get_template(name))

    def test_unknown_routes_render_custom_404_for_anonymous_and_signed_in_users(self):
        paths = [
            "/pd3-route-does-not-exist/",
            "/contracts/not-a-number/",
            "/contracts/1/rates/abc/edit/",
            "/dashboard/superuser/",
        ]
        for path in paths:
            with self.subTest(path=path, user="anonymous"):
                response = self.client.get(path)
                self.assertCustom404(response)
                self.assertNotContains(response, path, status_code=404)
                self.assertContains(response, 'href="/accounts/login/"', status_code=404)

        self.client.force_login(self.encoder_a)
        for path in paths:
            with self.subTest(path=path, user="encoder"):
                response = self.client.get(path)
                self.assertCustom404(response)
                self.assertNotContains(response, path, status_code=404)
                self.assertContains(response, 'href="/dashboard/"', status_code=404)
                self.assertContains(response, 'href="/contracts/"', status_code=404)

    def test_invalid_object_ids_render_custom_404_via_get_object_or_404(self):
        self.client.force_login(self.encoder_a)
        own = self.contract_a.pk
        missing = 987654
        get_urls = [
            reverse("contract_detail", kwargs={"pk": missing}),
            reverse("contract_edit", kwargs={"pk": missing}),
            reverse("rate_create", kwargs={"pk": missing}),
            reverse("rate_edit", kwargs={"pk": own, "rate_id": missing}),
            reverse("contract_export", kwargs={"pk": missing, "fmt": "json"}),
            reverse("contract_export", kwargs={"pk": own, "fmt": "pdf"}),
        ]
        post_urls = [
            reverse("rate_delete", kwargs={"pk": own, "rate_id": missing}),
            reverse("contract_archive", kwargs={"pk": missing}),
            reverse("document_delete", kwargs={"doc_id": missing}),
            reverse("api_token_revoke", kwargs={"pk": missing}),
        ]
        for url in get_urls:
            with self.subTest(method="GET", url=url):
                self.assertCustom404(self.client.get(url))
        for url in post_urls:
            with self.subTest(method="POST", url=url):
                self.assertCustom404(self.client.post(url))
        self.assertEqual(ExportRecord.objects.count(), 0)

    def test_500_template_renders_with_empty_context_and_zero_queries(self):
        with self.assertNumQueries(0):
            body = get_template("500.html").render({})
        self.assertIn("Something went wrong", body)
        self.assertIn('href="/dashboard/"', body)
        self.assertIn('href="/accounts/login/"', body)
        for marker in DEBUG_PAGE_MARKERS:
            self.assertNotIn(marker, body)

    def test_500_template_source_has_no_context_dependencies(self):
        source = (Path(settings.BASE_DIR) / "templates" / "500.html").read_text(encoding="utf-8")
        self.assertNotIn("{{", source)
        for tag in ("{% url", "{% extends", "{% include", "{% static", "{% csrf_token"):
            with self.subTest(tag=tag):
                self.assertNotIn(tag, source)
        self.assertNotIn("cdn.jsdelivr.net", source)

    def test_default_server_error_handler_uses_custom_500_without_database(self):
        request = RequestFactory().get("/contracts/")
        with self.assertNumQueries(0):
            response = server_error(request)
        self.assertEqual(response.status_code, 500)
        self.assertIn("Something went wrong", response.content.decode())

    def test_unhandled_view_exception_returns_custom_500_without_leaking_it(self):
        self.client.force_login(self.encoder_a)
        self.client.raise_request_exception = False
        with patch(
            "contracts.views.ContractListView.get_context_data",
            side_effect=RuntimeError("pd3-secret-internal-state"),
        ), self.assertLogs("django.request", level="ERROR"):
            response = self.client.get(reverse("contract_list"))
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Something went wrong", status_code=500)
        self.assertNotContains(response, "pd3-secret-internal-state", status_code=500)
        self.assertNotContains(response, "RuntimeError", status_code=500)
        for marker in DEBUG_PAGE_MARKERS:
            self.assertNotContains(response, marker, status_code=500)


# ===========================================================================
# 2. Server-side validation and business rules
# ===========================================================================


class PD3ServerSideValidationTests(PD3FixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.encoder_a)
        self.edit_url = reverse("contract_edit", kwargs={"pk": self.contract_a.pk})
        self.add_rate_url = reverse("rate_create", kwargs={"pk": self.contract_a.pk})
        self.edit_rate_url = reverse(
            "rate_edit", kwargs={"pk": self.contract_a.pk, "rate_id": self.rate_a.pk}
        )

    # -- BR-10: contract validity window -----------------------------------

    def test_br10_expiration_before_effective_is_rejected_by_the_web_form(self):
        response = self.client.post(
            self.edit_url,
            self.contract_post(
                self.contract_a, effective_date="2026-06-30", expiration_date="2026-06-01"
            ),
        )
        self.assertEqual(response.status_code, 200)
        errors = response.context["form"].errors
        self.assertEqual(
            errors["expiration_date"],
            ["Expiration date must be on or after the effective date (BR-10)."],
        )
        self.contract_a.refresh_from_db()
        self.assertEqual(self.contract_a.expiration_date, date(2026, 12, 31))

    def test_br10_is_enforced_by_model_clean_and_database_check(self):
        self.contract_a.expiration_date = date(2025, 12, 31)
        with self.assertRaises(ValidationError) as ctx:
            self.contract_a.full_clean()
        self.assertIn("expiration_date", ctx.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ContractMetadata.objects.filter(pk=self.contract_a.pk).update(
                expiration_date=date(2025, 12, 31)
            )

    def test_br10_same_day_validity_is_accepted(self):
        response = self.client.post(
            self.edit_url,
            self.contract_post(
                self.contract_a, effective_date="2026-03-01", expiration_date="2026-03-01"
            ),
        )
        self.assertEqual(response.status_code, 302)

    # -- BR-13: distinct origin/destination ports --------------------------

    def test_br13_identical_ports_rejected_on_create_and_edit_case_insensitively(self):
        for url in (self.add_rate_url, self.edit_rate_url):
            with self.subTest(url=url):
                response = self.client.post(
                    url,
                    self.rate_post(origin_port_code="cnsha", destination_port_code=" CNSHA "),
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.context["form"].errors["destination_port_code"],
                    ["Destination port code must differ from origin port code (BR-13)."],
                )
        self.assertEqual(self.contract_a.freight_rates.count(), 1)
        self.rate_a.refresh_from_db()
        self.assertEqual(self.rate_a.destination_port_code, "USLAX")

    def test_br13_is_enforced_by_database_check(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            FreightRate.objects.filter(pk=self.rate_a.pk).update(destination_port_code="CNSHA")

    # -- BR-12: rate amounts; arbitrary charge amounts ---------------------

    def test_br12_negative_zero_and_non_numeric_rate_amounts_are_rejected(self):
        for amount in ("-5", "-0.01", "0", "0.00", "abc", "NaN", "1e999", "99999999999.99"):
            with self.subTest(rate_amount=amount):
                response = self.client.post(self.add_rate_url, self.rate_post(rate_amount=amount))
                self.assertEqual(response.status_code, 200)
                self.assertIn("rate_amount", response.context["form"].errors)
        self.assertEqual(self.contract_a.freight_rates.count(), 1)

    def test_br12_negative_amount_rejected_when_editing_an_existing_rate(self):
        response = self.client.post(self.edit_rate_url, self.rate_post(rate_amount="-1500.00"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("rate_amount", response.context["form"].errors)
        self.rate_a.refresh_from_db()
        self.assertEqual(self.rate_a.rate_amount, Decimal("1500.00"))

    def test_rate_amount_is_enforced_by_model_validator_and_database_check(self):
        self.rate_a.rate_amount = Decimal("-1.00")
        with self.assertRaises(ValidationError) as ctx:
            self.rate_a.full_clean()
        self.assertIn("rate_amount", ctx.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FreightRate.objects.filter(pk=self.rate_a.pk).update(rate_amount=Decimal("-1.00"))

    def test_negative_arbitrary_charge_amount_rejected_by_validator_and_database(self):
        charge = self.contract_a.arbitrary_charges.get()
        charge.charge_amount = Decimal("-0.01")
        with self.assertRaises(ValidationError) as ctx:
            charge.full_clean()
        self.assertEqual(ctx.exception.message_dict["charge_amount"], ["Charge amount cannot be negative."])

        with self.assertRaises(IntegrityError), transaction.atomic():
            ArbitraryCharge.objects.filter(pk=charge.pk).update(charge_amount=Decimal("-0.01"))

        # Zero is a legitimate (waived) arbitrary charge.
        charge.charge_amount = Decimal("0.00")
        charge.full_clean()

    # -- Page spans ---------------------------------------------------------

    def test_page_span_end_before_start_is_rejected(self):
        self.rate_a.source_page_start = 3
        self.rate_a.source_page_end = 2
        with self.assertRaises(ValidationError) as ctx:
            self.rate_a.full_clean()
        self.assertEqual(
            ctx.exception.message_dict["source_page_end"],
            ["Source end page must be on or after the source start page."],
        )

    def test_page_numbers_must_start_at_one_and_valid_spans_pass(self):
        self.rate_a.source_page_start = 0
        self.rate_a.source_page_end = 0
        with self.assertRaises(ValidationError) as ctx:
            self.rate_a.full_clean()
        self.assertIn("source_page_start", ctx.exception.message_dict)
        self.assertIn("source_page_end", ctx.exception.message_dict)

        self.rate_a.source_page_start = 2
        self.rate_a.source_page_end = 3
        self.rate_a.full_clean()

    # -- Profile photo uploads ---------------------------------------------

    def test_oversized_profile_photo_over_5mb_is_rejected(self):
        photo = SimpleUploadedFile("huge.bmp", _oversized_bmp_bytes(), content_type="image/bmp")
        response = self.client.post(
            reverse("profile_edit"),
            {**self.profile_post(self.encoder_a), "profile_photo": photo},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].errors["profile_photo"],
            ["Profile photo must be 5 MB or smaller."],
        )
        self.encoder_a.refresh_from_db()
        self.assertFalse(self.encoder_a.profile_photo)

    def test_non_image_profile_photo_is_rejected(self):
        fake = SimpleUploadedFile(
            "avatar.png", b"<?php echo 'not an image'; ?>", content_type="image/png"
        )
        response = self.client.post(
            reverse("profile_edit"),
            {**self.profile_post(self.encoder_a), "profile_photo": fake},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("profile_photo", response.context["form"].errors)
        self.encoder_a.refresh_from_db()
        self.assertFalse(self.encoder_a.profile_photo)

    def test_small_valid_profile_photo_is_accepted(self):
        photo = SimpleUploadedFile("avatar.png", _png_bytes(), content_type="image/png")
        response = self.client.post(
            reverse("profile_edit"),
            {**self.profile_post(self.encoder_a), "profile_photo": photo},
        )
        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        self.encoder_a.refresh_from_db()
        self.assertTrue(self.encoder_a.profile_photo.name.startswith("profile_photos/"))


class PD3MessagesAndPRGTests(PD3FixtureMixin, TestCase):
    """Every form submission returns flash feedback; successful POSTs redirect (PRG)."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.encoder_a)
        self.detail_url = reverse("contract_detail", kwargs={"pk": self.contract_a.pk})

    def _assert_prg_success(self, response, expected_url, text):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"].split("#")[0], expected_url)
        flashes = _flash(response)
        self.assertTrue(
            any(level == SUCCESS and text in msg for level, msg in flashes), flashes
        )

    def _assert_invalid_rerender(self, response, text):
        self.assertEqual(response.status_code, 200)
        flashes = _flash(response)
        self.assertTrue(any(level == ERROR and text in msg for level, msg in flashes), flashes)

    def test_contract_edit_prg_and_messages(self):
        url = reverse("contract_edit", kwargs={"pk": self.contract_a.pk})
        ok = self.client.post(url, self.contract_post(self.contract_a, trade_scope="TRANSPACIFIC EB"))
        self._assert_prg_success(ok, self.detail_url, "Updated contract metadata")
        followed = self.client.get(ok["Location"])
        self.assertContains(followed, "Updated contract metadata")

        bad = self.client.post(url, self.contract_post(self.contract_a, expiration_date="2025-01-01"))
        self._assert_invalid_rerender(bad, "Contract metadata could not be updated")

    def test_rate_create_edit_delete_prg_and_messages(self):
        add_url = reverse("rate_create", kwargs={"pk": self.contract_a.pk})
        ok = self.client.post(add_url, self.rate_post())
        self._assert_prg_success(ok, self.detail_url, "Added rate row #2")
        new_rate = self.contract_a.freight_rates.get(line_item_sequence=2)
        self.assertEqual((new_rate.origin_port_code, new_rate.currency_code), ("CNNGB", "USD"))

        bad = self.client.post(add_url, self.rate_post(rate_amount="-10"))
        self._assert_invalid_rerender(bad, "Freight rate could not be saved")

        edit_url = reverse("rate_edit", kwargs={"pk": self.contract_a.pk, "rate_id": new_rate.pk})
        ok = self.client.post(edit_url, self.rate_post(rate_amount="1999.99"))
        self._assert_prg_success(ok, self.detail_url, "Updated rate row #2")
        bad = self.client.post(edit_url, self.rate_post(destination_port_code="CNNGB"))
        self._assert_invalid_rerender(bad, "Freight rate changes could not be saved")

        delete_url = reverse("rate_delete", kwargs={"pk": self.contract_a.pk, "rate_id": new_rate.pk})
        ok = self.client.post(delete_url)
        self._assert_prg_success(ok, self.detail_url, "Deleted freight rate row #2")
        self.assertFalse(FreightRate.objects.filter(pk=new_rate.pk).exists())

    def test_archive_and_document_delete_prg_and_messages(self):
        archive_url = reverse("contract_archive", kwargs={"pk": self.contract_a.pk})
        ok = self.client.post(archive_url)
        self._assert_prg_success(ok, self.detail_url, "has been archived (BR-09)")
        again = self.client.post(archive_url)
        self.assertEqual(again.status_code, 302)
        self.assertIn((INFO, f"Contract '{self.contract_a.contract_number}' is already archived."), _flash(again))

        delete_failed = self.client.post(
            reverse("document_delete", kwargs={"doc_id": self.failed_doc_a.pk})
        )
        self._assert_prg_success(delete_failed, reverse("contract_list"), "Deleted unextracted document")

        protected = self.client.post(
            reverse("document_delete", kwargs={"doc_id": self.contract_a.document_id})
        )
        self.assertEqual(protected.status_code, 302)
        self.assertTrue(any(level == ERROR and "BR-09" in msg for level, msg in _flash(protected)))
        self.assertTrue(DocumentFile.objects.filter(pk=self.contract_a.document_id).exists())

    def test_export_write_failure_redirects_with_error_message(self):
        with patch(
            "contracts.views.export_contract_artifact", side_effect=OSError("disk full")
        ), self.assertLogs("contracts.views", level="ERROR"):
            response = self.client.get(
                reverse("contract_export", kwargs={"pk": self.contract_a.pk, "fmt": "csv"})
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], self.detail_url)
        flashes = _flash(response)
        self.assertTrue(any(level == ERROR and "could not be written" in msg for level, msg in flashes))
        self.assertFalse(any("disk full" in msg for _, msg in flashes))

    def test_profile_and_password_prg_and_messages(self):
        ok = self.client.post(reverse("profile_edit"), self.profile_post(self.encoder_a, department="Docs"))
        self._assert_prg_success(ok, reverse("profile"), "profile has been updated")
        bad = self.client.post(reverse("profile_edit"), self.profile_post(self.encoder_a, email="pd3_b@shake.local"))
        self._assert_invalid_rerender(bad, "Profile update could not be saved")

        bad = self.client.post(
            reverse("password_change"),
            {"old_password": "wrong", "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        )
        self._assert_invalid_rerender(bad, "Password could not be changed")
        ok = self.client.post(
            reverse("password_change"),
            {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        )
        self._assert_prg_success(ok, reverse("profile"), "password has been changed")

    def test_api_token_create_and_revoke_prg_and_messages(self):
        ok = self.client.post(reverse("api_token_create"), {"name": "PRG token"})
        self._assert_prg_success(ok, reverse("profile"), "Local API token 'PRG token' generated")
        bad = self.client.post(reverse("api_token_create"), {"name": "x" * 101})
        self.assertEqual(bad.status_code, 302)
        self.assertTrue(any(level == ERROR for level, _ in _flash(bad)))

        ok = self.client.post(reverse("api_token_revoke", kwargs={"pk": self.token_a.pk}))
        self._assert_prg_success(ok, reverse("profile"), "revoked")


# ===========================================================================
# 3. Security, role enforcement and IDOR isolation
# ===========================================================================


class PD3AuthenticationGuardTests(PD3FixtureMixin, TestCase):
    def test_anonymous_get_requests_redirect_to_login_on_every_core_view(self):
        pk = self.contract_a.pk
        urls = [
            reverse("dashboard"),
            reverse("dashboard_root"),
            reverse("encoder_dashboard"),
            reverse("admin_dashboard"),
            reverse("contract_list"),
            reverse("contract_upload"),
            reverse("contract_detail", kwargs={"pk": pk}),
            reverse("contract_edit", kwargs={"pk": pk}),
            reverse("rate_create", kwargs={"pk": pk}),
            reverse("rate_edit", kwargs={"pk": pk, "rate_id": self.rate_a.pk}),
            reverse("contract_export", kwargs={"pk": pk, "fmt": "json"}),
            reverse("contract_export", kwargs={"pk": pk, "fmt": "xlsx"}),
            reverse("contract_export", kwargs={"pk": pk, "fmt": "csv"}),
            reverse("carrier_list"),
            reverse("profile"),
            reverse("profile_edit"),
            reverse("password_change"),
        ]
        login_url = reverse("login")
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(f"{login_url}?next="))
        self.assertEqual(ExportRecord.objects.count(), 0)

    def test_anonymous_post_requests_redirect_to_login_and_change_nothing(self):
        pk = self.contract_a.pk
        posts = [
            (reverse("contract_edit", kwargs={"pk": pk}), self.contract_post(self.contract_a, trade_scope="HACKED")),
            (reverse("rate_create", kwargs={"pk": pk}), self.rate_post()),
            (reverse("rate_edit", kwargs={"pk": pk, "rate_id": self.rate_a.pk}), self.rate_post()),
            (reverse("rate_delete", kwargs={"pk": pk, "rate_id": self.rate_a.pk}), {}),
            (reverse("contract_archive", kwargs={"pk": pk}), {}),
            (reverse("document_delete", kwargs={"doc_id": self.failed_doc_a.pk}), {}),
            (reverse("profile_edit"), self.profile_post(self.encoder_a)),
            (reverse("password_change"), {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}),
            (reverse("api_token_create"), {}),
            (reverse("api_token_revoke", kwargs={"pk": self.token_a.pk}), {}),
        ]
        for url, data in posts:
            with self.subTest(url=url):
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith(reverse("login")))

        self.contract_a.refresh_from_db()
        self.rate_a.refresh_from_db()
        self.token_a.refresh_from_db()
        self.assertEqual(self.contract_a.trade_scope, "ASIA - NORTH AMERICA (EB)")
        self.assertEqual(self.rate_a.destination_port_code, "USLAX")
        self.assertEqual(self.contract_a.freight_rates.count(), 1)
        self.assertEqual(self.contract_a.document.status, DocumentFile.Status.EXTRACTED)
        self.assertTrue(DocumentFile.objects.filter(pk=self.failed_doc_a.pk).exists())
        self.assertTrue(self.token_a.is_active)
        self.assertEqual(APIToken.objects.count(), 2)

    def test_anonymous_api_requests_get_401_json_not_a_login_redirect(self):
        response = self.client.get(reverse("api_contract_detail", kwargs={"pk": self.contract_a.pk}))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response["WWW-Authenticate"].split()[0], "Bearer")
        self.assertIn("detail", response.json())


class PD3IDORIsolationTests(PD3FixtureMixin, TestCase):
    """ENCODER B probes every record that belongs to ENCODER A."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.encoder_b)
        self.pk_a = self.contract_a.pk

    def test_encoder_cannot_view_another_encoders_contract_rate_or_exports(self):
        urls = [
            reverse("contract_detail", kwargs={"pk": self.pk_a}),
            reverse("contract_edit", kwargs={"pk": self.pk_a}),
            reverse("rate_create", kwargs={"pk": self.pk_a}),
            reverse("rate_edit", kwargs={"pk": self.pk_a, "rate_id": self.rate_a.pk}),
            reverse("contract_export", kwargs={"pk": self.pk_a, "fmt": "json"}),
            reverse("contract_export", kwargs={"pk": self.pk_a, "fmt": "xlsx"}),
            reverse("contract_export", kwargs={"pk": self.pk_a, "fmt": "csv"}),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(ExportRecord.objects.count(), 0)

    def test_encoder_cannot_edit_archive_or_delete_another_encoders_records(self):
        posts = [
            (reverse("contract_edit", kwargs={"pk": self.pk_a}), self.contract_post(self.contract_a, trade_scope="HIJACKED")),
            (reverse("rate_create", kwargs={"pk": self.pk_a}), self.rate_post()),
            (reverse("rate_edit", kwargs={"pk": self.pk_a, "rate_id": self.rate_a.pk}), self.rate_post(rate_amount="1.00")),
            (reverse("rate_delete", kwargs={"pk": self.pk_a, "rate_id": self.rate_a.pk}), {}),
            (reverse("contract_archive", kwargs={"pk": self.pk_a}), {}),
            (reverse("document_delete", kwargs={"doc_id": self.failed_doc_a.pk}), {}),
            (reverse("document_delete", kwargs={"doc_id": self.contract_a.document_id}), {}),
        ]
        for url, data in posts:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 404)

        self.contract_a.refresh_from_db()
        self.rate_a.refresh_from_db()
        self.assertEqual(self.contract_a.trade_scope, "ASIA - NORTH AMERICA (EB)")
        self.assertEqual(self.rate_a.rate_amount, Decimal("1500.00"))
        self.assertEqual(self.contract_a.freight_rates.count(), 1)
        self.assertEqual(self.contract_a.document.status, DocumentFile.Status.EXTRACTED)
        self.assertTrue(DocumentFile.objects.filter(pk=self.failed_doc_a.pk).exists())

    def test_child_rate_ids_cannot_cross_parent_contracts(self):
        # A's rate ID addressed through B's own contract is still 404.
        cross_edit = reverse("rate_edit", kwargs={"pk": self.contract_b.pk, "rate_id": self.rate_a.pk})
        cross_delete = reverse("rate_delete", kwargs={"pk": self.contract_b.pk, "rate_id": self.rate_a.pk})
        self.assertEqual(self.client.get(cross_edit).status_code, 404)
        self.assertEqual(self.client.post(cross_edit, self.rate_post()).status_code, 404)
        self.assertEqual(self.client.post(cross_delete).status_code, 404)
        self.assertTrue(FreightRate.objects.filter(pk=self.rate_a.pk).exists())

    def test_encoder_cannot_revoke_another_encoders_api_token(self):
        response = self.client.post(reverse("api_token_revoke", kwargs={"pk": self.token_a.pk}))
        self.assertEqual(response.status_code, 404)
        self.token_a.refresh_from_db()
        self.assertTrue(self.token_a.is_active)

    def test_encoder_profile_never_lists_another_encoders_tokens(self):
        response = self.client.get(reverse("profile"))
        self.assertContains(response, self.token_b.masked_key)
        self.assertNotContains(response, self.token_a.masked_key)
        self.assertNotContains(response, self.token_a.key)

    def test_encoder_list_and_search_show_only_own_contracts(self):
        response = self.client.get(reverse("contract_list"))
        self.assertEqual([c.pk for c in response.context["contracts"]], [self.contract_b.pk])
        response = self.client.get(reverse("contract_list"), {"q": "PD3-A"})
        self.assertEqual(list(response.context["contracts"]), [])

    def test_encoder_api_token_cannot_read_another_encoders_contract(self):
        auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token_b.key}"}
        self.client.logout()
        foreign = self.client.get(reverse("api_contract_detail", kwargs={"pk": self.pk_a}), **auth)
        self.assertEqual(foreign.status_code, 404)
        own = self.client.get(reverse("api_contract_detail", kwargs={"pk": self.contract_b.pk}), **auth)
        self.assertEqual(own.status_code, 200)

    def test_encoder_cannot_reach_admin_only_routes(self):
        for url in (
            reverse("admin_dashboard"),
            reverse("carrier_list"),
            reverse("carrier_create"),
            reverse("carrier_edit", kwargs={"pk": self.carrier.pk}),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, reverse("encoder_dashboard"), fetch_redirect_response=False)
        toggle = self.client.post(reverse("carrier_toggle", kwargs={"pk": self.carrier.pk}))
        self.assertRedirects(toggle, reverse("encoder_dashboard"), fetch_redirect_response=False)
        self.carrier.refresh_from_db()
        self.assertTrue(self.carrier.is_active)

    def test_admin_can_view_edit_archive_and_export_any_encoders_contract(self):
        self.client.force_login(self.admin_user)
        listing = self.client.get(reverse("contract_list"))
        self.assertEqual(
            {c.pk for c in listing.context["contracts"]}, {self.contract_a.pk, self.contract_b.pk}
        )
        for contract in (self.contract_a, self.contract_b):
            with self.subTest(contract=contract.contract_number):
                self.assertEqual(
                    self.client.get(reverse("contract_detail", kwargs={"pk": contract.pk})).status_code, 200
                )
                export = self.client.get(
                    reverse("contract_export", kwargs={"pk": contract.pk, "fmt": "csv"})
                )
                self.assertEqual(export.status_code, 200)
                self.assertIn("attachment;", export["Content-Disposition"])

        self.assertEqual(ExportRecord.objects.filter(user=self.admin_user).count(), 2)
        edit = self.client.post(
            reverse("contract_edit", kwargs={"pk": self.contract_b.pk}),
            self.contract_post(self.contract_b, commodity_desc="Reefer cargo"),
        )
        self.assertEqual(edit.status_code, 302)
        archive = self.client.post(reverse("contract_archive", kwargs={"pk": self.contract_b.pk}))
        self.assertEqual(archive.status_code, 302)
        self.contract_b.refresh_from_db()
        self.assertEqual(self.contract_b.commodity_desc, "Reefer cargo")
        self.assertEqual(self.contract_b.document.status, DocumentFile.Status.ARCHIVED)

    def test_admin_api_reads_any_contract_but_tokens_stay_self_only(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("api_contract_detail", kwargs={"pk": self.pk_a}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["metadata"]["contract_number"], "PD3-A-001")

        revoke = self.client.post(reverse("api_token_revoke", kwargs={"pk": self.token_a.pk}))
        self.assertEqual(revoke.status_code, 404)
        self.token_a.refresh_from_db()
        self.assertTrue(self.token_a.is_active)


class PD3RequestSafetyTests(PD3FixtureMixin, TestCase):
    def test_get_on_state_changing_endpoints_returns_405_without_side_effects(self):
        self.client.force_login(self.encoder_a)
        pk = self.contract_a.pk
        urls = [
            reverse("rate_delete", kwargs={"pk": pk, "rate_id": self.rate_a.pk}),
            reverse("contract_archive", kwargs={"pk": pk}),
            reverse("document_delete", kwargs={"doc_id": self.failed_doc_a.pk}),
            reverse("api_token_create"),
            reverse("api_token_revoke", kwargs={"pk": self.token_a.pk}),
            reverse("logout"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

        self.client.force_login(self.admin_user)
        toggle = reverse("carrier_toggle", kwargs={"pk": self.carrier.pk})
        self.assertEqual(self.client.get(toggle).status_code, 405)

        self.assertTrue(FreightRate.objects.filter(pk=self.rate_a.pk).exists())
        self.assertTrue(DocumentFile.objects.filter(pk=self.failed_doc_a.pk).exists())
        self.contract_a.document.refresh_from_db()
        self.assertEqual(self.contract_a.document.status, DocumentFile.Status.EXTRACTED)
        self.token_a.refresh_from_db()
        self.assertTrue(self.token_a.is_active)
        self.assertEqual(APIToken.objects.count(), 2)
        self.carrier.refresh_from_db()
        self.assertTrue(self.carrier.is_active)

    def test_export_endpoint_rejects_post_and_api_rejects_unsupported_methods(self):
        self.client.force_login(self.encoder_a)
        export_url = reverse("contract_export", kwargs={"pk": self.contract_a.pk, "fmt": "json"})
        self.assertEqual(self.client.post(export_url).status_code, 405)

        api_url = reverse("api_contract_detail", kwargs={"pk": self.contract_a.pk})
        auth = {"HTTP_AUTHORIZATION": f"Bearer {self.token_a.key}"}
        response = self.client.delete(api_url, **auth)
        self.assertEqual(response.status_code, 405)
        self.assertIn("GET", response["Allow"])
        self.assertIn("detail", response.json())

    def test_post_without_csrf_token_returns_403_and_changes_nothing(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.encoder_a)
        pk = self.contract_a.pk
        posts = [
            (reverse("contract_edit", kwargs={"pk": pk}), self.contract_post(self.contract_a, trade_scope="CSRF")),
            (reverse("rate_create", kwargs={"pk": pk}), self.rate_post()),
            (reverse("rate_edit", kwargs={"pk": pk, "rate_id": self.rate_a.pk}), self.rate_post()),
            (reverse("rate_delete", kwargs={"pk": pk, "rate_id": self.rate_a.pk}), {}),
            (reverse("contract_archive", kwargs={"pk": pk}), {}),
            (reverse("document_delete", kwargs={"doc_id": self.failed_doc_a.pk}), {}),
            (reverse("contract_upload"), {}),
            (reverse("profile_edit"), self.profile_post(self.encoder_a, department="CSRF")),
            (reverse("password_change"), {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}),
            (reverse("api_token_create"), {}),
            (reverse("api_token_revoke", kwargs={"pk": self.token_a.pk}), {}),
            (reverse("logout"), {}),
        ]
        for url, data in posts:
            with self.subTest(url=url):
                self.assertEqual(csrf_client.post(url, data).status_code, 403)

        self.contract_a.refresh_from_db()
        self.encoder_a.refresh_from_db()
        self.token_a.refresh_from_db()
        self.assertEqual(self.contract_a.trade_scope, "ASIA - NORTH AMERICA (EB)")
        self.assertEqual(self.contract_a.freight_rates.count(), 1)
        self.assertEqual(self.contract_a.document.status, DocumentFile.Status.EXTRACTED)
        self.assertTrue(DocumentFile.objects.filter(pk=self.failed_doc_a.pk).exists())
        self.assertNotEqual(self.encoder_a.department, "CSRF")
        self.assertTrue(self.encoder_a.check_password(PASSWORD))
        self.assertTrue(self.token_a.is_active)
        self.assertEqual(APIToken.objects.count(), 2)
        # The session survived the rejected logout.
        self.assertEqual(csrf_client.get(reverse("profile")).status_code, 200)

    def test_post_with_valid_csrf_token_succeeds(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.encoder_a)
        csrf_client.get(reverse("contract_detail", kwargs={"pk": self.contract_a.pk}))
        token = csrf_client.cookies[settings.CSRF_COOKIE_NAME].value
        response = csrf_client.post(
            reverse("contract_archive", kwargs={"pk": self.contract_a.pk}),
            {"csrfmiddlewaretoken": token},
        )
        self.assertEqual(response.status_code, 302)
        self.contract_a.document.refresh_from_db()
        self.assertEqual(self.contract_a.document.status, DocumentFile.Status.ARCHIVED)

    def test_session_authenticated_api_write_requires_csrf(self):
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(self.encoder_a)
        response = csrf_client.post(reverse("api_contract_ingest"), {})
        self.assertEqual(response.status_code, 403)
        self.assertIn("detail", response.json())


# ===========================================================================
# 4. PD1 standard features regression suite
# ===========================================================================


class PD1RegistrationTests(TestCase):
    def _payload(self, **overrides):
        data = {
            "username": "pd1_new_encoder",
            "email": "  New.Encoder@Shake.Local ",
            "first_name": "New",
            "last_name": "Encoder",
            "department": "Pricing",
            "contact_number": "+63 917 123 4567",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        data.update(overrides)
        return data

    def test_registration_form_has_no_role_selector(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("role", response.context["form"].fields)
        self.assertNotContains(response, 'name="role"')

    def test_registration_creates_encoder_even_when_admin_role_is_posted(self):
        response = self.client.post(
            reverse("register"),
            self._payload(role="ADMIN", is_staff="on", is_superuser="on"),
        )
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertTrue(any(level == SUCCESS for level, _ in _flash(response)))

        user = CustomUser.objects.get(username="pd1_new_encoder")
        self.assertEqual(user.role, CustomUser.Role.ENCODER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.email, "new.encoder@shake.local")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.check_password(PASSWORD))

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        CustomUser.objects.create_user(username="existing", email="taken@shake.local", password=PASSWORD)
        response = self.client.post(reverse("register"), self._payload(email="TAKEN@shake.LOCAL"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertTrue(any(level == ERROR for level, _ in _flash(response)))
        self.assertFalse(CustomUser.objects.filter(username="pd1_new_encoder").exists())

    def test_registration_rejects_mismatched_or_weak_passwords(self):
        for overrides in ({"password2": "Different!Pass2026"}, {"password1": "123", "password2": "123"}):
            with self.subTest(overrides=list(overrides)):
                response = self.client.post(reverse("register"), self._payload(**overrides))
                self.assertEqual(response.status_code, 200)
                self.assertIn("password2", response.context["form"].errors)
        self.assertFalse(CustomUser.objects.filter(username="pd1_new_encoder").exists())


class PD1LoginLogoutTests(PD3FixtureMixin, TestCase):
    def test_email_login_is_case_insensitive_and_routes_by_role(self):
        cases = [
            ("PD3_A@SHAKE.LOCAL", reverse("encoder_dashboard")),
            ("  Pd3_Admin@Shake.Local ", reverse("admin_dashboard")),
        ]
        for email, dashboard in cases:
            with self.subTest(email=email):
                response = self.client.post(reverse("login"), {"email": email, "password": PASSWORD})
                self.assertRedirects(response, dashboard, fetch_redirect_response=False)
                self.assertTrue(any("Welcome back" in msg for _, msg in _flash(response)))
                self.assertEqual(self.client.get(dashboard).status_code, 200)
                self.client.post(reverse("logout"))

    def test_login_rejects_username_wrong_password_and_inactive_accounts(self):
        attempts = [
            {"email": "pd3_encoder_a", "password": PASSWORD},
            {"email": "pd3_a@shake.local", "password": "wrong-password"},
        ]
        for data in attempts:
            with self.subTest(data=data["email"]):
                response = self.client.post(reverse("login"), data)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["form"].is_valid())
                self.assertNotIn("_auth_user_id", self.client.session)

        self.encoder_b.is_active = False
        self.encoder_b.save()
        response = self.client.post(reverse("login"), {"email": "pd3_b@shake.local", "password": PASSWORD})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_authenticated_user_visiting_login_is_sent_to_dashboard(self):
        self.client.force_login(self.encoder_a)
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 302)

    def test_logout_is_post_only_and_clears_the_session(self):
        self.client.force_login(self.encoder_a)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(any("logged out" in msg for _, msg in _flash(response)))
        after = self.client.get(reverse("contract_list"))
        self.assertTrue(after["Location"].startswith(reverse("login")))


class PD1RoleDashboardTests(PD3FixtureMixin, TestCase):
    def test_root_redirects_each_role_to_its_own_dashboard(self):
        for user, dashboard in (
            (self.encoder_a, reverse("encoder_dashboard")),
            (self.admin_user, reverse("admin_dashboard")),
        ):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                for root in (reverse("dashboard"), reverse("dashboard_root")):
                    self.assertRedirects(
                        self.client.get(root), dashboard, fetch_redirect_response=False
                    )

    def test_encoder_dashboard_metrics_count_only_own_records(self):
        ExportRecord.objects.create(
            user=self.encoder_b,
            contract=self.contract_b,
            export_format=ExportRecord.ExportFormat.JSON,
            file_path="contracts/exports/b.json",
        )
        self.client.force_login(self.encoder_a)
        response = self.client.get(reverse("encoder_dashboard"))
        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx["user_batches_count"], 1)
        self.assertEqual(ctx["extracted_contracts_count"], 1)
        self.assertEqual(ctx["total_rate_rows_count"], 1)
        self.assertEqual(ctx["total_arb_rows_count"], 1)
        self.assertEqual(ctx["exports_generated_count"], 0)
        doc_ids = {doc.pk for doc in ctx["recent_documents"]}
        self.assertEqual(doc_ids, {self.contract_a.document_id, self.failed_doc_a.pk})
        self.assertNotContains(response, "PD3-B-001")

    def test_admin_dashboard_metrics_cover_the_whole_system(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual(ctx["total_users_count"], 3)
        self.assertEqual(ctx["admin_users_count"], 1)
        self.assertEqual(ctx["encoder_users_count"], 2)
        self.assertEqual(ctx["total_batches_count"], 2)
        self.assertEqual(ctx["extracted_contracts_count"], 2)
        self.assertEqual(ctx["total_rate_rows_count"], 2)
        self.assertEqual(ctx["total_arb_rows_count"], 2)
        self.assertEqual(ctx["total_exports_count"], 0)
        self.assertEqual(
            ctx["active_carriers_count"], CarrierProfile.objects.filter(is_active=True).count()
        )

    def test_each_role_is_redirected_away_from_the_other_dashboard(self):
        self.client.force_login(self.encoder_a)
        denied = self.client.get(reverse("admin_dashboard"))
        self.assertRedirects(denied, reverse("encoder_dashboard"), fetch_redirect_response=False)
        self.assertTrue(any(level == ERROR and "Unauthorized" in msg for level, msg in _flash(denied)))

        self.client.force_login(self.admin_user)
        denied = self.client.get(reverse("encoder_dashboard"))
        self.assertRedirects(denied, reverse("admin_dashboard"), fetch_redirect_response=False)


class PD1ProfileAndTokenTests(PD3FixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.encoder_a)

    def test_profile_shows_only_the_signed_in_user(self):
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["profile_user"], self.encoder_a)
        self.assertContains(response, "pd3_a@shake.local")
        self.assertNotContains(response, "pd3_b@shake.local")

    def test_profile_update_saves_details_but_never_privileged_fields(self):
        response = self.client.post(
            reverse("profile_edit"),
            self.profile_post(
                self.encoder_a,
                email="PD3.A.Renamed@Shake.Local",
                department="Documentation",
                role="ADMIN",
                is_staff="on",
                is_superuser="on",
            ),
        )
        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        self.encoder_a.refresh_from_db()
        self.assertEqual(self.encoder_a.email, "pd3.a.renamed@shake.local")
        self.assertEqual(self.encoder_a.department, "Documentation")
        self.assertEqual(self.encoder_a.role, CustomUser.Role.ENCODER)
        self.assertFalse(self.encoder_a.is_staff)
        self.assertFalse(self.encoder_a.is_superuser)

    def test_password_change_keeps_session_and_new_password_logs_in(self):
        response = self.client.post(
            reverse("password_change"),
            {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
        )
        self.assertRedirects(response, reverse("profile"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("profile")).status_code, 200)

        self.client.post(reverse("logout"))
        old = self.client.post(reverse("login"), {"email": "pd3_a@shake.local", "password": PASSWORD})
        self.assertEqual(old.status_code, 200)
        new = self.client.post(reverse("login"), {"email": "pd3_a@shake.local", "password": NEW_PASSWORD})
        self.assertRedirects(new, reverse("encoder_dashboard"), fetch_redirect_response=False)

    def test_password_change_rejects_wrong_current_or_mismatched_new_password(self):
        for data in (
            {"old_password": "wrong", "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
            {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": "Mismatch!2027x"},
        ):
            with self.subTest(old=data["old_password"]):
                response = self.client.post(reverse("password_change"), data)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["form"].is_valid())
        self.encoder_a.refresh_from_db()
        self.assertTrue(self.encoder_a.check_password(PASSWORD))

    def test_api_token_lifecycle_generate_show_once_use_and_revoke(self):
        response = self.client.post(reverse("api_token_create"), {"name": "  Nightly sync  "})
        self.assertEqual(response.status_code, 302)
        token = APIToken.objects.filter(user=self.encoder_a).order_by("-pk").first()
        self.assertEqual(token.name, "Nightly sync")
        self.assertRegex(token.key, r"^[0-9a-f]{64}$")

        first_view = self.client.get(reverse("profile"))
        self.assertContains(first_view, token.key)
        second_view = self.client.get(reverse("profile"))
        self.assertNotContains(second_view, token.key)
        self.assertContains(second_view, token.masked_key)

        api_url = reverse("api_contract_detail", kwargs={"pk": self.contract_a.pk})
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token.key}"}
        self.client.logout()
        self.assertEqual(self.client.get(api_url, **auth).status_code, 200)
        token.refresh_from_db()
        self.assertIsNotNone(token.last_used_at)

        self.client.force_login(self.encoder_a)
        revoke = self.client.post(reverse("api_token_revoke", kwargs={"pk": token.pk}))
        self.assertEqual(revoke.status_code, 302)
        token.refresh_from_db()
        self.assertFalse(token.is_active)

        self.client.logout()
        self.assertEqual(self.client.get(api_url, **auth).status_code, 401)
