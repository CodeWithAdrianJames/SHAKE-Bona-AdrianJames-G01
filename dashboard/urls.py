from django.urls import path

from .views import (
    AdminDashboardView,
    DashboardRedirectView,
    EncoderDashboardView,
)

urlpatterns = [
    path("", DashboardRedirectView.as_view(), name="dashboard"),
    path("dashboard/", DashboardRedirectView.as_view(), name="dashboard_root"),
    path("dashboard/admin/", AdminDashboardView.as_view(), name="admin_dashboard"),
    path("dashboard/encoder/", EncoderDashboardView.as_view(), name="encoder_dashboard"),
]
