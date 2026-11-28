"""Shared types for official identity verification providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Status vocabulary. "verified" is only ever produced by an authorized provider response.
NOT_CONFIGURED = "not_configured"
NOT_VERIFIED = "not_verified"
VERIFIED = "verified"
FAILED = "failed"
CONSENT_MISSING = "consent_missing"
PROVIDER_ERROR = "provider_error"
VERIFICATION_STATUSES = {
    NOT_CONFIGURED,
    NOT_VERIFIED,
    VERIFIED,
    FAILED,
    CONSENT_MISSING,
    PROVIDER_ERROR,
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Consent:
    """Applicant consent for an official verification. Consent is recorded, not assumed."""

    given: bool
    purpose: str = ""
    captured_by: str = ""


@dataclass(frozen=True)
class VerificationResult:
    status: str
    provider: str
    reason_code: str | None = None
    verified_at: datetime = field(default_factory=now_utc)
    details: dict[str, Any] = field(default_factory=dict)
    """Normalized, non-identifying provider details (never raw identity data)."""
    attempts: int = 1

    @property
    def is_definitive(self) -> bool:
        return self.status in {VERIFIED, FAILED, NOT_CONFIGURED}
