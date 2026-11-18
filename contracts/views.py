from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import DetailView, FormView, ListView

from accounts.models import CustomUser
from contracts.forms import ContractUploadForm
from contracts.models import ContractMetadata, DocumentFile
from contracts.services.pipeline import ingest_uploaded_files


class ContractOwnershipMixin(LoginRequiredMixin):
    """
    Scope contract querysets to the logged-in ENCODER's own batches,
    while allowing ADMIN users to inspect all contracts across operators.
    """

    def get_base_queryset(self):
        return ContractMetadata.objects.select_related(
            "document",
            "document__batch",
            "document__batch__user",
            "carrier",
        )

    def get_queryset(self):
        qs = self.get_base_queryset()
        if getattr(self.request.user, "role", None) == CustomUser.Role.ADMIN:
            return qs
        return qs.filter(document__batch__user=self.request.user)


class ContractUploadView(LoginRequiredMixin, FormView):
    """Single and batch digital ocean freight contract PDF upload view."""

    template_name = "contracts/contract_upload.html"
    form_class = ContractUploadForm

    def form_valid(self, form):
        files = form.cleaned_data["pdf_files"]
        carrier_hint = form.cleaned_data.get("carrier_profile") or "AUTO"

        outcome = ingest_uploaded_files(
            user=self.request.user,
            uploaded_files=files,
            carrier_override_code=carrier_hint,
        )

        for filename, reason in outcome.rejected_files:
            messages.error(self.request, reason)

        for filename, reason in outcome.failed_documents:
            messages.error(
                self.request,
                f"Extraction failed for '{filename}': {reason}",
            )

        if outcome.succeeded:
            if len(outcome.succeeded) == 1:
                contract = outcome.succeeded[0]
                rate_count = contract.freight_rates.count()
                arb_count = contract.arbitrary_charges.count()
                messages.success(
                    self.request,
                    f"Extracted '{contract.document.original_file_name}' "
                    f"(Contract {contract.contract_number}): "
                    f"{rate_count} base freight rate(s) and {arb_count} arbitrary charge(s) saved.",
                )
                return redirect(reverse("contract_detail", kwargs={"pk": contract.pk}))

            messages.success(
                self.request,
                f"Batch {outcome.batch.batch_number} completed: "
                f"{len(outcome.succeeded)} contract PDF(s) extracted into PostgreSQL.",
            )
            return redirect(reverse("contract_list"))

        return self.form_invalid(form)

    def form_invalid(self, form):
        if form.errors:
            messages.error(
                self.request,
                "Upload could not be processed. Please review the errors below.",
            )
        return super().form_invalid(form)


class ContractListView(ContractOwnershipMixin, ListView):
    """Role-scoped, searchable, filterable list of extracted ocean freight contracts."""

    template_name = "contracts/contract_list.html"
    context_object_name = "contracts"
    paginate_by = 20

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .annotate(
                rate_count=Count("freight_rates", distinct=True),
                arb_count=Count("arbitrary_charges", distinct=True),
            )
            .order_by("-extracted_at")
        )

        search_query = (self.request.GET.get("q") or "").strip()
        if search_query:
            qs = qs.filter(
                Q(contract_number__icontains=search_query)
                | Q(trade_scope__icontains=search_query)
                | Q(commodity_desc__icontains=search_query)
                | Q(carrier__carrier_code__icontains=search_query)
                | Q(carrier__carrier_name__icontains=search_query)
                | Q(document__original_file_name__icontains=search_query)
                | Q(document__batch__batch_number__icontains=search_query)
            )

        status_filter = (self.request.GET.get("status") or "ALL").strip().upper()
        if status_filter in {
            DocumentFile.Status.EXTRACTED,
            DocumentFile.Status.ARCHIVED,
            DocumentFile.Status.FAILED,
        }:
            qs = qs.filter(document__status=status_filter)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        status_filter = (self.request.GET.get("status") or "ALL").strip().upper()
        search_query = (self.request.GET.get("q") or "").strip()

        failed_docs_qs = DocumentFile.objects.select_related(
            "batch", "batch__user"
        ).filter(status=DocumentFile.Status.FAILED)
        if getattr(self.request.user, "role", None) != CustomUser.Role.ADMIN:
            failed_docs_qs = failed_docs_qs.filter(batch__user=self.request.user)
        if search_query:
            failed_docs_qs = failed_docs_qs.filter(
                Q(original_file_name__icontains=search_query)
                | Q(batch__batch_number__icontains=search_query)
            )

        context.update(
            {
                "search_query": search_query,
                "status_filter": status_filter,
                "failed_documents": failed_docs_qs.prefetch_related("jobs")[:10]
                if status_filter in {"ALL", "FAILED"}
                else DocumentFile.objects.none(),
                "is_admin_view": getattr(self.request.user, "role", None)
                == CustomUser.Role.ADMIN,
            }
        )
        return context


class ContractDetailView(ContractOwnershipMixin, DetailView):
    """Structured inspection view for contract metadata, freight rates, arbitraries, and job logs."""

    template_name = "contracts/contract_detail.html"
    context_object_name = "contract"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .prefetch_related(
                "freight_rates",
                "arbitrary_charges",
                "document__jobs",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.object
        freight_rates = list(contract.freight_rates.all())
        arbitrary_charges = list(contract.arbitrary_charges.all())
        processing_jobs = list(contract.document.jobs.all())
        context.update(
            {
                "freight_rates": freight_rates,
                "arbitrary_charges": arbitrary_charges,
                "processing_jobs": processing_jobs,
                "rate_count": len(freight_rates),
                "arb_count": len(arbitrary_charges),
            }
        )
        return context
