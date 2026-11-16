from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView


class DashboardView(LoginRequiredMixin, TemplateView):
    """
    Protected main workspace entry point for SHAKE.
    Unauthenticated visitors are redirected to LOGIN_URL (/accounts/login/).
    Expanded with role-specific routing (/dashboard/admin/ & /dashboard/encoder/) in Stage 3.
    """

    template_name = "dashboard/home.html"
