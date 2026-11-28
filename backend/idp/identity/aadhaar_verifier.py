"""Aadhaar authenticity verification adapter.

Only authorized offline verification is modelled here (UIDAI secure QR or a digitally signed
e-Aadhaar). No online Aadhaar authentication is implemented and no biometric data is handled.

Without trusted verification material the adapter returns ``not_configured``. A readable QR code
is never reported as authentic: the signature must verify against a trusted certificate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from idp.config import Settings
from idp.identity.verification_types import (
    CONSENT_MISSING,
    FAILED,
    NOT_CONFIGURED,
    PROVIDER_ERROR,
    VERIFIED,
    Consent,
    VerificationResult,
)


@dataclass(frozen=True)
class AadhaarVerificationRequest:
    qr_payload: bytes | None
    consent: Consent
    """The secure QR payload exists only in memory for the duration of the call."""


class AadhaarVerifier(Protocol):
    name: str

    def verify(self, request: AadhaarVerificationRequest) -> VerificationResult: ...


class NotConfiguredAadhaarVerifier:
    name = "not_configured"

    def verify(self, request: AadhaarVerificationRequest) -> VerificationResult:
        del request
        return VerificationResult(
            status=NOT_CONFIGURED,
            provider=self.name,
            reason_code="aadhaar_verification_not_configured",
        )


# A signature validator receives the payload and the trusted certificate bytes and returns True
# only when the signature chain validates. It raises ``ValueError`` for malformed payloads.
SignatureValidator = Callable[[bytes, bytes], bool]


class UidaiOfflineQrVerifier:
    """Verifies a UIDAI signed payload with an injected, reviewed signature validator.

    The validator is deliberately injected: signature handling must come from a reviewed
    implementation and the official UIDAI certificate, not from ad hoc code here.
    """

    name = "uidai-offline-qr"

    def __init__(self, *, trust_certificate: bytes, validator: SignatureValidator):
        self._certificate = trust_certificate
        self._validator = validator

    def verify(self, request: AadhaarVerificationRequest) -> VerificationResult:
        if not request.consent.given:
            return VerificationResult(
                status=CONSENT_MISSING, provider=self.name, reason_code="consent_missing"
            )
        if not request.qr_payload:
            return VerificationResult(
                status=NOT_CONFIGURED, provider=self.name, reason_code="qr_payload_missing"
            )
        try:
            valid = self._validator(request.qr_payload, self._certificate)
        except ValueError:
            return VerificationResult(
                status=FAILED, provider=self.name, reason_code="qr_payload_malformed"
            )
        except Exception:
            return VerificationResult(
                status=PROVIDER_ERROR, provider=self.name, reason_code="validator_error"
            )
        if valid is True:
            return VerificationResult(status=VERIFIED, provider=self.name)
        return VerificationResult(
            status=FAILED, provider=self.name, reason_code="signature_validation_failed"
        )


def build_aadhaar_verifier(
    settings: Settings, *, validator: SignatureValidator | None = None
) -> AadhaarVerifier:
    """Select the verifier from configuration. Missing material means ``not_configured``."""
    if settings.identity_aadhaar_provider != "uidai-offline-qr":
        return NotConfiguredAadhaarVerifier()
    cert_path = settings.identity_aadhaar_trust_cert_path
    if cert_path is None or not Path(cert_path).is_file() or validator is None:
        # No official certificate or no reviewed validator: never claim verification.
        return NotConfiguredAadhaarVerifier()
    return UidaiOfflineQrVerifier(
        trust_certificate=Path(cert_path).read_bytes(), validator=validator
    )
