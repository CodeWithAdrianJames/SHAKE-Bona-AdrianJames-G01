from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from accounts.models import CustomUser
from contracts.forms import (
    CarrierProfileForm,
    ContractMetadataForm,
    ContractUploadForm,
    FreightRateForm,
)
from contracts.models import (
    CarrierProfile,
    ContractMetadata,
    DocumentFile,
    FreightRate,
)
from contracts.services.exporter import export_contract_artifact
from contracts.services.pipeline import ingest_uploaded_files
from dashboard.views import RoleRequiredMixin

logger = logging.getLogger(__name__)


def scope_contracts_to_user(queryset, user):
    """
    Restrict a ContractMetadata queryset to what `user` may see: ENCODER users
    only their own batches' contracts, ADMIN users everything. Shared by the web
    views (ContractOwnershipMixin) and the loopback REST API (F-11).
    """
    if getattr(user, "role", None) == CustomUser.Role.ADMIN:
        return queryset
    return queryset.filter(document__batch__user=user)


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
        return scope_contracts_to_user(self.get_base_queryset(), self.request.user)

    def get_scoped_contract(self, pk: int) -> ContractMetadata:
        return get_object_or_404(ContractOwnershipMixin.get_queryset(self), pk=pk)

    def get_scoped_document(self, doc_id: int) -> DocumentFile:
        qs = DocumentFile.objects.select_related("batch", "batch__user")
        if getattr(self.request.user, "role", None) != CustomUser.Role.ADMIN:
            qs = qs.filter(batch__user=self.request.user)
        return get_object_or_404(qs, pk=doc_id)


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
                f"{len(outcome.succeeded)} contract PDF(s) extracted and saved.",
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
                "export_records__user",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        contract = self.object
        freight_rates = list(contract.freight_rates.all())
        arbitrary_charges = list(contract.arbitrary_charges.all())
        processing_jobs = list(contract.document.jobs.all())
        # Reuse the prefetched "export_records__user" rows (no extra query).
        export_records = list(contract.export_records.all())
        context.update(
            {
                "freight_rates": freight_rates,
                "arbitrary_charges": arbitrary_charges,
                "processing_jobs": processing_jobs,
                "export_records": export_records,
                "rate_count": len(freight_rates),
                "arb_count": len(arbitrary_charges),
            }
        )
        return context


class ContractMetadataUpdateView(ContractOwnershipMixin, UpdateView):
    """Edit extracted ContractMetadata fields while enforcing BR-10 and BR-11."""

    model = ContractMetadata
    form_class = ContractMetadataForm
    template_name = "contracts/contract_form.html"
    context_object_name = "contract"

    def get_success_url(self):
        return reverse("contract_detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"Updated contract metadata for '{self.object.contract_number}'.",
        )
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Contract metadata could not be updated. Please fix the validation errors below.",
        )
        return super().form_invalid(form)


class FreightRateCreateView(ContractOwnershipMixin, CreateView):
    """Create a normalized base FreightRate row for a scoped contract."""

    model = FreightRate
    form_class = FreightRateForm
    template_name = "contracts/rate_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.contract = self.get_scoped_contract(self.kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # Read MAX(line_item_sequence) and insert in one transaction while
        # holding a row lock on the parent contract (PostgreSQL), so two
        # concurrent adds cannot both claim the same sequence number.
        try:
            with transaction.atomic():
                ContractMetadata.objects.select_for_update().filter(
                    pk=self.contract.pk
                ).first()
                max_seq = (
                    self.contract.freight_rates.aggregate(
                        max_seq=Max("line_item_sequence")
                    )["max_seq"]
                    or 0
                )
                form.instance.contract = self.contract
                form.instance.line_item_sequence = max_seq + 1
                response = super().form_valid(form)
        except IntegrityError:
            logger.exception(
                "FreightRate insert failed for contract %s", self.contract.pk
            )
            form.instance.pk = None
            form.add_error(
                None,
                "The rate row could not be saved because the contract changed while "
                "you were editing. Please submit the form again.",
            )
            return self.form_invalid(form)
        messages.success(
            self.request,
            f"Added rate row #{self.object.line_item_sequence} "
            f"({self.object.origin_port_code} -> {self.object.destination_port_code} "
            f"{self.object.equipment_type}).",
        )
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Freight rate could not be saved. Please review the errors below.",
        )
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("contract_detail", kwargs={"pk": self.contract.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"contract": self.contract, "is_edit": False})
        return context


