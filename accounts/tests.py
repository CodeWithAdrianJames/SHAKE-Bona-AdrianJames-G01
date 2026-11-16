import io
import shutil
import tempfile

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import BootstrapFormMixin
from .models import CustomUser



class CustomUserModelTests(TestCase):
    def test_default_role_is_encoder(self):
        user = CustomUser.objects.create_user(
            username="encoder1",
            email="encoder1@shake.local",
            password="Str0ngPassword!123",
            first_name="Adrian",
            last_name="Bona",
            department="Pricing",
            contact_number="+63 917 000 0000",
        )
        self.assertEqual(user.role, CustomUser.Role.ENCODER)
        self.assertTrue(user.is_encoder_role)
        self.assertFalse(user.is_admin_role)
        self.assertEqual(user.initials, "AB")
        self.assertTrue(user.check_password("Str0ngPassword!123"))

    def test_superuser_defaults_to_admin_role(self):
        admin_user = CustomUser.objects.create_superuser(
            username="opsadmin",
            email="admin@shake.local",
            password="Str0ngPassword!123",
        )
        self.assertEqual(admin_user.role, CustomUser.Role.ADMIN)
        self.assertTrue(admin_user.is_admin_role)


class RegistrationAndAuthTests(TestCase):
    def test_registration_creates_hashed_user_and_redirects_to_login(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "analyst_aj",
                "email": "AJ@ShakeLogistics.com",
                "first_name": "Adrian",
                "last_name": "Bona",
                "role": CustomUser.Role.ENCODER,
                "department": "Pricing & Tariff Management",
                "contact_number": "+63 917 123 4567",
                "password1": "Str0ngPass!234",
                "password2": "Str0ngPass!234",
            },
            follow=True,
        )
        self.assertRedirects(response, reverse("login"))
        self.assertContains(response, "Account created successfully!")
        user = CustomUser.objects.get(username="analyst_aj")
        self.assertEqual(user.email, "aj@shakelogistics.com")
        self.assertEqual(user.role, CustomUser.Role.ENCODER)
        self.assertNotEqual(user.password, "Str0ngPass!234")
        self.assertTrue(user.check_password("Str0ngPass!234"))

    def test_registration_rejects_duplicate_email_case_insensitively(self):
        CustomUser.objects.create_user(
            username="existing",
            email="dup@shake.local",
            password="Str0ngPass!234",
        )
        response = self.client.post(
            reverse("register"),
            {
                "username": "newuser",
                "email": "DUP@SHAKE.LOCAL",
                "first_name": "New",
                "last_name": "User",
                "password1": "Str0ngPass!234",
                "password2": "Str0ngPass!234",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already in use")
        self.assertFalse(CustomUser.objects.filter(username="newuser").exists())

    def test_registration_rejects_mismatched_passwords(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "mismatch_user",
                "email": "mismatch@shake.local",
                "first_name": "Mis",
                "last_name": "Match",
                "password1": "Str0ngPass!234",
                "password2": "DifferentPass!999",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CustomUser.objects.filter(username="mismatch_user").exists())

    def test_invalid_login_displays_error(self):
        response = self.client.post(
            reverse("login"),
            {"username": "nonexistent", "password": "wrongpassword"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password")

    def test_protected_dashboard_redirects_anonymous_user_to_login(self):
        dashboard_url = reverse("dashboard")
        response = self.client.get(dashboard_url)
        self.assertRedirects(response, f"{reverse('login')}?next={dashboard_url}")

    def test_post_logout_clears_session_and_redirects_to_login(self):
        CustomUser.objects.create_user(
            username="activeuser",
            email="active@shake.local",
            password="Str0ngPass!234",
        )
        self.client.login(username="activeuser", password="Str0ngPass!234")
        response = self.client.post(reverse("logout"), follow=True)
        self.assertRedirects(response, reverse("login"))
        self.assertContains(response, "logged out")


class BootstrapFormMixinTests(TestCase):
    def test_widget_types_get_matching_bootstrap_classes(self):
        class DemoForm(BootstrapFormMixin, forms.Form):
            text = forms.CharField()
            choice = forms.ChoiceField(choices=[("a", "A")])
            agree = forms.BooleanField()

        form = DemoForm()
        self.assertIn("form-control", form.fields["text"].widget.attrs["class"])
        self.assertIn("form-select", form.fields["choice"].widget.attrs["class"])
        self.assertIn("form-check-input", form.fields["agree"].widget.attrs["class"])


class UserProfileTests(TestCase):
    """
    Stage 4 test suite verifying self-only profile detail & update views,
    IDOR prevention, field/email validation, and profile photo uploads.
    """

    def setUp(self):
        self.temp_media_dir = tempfile.mkdtemp()
        self.password = "Str0ngPass!2026"
        self.user = CustomUser.objects.create_user(
            username="analyst_adrian",
            email="adrian@shakelogistics.com",
            password=self.password,
            first_name="Adrian James",
            last_name="Bona",
            role=CustomUser.Role.ENCODER,
            department="Pricing & Tariff Management",
            contact_number="+63 917 111 2222",
        )
        self.other_user = CustomUser.objects.create_user(
            username="ops_colleague",
            email="colleague@shakelogistics.com",
            password=self.password,
            first_name="Elena",
            last_name="Vance",
            role=CustomUser.Role.ADMIN,
            department="IT Operations",
            contact_number="+63 917 999 8888",
        )

    def tearDown(self):
        shutil.rmtree(self.temp_media_dir, ignore_errors=True)

    @staticmethod
    def _generate_test_image_file(filename="avatar.png"):
        buffer = io.BytesIO()
        image = Image.new("RGB", (32, 32), color=(2, 132, 199))
        image.save(buffer, format="PNG")
        buffer.seek(0)
        return SimpleUploadedFile(
            filename,
            buffer.read(),
            content_type="image/png",
        )

    def test_unauthenticated_users_redirected_to_login_from_profile_routes(self):
        for route_name in ("profile", "profile_edit"):
            with self.subTest(route=route_name):
                target_url = reverse(route_name)
                response = self.client.get(target_url)
                self.assertRedirects(
                    response,
                    f"{reverse('login')}?next={target_url}",
                )

    def test_logged_in_user_views_only_own_profile_details(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/profile.html")
        self.assertContains(response, "Adrian James Bona")
        self.assertContains(response, "analyst_adrian")
        self.assertContains(response, "adrian@shakelogistics.com")
        self.assertContains(response, "Freight Analyst / Encoder")
        self.assertContains(response, "Pricing &amp; Tariff Management")
        self.assertContains(response, "+63 917 111 2222")
        self.assertContains(response, reverse("profile_edit"))
        self.assertNotContains(response, "colleague@shakelogistics.com")

    def test_profile_update_fields_and_photo_upload(self):
        self.client.force_login(self.user)
        with override_settings(MEDIA_ROOT=self.temp_media_dir):
            avatar = self._generate_test_image_file("adrian_avatar.png")
            response = self.client.post(
                reverse("profile_edit"),
                {
                    "first_name": "Adrian",
                    "last_name": "Bona Jr.",
                    "email": "Adrian.Updated@ShakeLogistics.com",
                    "department": "Ocean Freight Audit",
                    "contact_number": "+63 918 555 7777",
                    "profile_photo": avatar,
                },
                follow=True,
            )

            self.assertRedirects(response, reverse("profile"))
            self.assertContains(
                response,
                "Your SHAKE profile has been updated successfully.",
            )

            self.user.refresh_from_db()
            self.assertEqual(self.user.first_name, "Adrian")
            self.assertEqual(self.user.last_name, "Bona Jr.")
            self.assertEqual(self.user.email, "adrian.updated@shakelogistics.com")
            self.assertEqual(self.user.department, "Ocean Freight Audit")
            self.assertEqual(self.user.contact_number, "+63 918 555 7777")
            self.assertTrue(bool(self.user.profile_photo))
            self.assertIn("profile_photos/", self.user.profile_photo.name)
            self.assertContains(response, self.user.profile_photo.url)

    def test_profile_update_rejects_duplicate_email_from_another_user(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile_edit"),
            {
                "first_name": "Adrian James",
                "last_name": "Bona",
                "email": "COLLEAGUE@SHAKELOGISTICS.COM",
                "department": "Pricing & Tariff Management",
                "contact_number": "+63 917 111 2222",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/profile_edit.html")
        self.assertContains(
            response,
            "This email address is already in use by another account.",
        )
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "adrian@shakelogistics.com")

    def test_profile_update_allows_keeping_own_current_email(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("profile_edit"),
            {
                "first_name": "Adrian James",
                "last_name": "Bona",
                "email": "ADRIAN@SHAKELOGISTICS.COM",
                "department": "Carrier Relations",
                "contact_number": "+63 917 333 4444",
            },
            follow=True,
        )
        self.assertRedirects(response, reverse("profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "adrian@shakelogistics.com")
        self.assertEqual(self.user.department, "Carrier Relations")
        self.assertEqual(self.user.contact_number, "+63 917 333 4444")

