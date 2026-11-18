from django.urls import path

from .views import (
    CarrierProfileCreateView,
    CarrierProfileListView,
    CarrierProfileToggleView,
    CarrierProfileUpdateView,
    ContractArchiveView,
    ContractDetailView,
    ContractExportView,
    ContractListView,
    ContractMetadataUpdateView,
    ContractUploadView,
    DocumentFileDeleteView,
    FreightRateCreateView,
    FreightRateDeleteView,
    FreightRateUpdateView,
)

urlpatterns = [
    path("", ContractListView.as_view(), name="contract_list"),
    path("upload/", ContractUploadView.as_view(), name="contract_upload"),
    path("carriers/", CarrierProfileListView.as_view(), name="carrier_list"),
    path("carriers/create/", CarrierProfileCreateView.as_view(), name="carrier_create"),
    path("carriers/<int:pk>/edit/", CarrierProfileUpdateView.as_view(), name="carrier_edit"),
    path("carriers/<int:pk>/toggle/", CarrierProfileToggleView.as_view(), name="carrier_toggle"),
    path("documents/<int:doc_id>/delete/", DocumentFileDeleteView.as_view(), name="document_delete"),
    path("<int:pk>/", ContractDetailView.as_view(), name="contract_detail"),
    path("<int:pk>/edit/", ContractMetadataUpdateView.as_view(), name="contract_edit"),
    path("<int:pk>/archive/", ContractArchiveView.as_view(), name="contract_archive"),
    path("<int:pk>/export/<str:fmt>/", ContractExportView.as_view(), name="contract_export"),
    path("<int:pk>/rates/add/", FreightRateCreateView.as_view(), name="rate_create"),
    path("<int:pk>/rates/<int:rate_id>/edit/", FreightRateUpdateView.as_view(), name="rate_edit"),
    path("<int:pk>/rates/<int:rate_id>/delete/", FreightRateDeleteView.as_view(), name="rate_delete"),
]
