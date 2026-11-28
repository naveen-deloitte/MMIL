"""API models for the identity verification endpoints."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from idp.schemas import ApiModel, FieldOut


class ConsentIn(BaseModel):
    given: bool = False
    purpose: str = Field(default="", max_length=200)


class IdentityVerifyIn(BaseModel):
    subjects: list[Literal["aadhaar", "pan"]] = Field(default_factory=lambda: ["aadhaar", "pan"])
    consent: ConsentIn = Field(default_factory=ConsentIn)
    pan_number: str | None = Field(default=None, max_length=20, repr=False)
    """Held in memory for one provider call. Never stored or logged."""
    qr_payload_base64: str | None = Field(default=None, max_length=200_000, repr=False)

    @field_validator("pan_number")
    @classmethod
    def normalize_pan(cls, value: str | None) -> str | None:
        if value is None:
            return None
        compact = re.sub(r"\s", "", value).upper()
        if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", compact):
            raise ValueError("pan_number has an invalid format")
        return compact

    @field_validator("qr_payload_base64")
    @classmethod
    def validate_qr(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("qr_payload_base64 is not valid base64") from exc
        return value


class IdentityReviewIn(BaseModel):
    decision: Literal["confirmed", "rejected", "follow_up_required"]
    rationale: str | None = Field(default=None, max_length=2000)
    resolved_fields: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("rationale")
    @classmethod
    def strip_rationale(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


class IdentityDocumentOut(ApiModel):
    subject: str
    state: str
    """not_uploaded | processing | failed | extracted"""
    document_id: str | None = None
    filename: str | None = None
    document_status: str | None = None
    failure_code: str | None = None
    action_required: str | None = None
    extraction_confidence: float | None = None
    fields: list[FieldOut] = Field(default_factory=list)


class IdentityFindingOut(ApiModel):
    subject: str
    field_path: str
    status: Literal["passed", "warning", "failed"]
    rule: str
    reason: str
    citation: dict[str, Any] | None = None


class IdentityMatchOut(ApiModel):
    field: str
    label: str
    kyc_value: Any | None = None
    aadhaar_value: Any | None = None
    pan_value: Any | None = None
    match_status: str
    confidence: float
    explanation: str
    pairs: list[dict[str, Any]] = Field(default_factory=list)
    not_applicable_sources: list[str] = Field(default_factory=list)
    missing_sources: list[str] = Field(default_factory=list)


class IdentityVerificationOut(ApiModel):
    subject: str
    status: str
    """not_verified | not_configured | verified | failed | consent_missing | provider_error"""
    configured: bool = False
    provider: str | None = None
    reason_code: str | None = None
    verified_at: datetime | None = None
    consent_given: bool | None = None


class IdentityIssueOut(ApiModel):
    code: str
    category: Literal[
        "mandatory_missing",
        "extraction_uncertainty",
        "data_mismatch",
        "verification_unavailable",
        "verification_failed",
        "invalid_format",
        "processing",
    ]
    severity: Literal["info", "warning", "error"]
    message: str
    subject: str | None = None
    field: str | None = None


class IdentityReviewOut(ApiModel):
    status: Literal["not_started", "completed", "stale"]
    decision: str | None = None
    rationale: str | None = None
    reviewer_subject: str | None = None
    reviewed_at: datetime | None = None
    resolved_fields: list[str] = Field(default_factory=list)


class IdentityStagesOut(BaseModel):
    """Distinct states. None implies any other."""

    document_uploaded: dict[str, str]
    information_extracted: dict[str, str]
    format_validated: dict[str, str]
    kyc_matched: str
    authenticity_verified: dict[str, str]
    human_review_completed: str


class IdentitySummaryOut(ApiModel):
    case_id: str
    fingerprint: str
    kyc_present: bool
    documents: list[IdentityDocumentOut]
    stages: IdentityStagesOut
    match_status: str
    matches: list[IdentityMatchOut]
    findings: list[IdentityFindingOut]
    verification: list[IdentityVerificationOut]
    review: IdentityReviewOut
    issues: list[IdentityIssueOut]


class IdentityMatchesOut(ApiModel):
    case_id: str
    fingerprint: str
    match_status: str
    matches: list[IdentityMatchOut]


class IdentityVerifyOut(ApiModel):
    reused_existing: list[str] = Field(default_factory=list)
    summary: IdentitySummaryOut
