from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import CustomUser
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