class FreightRateUpdateView(ContractOwnershipMixin, UpdateView):
    """Update an existing normalized FreightRate row for a scoped contract."""

    model = FreightRate
    form_class = FreightRateForm
    template_name = "contracts/rate_form.html"
    pk_url_kwarg = "rate_id"
    context_object_name = "rate"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        self.contract = self.get_scoped_contract(self.kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return FreightRate.objects.filter(contract=self.contract)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"Updated rate row #{self.object.line_item_sequence} "
            f"({self.object.origin_port_code} -> {self.object.destination_port_code}).",
        )
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Freight rate changes could not be saved. Please review the errors below.",
        )
        return super().form_invalid(form)

    def get_success_url(self):
        return reverse("contract_detail", kwargs={"pk": self.contract.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"contract": self.contract, "is_edit": True})
        return context


class FreightRateDeleteView(ContractOwnershipMixin, View):
    """POST-only deletion of an individual FreightRate row."""

    http_method_names = ["post", "options"]

    def post(self, request, pk: int, rate_id: int):
        contract = self.get_scoped_contract(pk)
        rate = get_object_or_404(FreightRate, pk=rate_id, contract=contract)
        seq = rate.line_item_sequence
        lane = f"{rate.origin_port_code} -> {rate.destination_port_code} ({rate.equipment_type})"
        rate.delete()
        messages.success(request, f"Deleted freight rate row #{seq} ({lane}).")
        return redirect(reverse("contract_detail", kwargs={"pk": contract.pk}))


class DocumentFileDeleteView(ContractOwnershipMixin, View):
    """
    POST-only hard deletion permitted strictly for PENDING or FAILED documents
    without linked ContractMetadata (BR-09).
    """

    http_method_names = ["post", "options"]

    def post(self, request, doc_id: int):
        doc = self.get_scoped_document(doc_id)
        linked_contract = ContractMetadata.objects.filter(document=doc).first()
        deletable_statuses = {DocumentFile.Status.PENDING, DocumentFile.Status.FAILED}

        if linked_contract is not None or doc.status not in deletable_statuses:
            messages.error(
                request,
                f"Cannot hard-delete '{doc.original_file_name}': extracted or archived "
                "documents are protected by BR-09. Use Archive instead.",
            )
            if linked_contract is not None:
                return redirect(
                    reverse("contract_detail", kwargs={"pk": linked_contract.pk})
                )
            return redirect(reverse("contract_list"))

        filename = doc.original_file_name
        stored_file = doc.uploaded_file if doc.uploaded_file else None
        with transaction.atomic():
            # Deletes the DocumentFile and its ProcessingJob rows together.
            doc.delete()
            if stored_file is not None:
                # Remove the PDF from disk only after the rows are committed,
                # so a failed delete never leaves a row pointing at a lost file.
                transaction.on_commit(lambda: _delete_stored_file(stored_file))
        messages.success(request, f"Deleted unextracted document '{filename}'.")
        return redirect(reverse("contract_list"))


def _delete_stored_file(stored_file) -> None:
    """Delete an uploaded file from storage, logging (not hiding) any failure."""
    try:
        stored_file.storage.delete(stored_file.name)
    except OSError:
        logger.exception("Could not remove stored file %s", stored_file.name)


