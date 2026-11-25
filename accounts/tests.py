import io
import shutil
import tempfile

from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from PIL import Image

from .forms import BootstrapFormMixin, CustomUserCreationForm
from .models import APIToken, CustomUser


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
            {"email": "nobody@shake.local", "password": "wrongpassword"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password")

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

    def test_registration_form_does_not_expose_role_field(self):
        self.assertNotIn("role", CustomUserCreationForm().fields)
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="role"')

    def test_registration_cannot_self_assign_admin_role(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "sneaky_admin",
                "email": "sneaky@shake.local",
                "first_name": "Sneaky",
                "last_name": "Admin",
                "role": CustomUser.Role.ADMIN,
                "password1": "Str0ngPass!234",
                "password2": "Str0ngPass!234",
            },
        )
        self.assertRedirects(response, reverse("login"))
        user = CustomUser.objects.get(username="sneaky_admin")
        self.assertEqual(user.role, CustomUser.Role.ENCODER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)


class EmailLoginTests(TestCase):
    """BR-01: users sign in with their unique email address (case-insensitive)."""

    def setUp(self):
        self.password = "Str0ngPass!234"
        self.encoder = CustomUser.objects.create_user(
            username="login_encoder",
            email="encoder.login@shake.local",
            password=self.password,
        )
        self.admin_user = CustomUser.objects.create_user(
            username="login_admin",
            email="admin.login@shake.local",
            password=self.password,
            role=CustomUser.Role.ADMIN,
        )

    def test_login_form_uses_email_instead_of_username(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="email"')
        self.assertNotContains(response, 'name="username"')

    def test_encoder_logs_in_with_email_and_lands_on_encoder_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"email": "encoder.login@shake.local", "password": self.password},
        )
        self.assertRedirects(response, reverse("encoder_dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.encoder.pk)

    def test_admin_logs_in_with_email_and_lands_on_admin_dashboard(self):
        response = self.client.post(
            reverse("login"),
            {"email": "admin.login@shake.local", "password": self.password},
        )
        self.assertRedirects(response, reverse("admin_dashboard"))

    def test_email_login_is_case_insensitive(self):
        response = self.client.post(
            reverse("login"),
            {"email": "  Encoder.LOGIN@Shake.Local ", "password": self.password},
        )
        self.assertRedirects(response, reverse("encoder_dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.encoder.pk)

    def test_login_with_username_is_rejected(self):
        response = self.client.post(
            reverse("login"),
            {"username": "login_encoder", "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_with_wrong_password_is_rejected(self):
        response = self.client.post(
            reverse("login"),
            {"email": "encoder.login@shake.local", "password": "WrongPass!999"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid email or password")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_log_in(self):
        self.encoder.is_active = False
        self.encoder.save()
        response = self.client.post(
            reverse("login"),
            {"email": "encoder.login@shake.local", "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)


class UserDatabaseConstraintTests(TestCase):
    """BR-01 / BR-02 are enforced by the database, not only by forms."""

    def test_email_is_normalized_to_lowercase_on_save(self):
        user = CustomUser.objects.create_user(
            username="mixedcase",
            email="  Mixed.Case@SHAKE.Local ",
            password="Str0ngPass!234",
        )
        user.refresh_from_db()
        self.assertEqual(user.email, "mixed.case@shake.local")

    def test_duplicate_email_rejected_by_database(self):
        CustomUser.objects.create_user(
            username="first", email="dup.db@shake.local", password="x"
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomUser.objects.create_user(
                username="second", email="DUP.DB@shake.local", password="x"
            )

    def test_invalid_role_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomUser.objects.create_user(
                username="superrole",
                email="superrole@shake.local",
                password="x",
                role="SUPERADMIN",
            )


class UserConstraintsMigrationTests(TransactionTestCase):
    """0002_user_constraints normalizes legacy rows before adding constraints."""

    migrate_from = [("accounts", "0001_initial")]
    migrate_to = [("accounts", "0002_user_constraints")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_blank_and_duplicate_emails_are_normalized(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        LegacyUser = old_apps.get_model("accounts", "CustomUser")

        keeper = LegacyUser.objects.create(username="keeper", email=" Shared@Shake.Local ")
        duplicate = LegacyUser.objects.create(username="duplicate", email="shared@shake.local")
        blank_a = LegacyUser.objects.create(username="blank_a", email="")
        blank_b = LegacyUser.objects.create(username="blank_b", email="")
        bad_role = LegacyUser.objects.create(
            username="bad_role", email="bad.role@shake.local", role="ROOT"
        )

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.migrate_to)
        new_apps = executor.loader.project_state(self.migrate_to).apps
        User = new_apps.get_model("accounts", "CustomUser")

        self.assertEqual(User.objects.get(pk=keeper.pk).email, "shared@shake.local")
        dup_email = User.objects.get(pk=duplicate.pk).email
        self.assertNotEqual(dup_email, "shared@shake.local")
        self.assertTrue(dup_email.endswith("@users.shake.invalid"))
        blank_emails = {
            User.objects.get(pk=blank_a.pk).email,
            User.objects.get(pk=blank_b.pk).email,
        }
        self.assertEqual(len(blank_emails), 2)
        self.assertNotIn("", blank_emails)
        self.assertEqual(User.objects.get(pk=bad_role.pk).role, "ENCODER")

        emails = list(User.objects.values_list("email", flat=True))
        self.assertEqual(len(emails), len(set(emails)))


class PasswordChangeTests(TestCase):
    """Self-service password change at /accounts/password/."""

    def setUp(self):
        self.old_password = "Str0ngPass!234"
        self.new_password = "N3wStr0ngPass!567"
        self.user = CustomUser.objects.create_user(
            username="pw_user",
            email="pw.user@shake.local",
            password=self.old_password,
        )
        self.url = reverse("password_change")

    def test_password_change_route_and_profile_link(self):
        self.assertEqual(self.url, "/accounts/password/")
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertContains(response, self.url)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_password_change_succeeds_and_keeps_session(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_change.html")

        response = self.client.post(
            self.url,
            {
                "old_password": self.old_password,
                "new_password1": self.new_password,
                "new_password2": self.new_password,
            },
            follow=True,
        )
        self.assertRedirects(response, reverse("profile"))
        self.assertContains(response, "Your SHAKE password has been changed successfully.")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password(self.old_password))
        # Session auth hash was refreshed, so the user remains signed in.
        self.assertEqual(self.client.get(reverse("profile")).status_code, 200)

        # The new password works for email login.
        self.client.logout()
        response = self.client.post(
            reverse("login"),
            {"email": "pw.user@shake.local", "password": self.new_password},
        )
        self.assertRedirects(response, reverse("encoder_dashboard"))

    def test_wrong_current_password_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            {
                "old_password": "NotMyPassword!1",
                "new_password1": self.new_password,
                "new_password2": self.new_password,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("old_password"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))

    def test_mismatched_new_passwords_are_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            {
                "old_password": self.old_password,
                "new_password1": self.new_password,
                "new_password2": "Different!Pass789",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors.get("new_password2"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.old_password))


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



class APITokenModelTests(TestCase):
    """F-11 APIToken model: secure key generation, defaults, and constraints."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="token_owner", email="token.owner@shake.local", password=None
        )

    def test_key_is_64_char_hex_and_defaults_are_applied(self):
        token = APIToken.objects.create(user=self.user)
        self.assertRegex(token.key, r"^[0-9a-f]{64}$")
        self.assertEqual(token.name, "Local CLI Token")
        self.assertTrue(token.is_active)
        self.assertIsNotNone(token.created_at)
        self.assertIsNone(token.last_used_at)
        self.assertEqual(token.masked_key, f"{token.key[:8]}…")
        self.assertNotIn(token.key, str(token))

    def test_each_token_gets_a_distinct_key(self):
        keys = {APIToken.objects.create(user=self.user).key for _ in range(5)}
        self.assertEqual(len(keys), 5)

    def test_duplicate_key_rejected_by_database(self):
        token = APIToken.objects.create(user=self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                APIToken.objects.create(user=self.user, key=token.key)

    def test_tokens_are_deleted_with_their_user(self):
        other = CustomUser.objects.create_user(
            username="short_lived", email="short.lived@shake.local", password=None
        )
        APIToken.objects.create(user=other)
        other.delete()
        self.assertFalse(APIToken.objects.filter(user_id=other.pk).exists())


class APITokenProfileManagementTests(TestCase):
    """F-11 Local API Tokens card on /accounts/profile/: generate and revoke via POST."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username="token_encoder", email="token.encoder@shake.local", password=None
        )
        cls.other_user = CustomUser.objects.create_user(
            username="token_admin",
            email="token.admin@shake.local",
            password=None,
            role=CustomUser.Role.ADMIN,
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.profile_url = reverse("profile")
        self.create_url = reverse("api_token_create")

    def test_profile_shows_local_api_tokens_section(self):
        response = self.client.get(self.profile_url)
        self.assertContains(response, "Local API Tokens")
        self.assertContains(response, f'action="{self.create_url}"')
        self.assertContains(response, "No API tokens yet")

    def test_generate_token_shows_raw_key_exactly_once(self):
        response = self.client.post(self.create_url, {"name": "Nightly ingest script"})
        self.assertRedirects(response, f"{self.profile_url}#api-tokens", fetch_redirect_response=False)

        token = APIToken.objects.get(user=self.user)
        self.assertEqual(token.name, "Nightly ingest script")
        self.assertTrue(token.is_active)

        first_view = self.client.get(self.profile_url)
        self.assertContains(first_view, token.key)
        self.assertContains(first_view, "Copy your new token now")
        self.assertContains(first_view, token.masked_key)

        second_view = self.client.get(self.profile_url)
        self.assertNotContains(second_view, token.key)
        self.assertContains(second_view, token.masked_key)

    def test_blank_label_falls_back_to_default_name(self):
        self.client.post(self.create_url, {"name": "   "})
        self.assertEqual(APIToken.objects.get(user=self.user).name, APIToken.DEFAULT_NAME)

    def test_overlong_label_is_rejected(self):
        response = self.client.post(self.create_url, {"name": "x" * 101}, follow=True)
        self.assertFalse(APIToken.objects.filter(user=self.user).exists())
        self.assertContains(response, "API token could not be generated")

    def test_profile_lists_only_own_tokens(self):
        own = APIToken.objects.create(user=self.user, name="Mine")
        foreign = APIToken.objects.create(user=self.other_user, name="Someone else's")
        response = self.client.get(self.profile_url)
        self.assertContains(response, own.masked_key)
        self.assertNotContains(response, foreign.masked_key)
        self.assertNotContains(response, "Someone else&#x27;s")

    def test_token_endpoints_are_post_only(self):
        token = APIToken.objects.create(user=self.user)
        self.assertEqual(self.client.get(self.create_url).status_code, 405)
        revoke_url = reverse("api_token_revoke", kwargs={"pk": token.pk})
        self.assertEqual(self.client.get(revoke_url).status_code, 405)
        token.refresh_from_db()
        self.assertTrue(token.is_active)

    def test_anonymous_user_cannot_generate_or_revoke(self):
        token = APIToken.objects.create(user=self.user)
        self.client.logout()
        response = self.client.post(self.create_url, {"name": "anon"})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        response = self.client.post(reverse("api_token_revoke", kwargs={"pk": token.pk}))
        self.assertIn(reverse("login"), response["Location"])
        self.assertEqual(APIToken.objects.count(), 1)
        token.refresh_from_db()
        self.assertTrue(token.is_active)

    def test_revoke_own_token(self):
        token = APIToken.objects.create(user=self.user)
        response = self.client.post(
            reverse("api_token_revoke", kwargs={"pk": token.pk}), follow=True
        )
        token.refresh_from_db()
        self.assertFalse(token.is_active)
        self.assertContains(response, "revoked")
        self.assertContains(response, "Revoked")

    def test_cannot_revoke_another_users_token(self):
        foreign = APIToken.objects.create(user=self.other_user)
        response = self.client.post(reverse("api_token_revoke", kwargs={"pk": foreign.pk}))
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertTrue(foreign.is_active)

    def test_revoked_token_no_longer_authenticates_api(self):
        token = APIToken.objects.create(user=self.user)
        api_url = reverse("api_contract_detail", kwargs={"pk": 1})
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token.key}"}
        self.client.logout()
        # Active token authenticates (404: the user owns no contract with that ID).
        self.assertEqual(self.client.get(api_url, **auth).status_code, 404)

        self.client.force_login(self.user)
        self.client.post(reverse("api_token_revoke", kwargs={"pk": token.pk}))
        self.client.logout()
        self.assertEqual(self.client.get(api_url, **auth).status_code, 401)
