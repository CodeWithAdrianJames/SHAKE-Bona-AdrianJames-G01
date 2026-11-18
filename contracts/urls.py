from django.urls import path

from .views import ContractDetailView, ContractListView, ContractUploadView

urlpatterns = [
    path("", ContractListView.as_view(), name="contract_list"),
    path("upload/", ContractUploadView.as_view(), name="contract_upload"),
    path("<int:pk>/", ContractDetailView.as_view(), name="contract_detail"),
]
