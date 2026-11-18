from functools import wraps

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import RedirectView, TemplateView

from accounts.models import CustomUser
from contracts.models import (
    ArbitraryCharge,
    BatchUpload,
    CarrierProfile,
    ContractMetadata,
    DocumentFile,
    ExportRecord,
    FreightRate,
    ProcessingJob,
)

UNAUTHORIZED_DASHBOARD_MESSAGE = (
    "Unauthorized access: you do not have permission to view that dashboard."
)


def get_role_dashboard_url(user) -> str:
    """
    Return the canonical dashboard URL path corresponding to the authenticated user's role.
    Defaults to the Encoder dashboard for standard Freight Analyst / Encoder accounts.
    """
    if getattr(user, "role", None) == CustomUser.Role.ADMIN:
        return reverse("admin_dashboard")
    return reverse("encoder_dashboard")


class RoleRequiredMixin(LoginRequiredMixin):
    """
    Reusable view guard requiring both authentication (LoginRequiredMixin) and
    a matching CustomUser role (`required_role`).

    When an authenticated user with a different role attempts to access the view,
    access is strictly blocked: a Bootstrap danger flash message is queued and the
    user is redirected to their own role's dashboard (or rendered a 403 Forbidden
    page if `return_403 = True`).
    """

    required_role = None
    return_403 = False

    def get_allowed_roles(self):
        if self.required_role is None:
            return ()
        if isinstance(self.required_role, (list, tuple, set, frozenset)):
            return tuple(self.required_role)
        return (self.required_role,)

    def has_required_role(self, user) -> bool:
        allowed_roles = self.get_allowed_roles()
        if not allowed_roles:
            return True
        return getattr(user, "role", None) in allowed_roles

    def handle_role_denied(self, request):
        messages.error(request, UNAUTHORIZED_DASHBOARD_MESSAGE)
        if self.return_403:
            return render(
                request,
                "403.html",
                {
                    "error_message": UNAUTHORIZED_DASHBOARD_MESSAGE,
                    "fallback_dashboard_url": get_role_dashboard_url(request.user),
                },
                status=403,
            )
        return redirect(get_role_dashboard_url(request.user))

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not self.has_required_role(request.user):
            return self.handle_role_denied(request)
        return super().dispatch(request, *args, **kwargs)


def role_required(required_role, return_403: bool = False):
    """
    Reusable function-based view decorator enforcing authentication and role matching.
    """
    if isinstance(required_role, (list, tuple, set, frozenset)):
        allowed_roles = tuple(required_role)
    else:
        allowed_roles = (required_role,)

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if getattr(request.user, "role", None) not in allowed_roles:
                messages.error(request, UNAUTHORIZED_DASHBOARD_MESSAGE)
                if return_403:
                    return render(
                        request,
                        "403.html",
                        {
                            "error_message": UNAUTHORIZED_DASHBOARD_MESSAGE,
                            "fallback_dashboard_url": get_role_dashboard_url(request.user),
                        },
                        status=403,
                    )
                return redirect(get_role_dashboard_url(request.user))
            return view_func(request, *args, **kwargs)

        return _wrapped_view

    return decorator


class DashboardRedirectView(LoginRequiredMixin, RedirectView):
    """
    Root workspace entry point (`/`).
    Redirects unauthenticated visitors to `/accounts/login/` and routes
    authenticated users to their role-specific SHAKE dashboard.
    """

    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return get_role_dashboard_url(self.request.user)


# Backwards-compatible alias
DashboardView = DashboardRedirectView