class ContractArchiveView(ContractOwnershipMixin, View):
    """POST-only non-destructive archive transition (DocumentFile.status = ARCHIVED, BR-09)."""

    http_method_names = ["post", "options"]

    def post(self, request, pk: int):
        contract = self.get_scoped_contract(pk)
        doc = contract.document
        if doc.status != DocumentFile.Status.ARCHIVED:
            doc.status = DocumentFile.Status.ARCHIVED
            doc.save(update_fields=["status"])
            messages.success(
                request,
                f"Contract '{contract.contract_number}' has been archived (BR-09).",
            )
        else:
            messages.info(
                request,
                f"Contract '{contract.contract_number}' is already archived.",
            )

        next_url = (request.POST.get("next") or "").strip()
        if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}
        ):
            return redirect(next_url)
        return redirect(reverse("contract_detail", kwargs={"pk": contract.pk}))


class ContractExportView(ContractOwnershipMixin, View):
    """Export contract data to JSON, XLSX, or CSV via contracts.engine.exporter and log ExportRecord."""

    http_method_names = ["get", "head", "options"]

    def get(self, request, pk: int, fmt: str):
        contract = self.get_scoped_contract(pk)
        try:
            artifact = export_contract_artifact(
                contract=contract,
                user=request.user,
                fmt=fmt,
            )
        except ValueError as exc:
            raise Http404("Unsupported export format.") from exc
        except OSError:
            logger.exception("Export of contract %s as %s failed", contract.pk, fmt)
            messages.error(
                request,
                f"The {fmt.upper()} export for '{contract.contract_number}' could not be "
                "written to disk. Please try again or contact your administrator.",
            )
            return redirect(reverse("contract_detail", kwargs={"pk": contract.pk}))

        response = HttpResponse(artifact.content_bytes, content_type=artifact.content_type)
        response["Content-Disposition"] = f'attachment; filename="{artifact.filename}"'
        return response


class CarrierProfileListView(RoleRequiredMixin, ListView):
    """Admin-only list of registered shipping carrier profiles (F-02)."""

    required_role = CustomUser.Role.ADMIN
    template_name = "contracts/carrier_list.html"
    context_object_name = "carriers"

    def get_queryset(self):
        return CarrierProfile.objects.annotate(
            contract_count=Count("contracts", distinct=True)
        ).order_by("carrier_code")


class CarrierProfileCreateView(RoleRequiredMixin, CreateView):
    """Admin-only create view for CarrierProfile (BR-03)."""

    required_role = CustomUser.Role.ADMIN
    model = CarrierProfile
    form_class = CarrierProfileForm
    template_name = "contracts/carrier_form.html"
    success_url = reverse_lazy("carrier_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"Created carrier profile '{self.object.carrier_code} — {self.object.carrier_name}'.",
        )
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Carrier profile could not be created. Please review the errors below.",
        )
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_edit"] = False
        return context


class CarrierProfileUpdateView(RoleRequiredMixin, UpdateView):
    """Admin-only update view for CarrierProfile (BR-03)."""

    required_role = CustomUser.Role.ADMIN
    model = CarrierProfile
    form_class = CarrierProfileForm
    template_name = "contracts/carrier_form.html"
    context_object_name = "carrier"
    success_url = reverse_lazy("carrier_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"Updated carrier profile '{self.object.carrier_code} — {self.object.carrier_name}'.",
        )
        return response

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Carrier profile could not be updated. Please review the errors below.",
        )
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["is_edit"] = True
        return context


class CarrierProfileToggleView(RoleRequiredMixin, View):
    """Admin-only POST action to activate or deactivate a CarrierProfile."""

    required_role = CustomUser.Role.ADMIN
    http_method_names = ["post", "options"]

    def post(self, request, pk: int):
        carrier = get_object_or_404(CarrierProfile, pk=pk)
        carrier.is_active = not carrier.is_active
        carrier.save(update_fields=["is_active"])
        state_label = "activated" if carrier.is_active else "deactivated"
        messages.success(
            request,
            f"Carrier profile '{carrier.carrier_code}' has been {state_label}.",
        )
        return redirect(reverse("carrier_list"))
