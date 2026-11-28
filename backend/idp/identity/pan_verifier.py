"""PAN verification adapter for an authorized provider.

The provider endpoint, credentials and eligibility are organization specific, so the adapter is a
configurable HTTPS client with request preparation, response normalization, retries and timeout
handling. Credentials come from environment configuration only. The full PAN is held in memory
for the call and is never stored or logged.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from idp.config import Settings
from idp.identity.masking import PAN_STRICT_RE
from idp.identity.verification_types import (
    CONSENT_MISSING,
    FAILED,
    NOT_CONFIGURED,
    PROVIDER_ERROR,
    VERIFIED,
    Consent,
    VerificationResult,
)

logger = logging.getLogger(__name__)
_VALID_RESPONSES = {"valid": VERIFIED, "invalid": FAILED}


@dataclass(frozen=True)
class PanVerificationRequest:
    pan_number: str
    consent: Consent
    name: str | None = None
    date_of_birth: str | None = None

    def __repr__(self) -> str:  # Keep identifiers out of tracebacks and logs.
        return "PanVerificationRequest(<redacted>)"


class PanVerifier(Protocol):
    name: str

    def verify(self, request: PanVerificationRequest) -> VerificationResult: ...


class NotConfiguredPanVerifier:
    name = "not_configured"

    def verify(self, request: PanVerificationRequest) -> VerificationResult:
        del request
        return VerificationResult(
            status=NOT_CONFIGURED,
            provider=self.name,
            reason_code="pan_verification_not_configured",
        )


def prepare_request_body(request: PanVerificationRequest) -> dict[str, Any]:
    body: dict[str, Any] = {"pan": request.pan_number.upper(), "consent": True}
    if request.name:
        body["name"] = request.name
    if request.date_of_birth:
        body["dob"] = request.date_of_birth
    return body


def normalize_response(payload: Any, provider: str, attempts: int) -> VerificationResult:
    """Map a provider response to a status. Anything unexpected is ``provider_error``."""
    if not isinstance(payload, dict):
        return VerificationResult(
            status=PROVIDER_ERROR,
            provider=provider,
            reason_code="invalid_provider_response",
            attempts=attempts,
        )
    raw_status = str(payload.get("status", "")).strip().lower()
    status = _VALID_RESPONSES.get(raw_status)
    if status is None:
        return VerificationResult(
            status=PROVIDER_ERROR,
            provider=provider,
            reason_code="invalid_provider_response",
            attempts=attempts,
        )
    details: dict[str, Any] = {}
    for key in ("name_match", "dob_match"):
        if isinstance(payload.get(key), bool):
            details[key] = payload[key]
    return VerificationResult(
        status=status,
        provider=provider,
        reason_code=None if status == VERIFIED else "provider_reported_invalid",
        details=details,
        attempts=attempts,
    )


class HttpPanVerifier:
    name = "http"

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        timeout: float,
        max_retries: int,
        client: httpx.Client | None = None,
    ):
        self._endpoint = endpoint
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client

    def verify(self, request: PanVerificationRequest) -> VerificationResult:
        if not request.consent.given:
            return VerificationResult(
                status=CONSENT_MISSING, provider=self.name, reason_code="consent_missing"
            )
        if not PAN_STRICT_RE.fullmatch(re.sub(r"\s", "", request.pan_number).upper()):
            return VerificationResult(
                status=FAILED, provider=self.name, reason_code="pan_format_invalid"
            )
        body = prepare_request_body(request)
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        attempts = 0
        last_reason = "provider_unavailable"
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            while attempts <= self._max_retries:
                attempts += 1
                try:
                    response = client.post(
                        self._endpoint, json=body, headers=headers, timeout=self._timeout
                    )
                except httpx.TimeoutException:
                    last_reason = "provider_timeout"
                    continue
                except httpx.HTTPError:
                    last_reason = "provider_unavailable"
                    continue
                if response.status_code >= 500 or response.status_code == 429:
                    last_reason = "provider_unavailable"
                    continue
                if response.status_code >= 400:
                    return VerificationResult(
                        status=PROVIDER_ERROR,
                        provider=self.name,
                        reason_code=f"provider_rejected_{response.status_code}",
                        attempts=attempts,
                    )
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                return normalize_response(payload, self.name, attempts)
        finally:
            if self._client is None:
                client.close()
        logger.warning("PAN verification provider failed reason=%s attempts=%s", last_reason, attempts)
        return VerificationResult(
            status=PROVIDER_ERROR, provider=self.name, reason_code=last_reason, attempts=attempts
        )


def build_pan_verifier(settings: Settings, *, client: httpx.Client | None = None) -> PanVerifier:
    if (
        settings.identity_pan_provider != "http"
        or not settings.identity_pan_endpoint
        or settings.identity_pan_api_key is None
    ):
        return NotConfiguredPanVerifier()
    return HttpPanVerifier(
        endpoint=settings.identity_pan_endpoint,
        api_key=settings.identity_pan_api_key.get_secret_value(),
        timeout=settings.identity_pan_timeout_seconds,
        max_retries=settings.identity_pan_max_retries,
        client=client,
    )