class AdminDashboardView(RoleRequiredMixin, TemplateView):
    """
    Operations Admin Dashboard (`/dashboard/admin/`).
    Restricted strictly to users with `CustomUser.Role.ADMIN`.
    Displays live PostgreSQL system metrics, the registered user roster,
    carrier parser profiles, recent processing/export activity, and Offline
    OpenDataLoader AST Engine health status.
    """

    required_role = CustomUser.Role.ADMIN
    template_name = "dashboard/admin_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        users_qs = CustomUser.objects.annotate(
            batch_count=Count("batch_uploads", distinct=True)
        ).order_by("-date_joined")
        carrier_profiles = list(
            CarrierProfile.objects.annotate(
                contract_count=Count("contracts", distinct=True)
            ).order_by("carrier_code")
        )
        active_carriers_count = sum(1 for c in carrier_profiles if c.is_active)

        recent_jobs = list(
            ProcessingJob.objects.select_related(
                "document",
                "document__batch",
                "document__batch__user",
                "document__contract_metadata",
                "document__contract_metadata__carrier",
            ).order_by("-started_at")[:10]
        )
        recent_exports = list(
            ExportRecord.objects.select_related(
                "user",
                "contract",
                "contract__carrier",
            ).order_by("-exported_at")[:10]
        )

        context.update(
            {
                "registered_users": users_qs,
                "total_users_count": CustomUser.objects.count(),
                "admin_users_count": CustomUser.objects.filter(
                    role=CustomUser.Role.ADMIN
                ).count(),
                "encoder_users_count": CustomUser.objects.filter(
                    role=CustomUser.Role.ENCODER
                ).count(),
                "total_batches_count": BatchUpload.objects.count(),
                "extracted_contracts_count": ContractMetadata.objects.count(),
                "total_rate_rows_count": FreightRate.objects.count(),
                "total_arb_rows_count": ArbitraryCharge.objects.count(),
                "total_exports_count": ExportRecord.objects.count(),
                "active_carriers_count": active_carriers_count,
                "active_parsers_count": active_carriers_count,
                "carrier_profiles": carrier_profiles,
                "recent_jobs": recent_jobs,
                "recent_exports": recent_exports,
                "engine_status": {
                    "name": "OpenDataLoader AST Engine v2.4",
                    "mode": "100% Offline Air-Gapped Execution",
                    "status_label": "Operational & Ready",
                    "latency_target": "< 1.8s / 50-page PDF",
                    "export_targets": "Unified .xlsx • Flattened .csv • Canonical .json AST",
                },
            }
        )
        return context


class EncoderDashboardView(RoleRequiredMixin, TemplateView):
    """
    Freight Analyst / Encoder Dashboard (`/dashboard/encoder/`).
    Restricted strictly to users with `CustomUser.Role.ENCODER`.
    Displays live personal extraction KPIs, quick-upload CTA, recent extraction jobs,
    and standardized output schema specifications (.xlsx, .csv, .json).
    """

    required_role = CustomUser.Role.ENCODER
    template_name = "dashboard/encoder_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        user_batches_count = BatchUpload.objects.filter(user=user).count()
        extracted_contracts_count = ContractMetadata.objects.filter(
            document__batch__user=user
        ).count()
        total_rate_rows_count = FreightRate.objects.filter(
            contract__document__batch__user=user
        ).count()
        total_arb_rows_count = ArbitraryCharge.objects.filter(
            contract__document__batch__user=user
        ).count()
        exports_generated_count = ExportRecord.objects.filter(user=user).count()

        recent_documents = list(
            DocumentFile.objects.filter(batch__user=user)
            .select_related("batch", "contract_metadata", "contract_metadata__carrier")
            .annotate(
                rate_count=Count("contract_metadata__freight_rates", distinct=True),
                arb_count=Count("contract_metadata__arbitrary_charges", distinct=True),
            )
            .prefetch_related("jobs")
            .order_by("-uploaded_at")[:10]
        )
        active_carriers = list(
            CarrierProfile.objects.filter(is_active=True).order_by("carrier_code")
        )

        output_schemas = [
            {
                "title": "Unified Excel Workbook",
                "extension": ".xlsx",
                "icon": "bi-file-earmark-excel-fill",
                "accent_class": "text-success",
                "badge_class": "bg-success-subtle text-success border border-success-subtle",
                "sheets_or_structure": "3 Normalized Tabs: Rates, Origin_Arbitraries, Destination_Arbitraries",
                "description": (
                    "Normalized multi-sheet workbook with validated currency codes "
                    "and side-by-side 20GP / 40GP / 40HC / 45HC container rate columns."
                ),
            },
            {
                "title": "Flattened Relational Feed",
                "extension": ".csv",
                "icon": "bi-filetype-csv",
                "accent_class": "text-primary",
                "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
                "sheets_or_structure": "UTF-8 Delimited • Canonical Rate Columns per Trade Lane Row",
                "description": (
                    "Denormalized flat file engineered for direct bulk ingestion into TMS/ERP rate "
                    "tables and PostgreSQL analytics pipelines."
                ),
            },
            {
                "title": "Canonical Document AST",
                "extension": ".json",
                "icon": "bi-filetype-json",
                "accent_class": "text-warning-emphasis",
                "badge_class": "bg-warning-subtle text-warning-emphasis border border-warning-subtle",
                "sheets_or_structure": "Hierarchical JSON Schema • Rates & Arbitrary Sections",
                "description": (
                    "Complete structured contract payload preserving carrier metadata, "
                    "validity dates, trade scope, commodity, and normalized rates."
                ),
            },
        ]

        context.update(
            {
                "user_batches_count": user_batches_count,
                "extracted_contracts_count": extracted_contracts_count,
                "total_rate_rows_count": total_rate_rows_count,
                "total_arb_rows_count": total_arb_rows_count,
                "exports_generated_count": exports_generated_count,
                "recent_documents": recent_documents,
                "active_carriers": active_carriers,
                "output_schemas": output_schemas,
            }
        )
        return context
