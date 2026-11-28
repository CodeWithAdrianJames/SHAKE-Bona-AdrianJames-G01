"""
Lightweight local loopback REST API (F-11).

Every request passes three gates in order before reaching a handler:

1. Loopback guard: REMOTE_ADDR must be in settings.SHAKE_API_LOOPBACK_ADDRESSES,
   otherwise 403. Proxy headers such as X-Forwarded-For are ignored.
2. Authentication: `Authorization: Bearer <token>` for an active APIToken whose
   user is active, or else an authenticated Django session. Failure is 401 JSON,
   never an HTML login redirect.
3. CSRF: Bearer-token requests are exempt (no ambient browser credential is
   involved); session-authenticated unsafe requests must pass Django's CSRF check.
"""

from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from accounts.models import APIToken
from contracts.forms import MAX_UPLOAD_SIZE_BYTES
from contracts.models import ContractMetadata
from contracts.services.exporter import build_contract_api_payload
from contracts.services.pipeline import DuplicateDocumentError, ingest_uploaded_files
from contracts.views import scope_contracts_to_user

LOOPBACK_DENIED_DETAIL = "API access is restricted to localhost loopback connections."
AUTH_FAILED_DETAIL = "Authentication credentials were not provided or are invalid."
CONTRACT_NOT_FOUND_DETAIL = "Contract not found."
WWW_AUTHENTICATE_VALUE = 'Bearer realm="SHAKE local API"'


def api_error(detail: str, status: int, **extra) -> JsonResponse:
    """Return a JSON error body of the form {"detail": ..., **extra}."""
    return JsonResponse({"detail": detail, **extra}, status=status)


def is_loopback_request(request) -> bool:
    """True when the socket peer address is an allowed loopback address."""
    if not getattr(settings, "SHAKE_API_LOOPBACK_ONLY", True):
        return True
    allowed = set(getattr(settings, "SHAKE_API_LOOPBACK_ADDRESSES", ("127.0.0.1", "::1")))
    return request.META.get("REMOTE_ADDR", "") in allowed


def authenticate_api_request(request):
    """
    Resolve the API caller. Returns (user, via_token); user is None when
    authentication failed. A present Authorization header is authoritative: an
    invalid or revoked token fails even if a valid session cookie is also sent.
    """
    header = request.META.get("HTTP_AUTHORIZATION", "").strip()
    if header:
        scheme, _, key = header.partition(" ")
        key = key.strip()
        if scheme.lower() != "bearer" or not key or " " in key:
            return None, True
        token = (
            APIToken.objects.select_related("user")
            .filter(key=key, is_active=True, user__is_active=True)
            .first()
        )
        if token is None:
            return None, True
        APIToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return token.user, True

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return user, False
    return None, False


class _SessionCsrfCheck(CsrfViewMiddleware):
    """Runs Django's CSRF validation on demand and returns the failure reason."""

    def _reject(self, request, reason):
        return reason


def csrf_failure_reason(request) -> str | None:
    """Return None if the request passes CSRF validation, else the reason."""
    check = _SessionCsrfCheck(lambda req: None)
    check.process_request(request)
    return check.process_view(request, None, (), {})


@method_decorator(csrf_exempt, name="dispatch")
class LoopbackAPIView(View):
    """Base view applying the loopback guard, authentication, and JSON errors."""

    def dispatch(self, request, *args, **kwargs):
        if not is_loopback_request(request):
            return api_error(LOOPBACK_DENIED_DETAIL, 403)

        user, via_token = authenticate_api_request(request)
        if user is None:
            response = api_error(AUTH_FAILED_DETAIL, 401)
            response["WWW-Authenticate"] = WWW_AUTHENTICATE_VALUE
            return response

        if not via_token:
            reason = csrf_failure_reason(request)
            if reason:
                return api_error(f"CSRF verification failed: {reason}", 403)

        request.user = user
        return super().dispatch(request, *args, **kwargs)

    def http_method_not_allowed(self, request, *args, **kwargs):
        response = api_error(f'Method "{request.method}" not allowed.', 405)
        response["Allow"] = ", ".join(self._allowed_methods())
        return response


class ContractIngestAPIView(LoopbackAPIView):
    """
    POST /api/v1/ingest — ingest one contract PDF (multipart field `file`)
    through the same offline pipeline as the web upload, as request.user.
    """

    http_method_names = ["post", "options"]

    def post(self, request, *args, **kwargs):
        if not (request.content_type or "").startswith("multipart/form-data"):
            return api_error(
                "Content-Type must be multipart/form-data with the PDF in the 'file' field.",
                400,
            )

        uploads = request.FILES.getlist("file")
        if len(uploads) != 1:
            return api_error("Upload exactly one PDF in the multipart 'file' field.", 400)
        upload = uploads[0]

        if (upload.size or 0) > MAX_UPLOAD_SIZE_BYTES:
            return api_error(f"File '{upload.name}' exceeds the 100 MB maximum upload limit.", 400)

        outcome = ingest_uploaded_files(user=request.user, uploaded_files=[upload])

        if outcome.rejected_errors:
            error = outcome.rejected_errors[0]
            if isinstance(error, DuplicateDocumentError):
                return api_error(str(error), 409, rule="BR-06")
            return api_error(str(error), 400, rule="BR-07/BR-08")

        if not outcome.succeeded:
            reason = outcome.failed_documents[0][1] if outcome.failed_documents else "Unknown error."
            return api_error(
                f"Extraction failed for '{upload.name}': {reason}",
                422,
                batch_id=outcome.batch.pk if outcome.batch else None,
            )

        contract = outcome.succeeded[0]
        document = contract.document
        return JsonResponse(
            {
                "contract_id": contract.pk,
                "batch_id": outcome.batch.pk,
                "batch_number": outcome.batch.batch_number,
                "document_id": document.pk,
                "original_file_name": document.original_file_name,
                "file_hash_sha256": document.file_hash_sha256,
                "contract_number": contract.contract_number,
                "carrier_code": contract.carrier.carrier_code,
                "status": document.status,
                "rates_count": contract.freight_rates.count(),
                "arbitraries_count": contract.arbitrary_charges.count(),
                "detail_url": reverse("api_contract_detail", kwargs={"pk": contract.pk}),
            },
            status=201,
        )


class ContractDetailAPIView(LoopbackAPIView):
    """
    GET /api/v1/contracts/<pk> — canonical contract JSON. ENCODER users see only
    contracts from their own batches (archived included, BR-09); ADMIN sees all.
    Anything outside that scope is indistinguishable from a missing ID (404).
    """

    http_method_names = ["get", "head", "options"]

    def get(self, request, pk, *args, **kwargs):
        queryset = ContractMetadata.objects.select_related("document", "carrier")
        contract = scope_contracts_to_user(queryset, request.user).filter(pk=pk).first()
        if contract is None:
            return api_error(CONTRACT_NOT_FOUND_DETAIL, 404)
        return JsonResponse(build_contract_api_payload(contract), status=200)
