"""
Local loopback REST API routes (F-11), mounted at /api/v1/ by shake/urls.py.

Canonical paths have no trailing slash so POST never hits an APPEND_SLASH
redirect; the trailing-slash forms are accepted as aliases.
"""

from django.urls import path

from .api_views import ContractDetailAPIView, ContractIngestAPIView

urlpatterns = [
    path("ingest", ContractIngestAPIView.as_view(), name="api_contract_ingest"),
    path("ingest/", ContractIngestAPIView.as_view()),
    path("contracts/<int:pk>", ContractDetailAPIView.as_view(), name="api_contract_detail"),
    path("contracts/<int:pk>/", ContractDetailAPIView.as_view()),
]
