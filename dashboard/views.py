from functools import wraps

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.generic import RedirectView, TemplateView

from accounts.models import CustomUser

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
    Displays system user metrics, the registered user roster, carrier parser templates,
    and Offline OpenDataLoader AST Engine health status.
    """

    required_role = CustomUser.Role.ADMIN
    template_name = "dashboard/admin_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        users_qs = CustomUser.objects.all().order_by("-date_joined")

        carrier_parsers = [
            {
                "carrier": "MSC",
                "full_name": "Mediterranean Shipping Company",
                "template_code": "MSC-SEA-2026-V4",
                "rate_sections": "Base Ocean Freight, Origin/Destination Arbitraries, Bunker & PSS",
                "ast_strategy": "Multi-page header stitching & commodity group hierarchy",
                "supported_containers": "20GP, 40GP, 40HQ, 40RH",
                "status": "Active",
            },
            {
                "carrier": "CMA CGM",
                "full_name": "CMA CGM Group",
                "template_code": "CMACGM-ASIA-EUR-V3",
                "rate_sections": "Mainline Tariff Grids, Outport Add-Ons, Local THC & Surcharges",
                "ast_strategy": "Bounding-box column alignment & footnote clause resolution",
                "supported_containers": "20ST, 40ST, 40HC",
                "status": "Active",
            },
            {
                "carrier": "COSCO",
                "full_name": "COSCO Shipping Lines",
                "template_code": "COSCO-GLOBAL-SC-V2",
                "rate_sections": "Service Contract Appendices, Inland Arbitraries, Equipment Matrix",
                "ast_strategy": "Merged-cell span normalization & currency/unit disambiguation",
                "supported_containers": "20GP, 40GP, 40HQ",
                "status": "Active",
            },
        ]

        context.update(
            {
                "registered_users": users_qs,
                "total_users_count": users_qs.count(),
                "admin_users_count": users_qs.filter(role=CustomUser.Role.ADMIN).count(),
                "encoder_users_count": users_qs.filter(role=CustomUser.Role.ENCODER).count(),
                "active_parsers_count": len(carrier_parsers),
                "carrier_parsers": carrier_parsers,
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
    Displays the Ocean Freight Contract PDF upload dropzone, recent extraction jobs,
    and standardized output schema specifications (.xlsx, .csv, .json).
    """

    required_role = CustomUser.Role.ENCODER
    template_name = "dashboard/encoder_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        carrier_options = [
            {
                "code": "MSC",
                "label": "MSC — Mediterranean Shipping Company (MSC-SEA-2026-V4)",
            },
            {
                "code": "CMA_CGM",
                "label": "CMA CGM — Service Contract Tariff (CMACGM-ASIA-EUR-V3)",
            },
            {
                "code": "COSCO",
                "label": "COSCO — Ocean Freight Rate Appendix (COSCO-GLOBAL-SC-V2)",
            },
        ]

        recent_extractions = [
            {
                "job_id": "JOB-2026-0104",
                "carrier": "MSC",
                "pdf_filename": "MSC_Service_Contract_PH_EU_2026_Amend3.pdf",
                "ocean_rate_rows": 418,
                "arbitrary_rows": 96,
                "total_rows": 514,
                "processed_at": "Today, 14:20 PST",
                "status": "Exported",
                "status_badge": "bg-success-subtle text-success border border-success-subtle",
            },
            {
                "job_id": "JOB-2026-0103",
                "carrier": "CMA CGM",
                "pdf_filename": "CMACGM_Q4_Asia_Med_Tariff_Schedule.pdf",
                "ocean_rate_rows": 284,
                "arbitrary_rows": 62,
                "total_rows": 346,
                "processed_at": "Today, 11:05 PST",
                "status": "Parsed",
                "status_badge": "bg-info-subtle text-info-emphasis border border-info-subtle",
            },
            {
                "job_id": "JOB-2026-0102",
                "carrier": "COSCO",
                "pdf_filename": "COSCO_Transpacific_Contract_Appendix_B.pdf",
                "ocean_rate_rows": 510,
                "arbitrary_rows": 118,
                "total_rows": 628,
                "processed_at": "Yesterday, 17:42 PST",
                "status": "Exported",
                "status_badge": "bg-success-subtle text-success border border-success-subtle",
            },
            {
                "job_id": "JOB-2026-0101",
                "carrier": "MSC",
                "pdf_filename": "MSC_IntraAsia_Reefer_Dry_Tariff_2026.pdf",
                "ocean_rate_rows": 192,
                "arbitrary_rows": 44,
                "total_rows": 236,
                "processed_at": "Nov 14, 09:15 PST",
                "status": "Parsed",
                "status_badge": "bg-info-subtle text-info-emphasis border border-info-subtle",
            },
        ]

        output_schemas = [
            {
                "title": "Unified Excel Workbook",
                "extension": ".xlsx",
                "icon": "bi-file-earmark-excel-fill",
                "accent_class": "text-success",
                "badge_class": "bg-success-subtle text-success border border-success-subtle",
                "sheets_or_structure": "4 Standardized Tabs: Ocean_Rates, Origin_Arbitraries, Dest_Arbitraries, Surcharges",
                "description": (
                    "Normalized multi-sheet workbook with frozen headers, validated currency codes, "
                    "and side-by-side 20GP / 40GP / 40HQ container rate columns."
                ),
            },
            {
                "title": "Flattened Relational Feed",
                "extension": ".csv",
                "icon": "bi-filetype-csv",
                "accent_class": "text-primary",
                "badge_class": "bg-primary-subtle text-primary border border-primary-subtle",
                "sheets_or_structure": "UTF-8 Delimited • 18 Canonical Columns per Trade Lane Row",
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
                "sheets_or_structure": "Hierarchical JSON Schema v2 • Page & Bounding-Box Coordinates",
                "description": (
                    "Complete Abstract Syntax Tree preserving source PDF table coordinates, commodity "
                    "footnotes, validity windows, and surcharge rule references."
                ),
            },
        ]

        context.update(
            {
                "carrier_options": carrier_options,
                "recent_extractions": recent_extractions,
                "output_schemas": output_schemas,
                "total_parsed_contracts": len(recent_extractions),
                "total_extracted_rows": sum(job["total_rows"] for job in recent_extractions),
            }
        )
        return context
