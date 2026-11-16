from django import forms
from django.test import TestCase
from django.urls import reverse

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
