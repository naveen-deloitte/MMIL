"""Identity verification workflow for a case: summary, matching, verification and review.

Keeps four things apart: format validation, cross-document matching, official authenticity
verification and human review. None of them implies another.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from idp.audit import append_audit
from idp.auth import Principal
from idp.config import Settings
from idp.errors import AppError
from idp.identity.aadhaar_verifier import (
    AadhaarVerificationRequest,
    AadhaarVerifier,
    build_aadhaar_verifier,
)
from idp.identity.identity_matcher import (
    MISMATCH,
    NOT_APPLICABLE,
    NOT_AVAILABLE,
    REVIEW_REQUIRED,
    SourceValue,
    match_identity,
    overall_match_status,
)
from idp.identity.pan_verifier import PanVerificationRequest, PanVerifier, build_pan_verifier
from idp.identity.schemas import (
    IdentityDocumentOut,
    IdentityFindingOut,
    IdentityIssueOut,
    IdentityMatchOut,
    IdentityReviewIn,
    IdentityReviewOut,
    IdentityStagesOut,
    IdentitySummaryOut,
    IdentityVerificationOut,
    IdentityVerifyIn,
)
from idp.identity.verification_types import (
    CONSENT_MISSING,
    FAILED,
    NOT_CONFIGURED,
    NOT_VERIFIED,
    VERIFIED,
    Consent,
    VerificationResult,
)
from idp.models import (
    Case,
    Document,
    IdentityMatchSnapshot,
    IdentityReview,
    IdentityVerification,
    ProcessingJob,
    utc_now,
)
from idp.schemas import FieldOut
from idp.services.workspace import _field_output

AADHAAR = "aadhaar"
PAN = "pan"
DOCUMENT_TYPES = {AADHAAR: "aadhaar_card", PAN: "pan_card"}
KYC_DOCUMENT_TYPE = "kyc_individual"
PROCESSING_STATES = {"uploaded", "scanning", "ocr", "extracting"}

ACTION_REQUIRED = {
    "ocr_unavailable": (
        "No OCR provider is configured, so this image could not be read. Set IDP_OCR_PROVIDER "
        "to an approved provider (rapidocr for local development, textract where approved) "
        "and retry the document."
    ),
    "ocr_adapter_not_installed": (
        "The configured OCR adapter is not installed. Install the 'ocr' extra and retry."
    ),
    "ocr_failed": "OCR failed on this document. Retry, or upload a clearer scan.",
    "encrypted_document": "The PDF is password protected. Upload an unprotected copy.",
}

# Field paths that carry each comparison on each identity document.
_FIELD_MAP = {
    "full_name": "identity.full_name",
    "date_of_birth": "identity.date_of_birth",
    "gender": "identity.gender",
    "address": "identity.address",
}
FORMAT_ERROR_CODES = frozenset(
    {
        "aadhaar_format_invalid",
        "aadhaar_checksum_invalid",
        "pan_format_invalid",
        "date_invalid",
        "date_in_future",
        "year_invalid",
        "year_implausible",
        "dob_year_inconsistent",
    }
)
ROUTING_MARKER = "identity_cross_document_mismatch"
VERIFICATION_FAILED_MARKER = "identity_verification_failed"


@dataclass
class _Doc:
    subject: str
    document: Document | None
    fields: dict[str, FieldOut]


def _case_documents(session: Session, case: Case, tenant_id: str, document_type: str) -> Document | None:
    documents = list(
        session.scalars(
            select(Document)
            .where(
                Document.case_id == case.id,
                Document.tenant_id == tenant_id,
                Document.document_type == document_type,
            )
            .order_by(Document.created_at.desc())
        )
    )
    # Prefer the newest document that has extraction results.
    for candidate in documents:
        if candidate.latest_run_id:
            return candidate
    return documents[0] if documents else None


def _load_fields(session: Session, document: Document | None) -> dict[str, FieldOut]:
    if document is None or not document.latest_run_id:
        return {}
    from idp.models import ExtractedField

    rows = session.scalars(
        select(ExtractedField).where(ExtractedField.run_id == document.latest_run_id)
    )
    return {row.field_path: _field_output(session, row) for row in rows}


def _usable(field: FieldOut | None) -> Any | None:
    """Effective value, excluding fields a person rejected or marked not applicable."""
    if field is None or field.review_state in {"rejected", "not_applicable"}:
        return None
    return field.effective_value


def _uncertain(field: FieldOut | None) -> bool:
    return bool(
        field
        and field.extraction_status == "uncertain"
        and field.review_state not in {"accepted", "corrected"}
    )


def _source_value(fields: dict[str, FieldOut], path: str) -> SourceValue:
    field = fields.get(path)
    return SourceValue(value=_usable(field), uncertain=_uncertain(field))


def _kyc_sources(fields: dict[str, FieldOut]) -> dict[str, SourceValue]:
    parts = [fields.get(p) for p in ("identity.first_name", "identity.other_names", "identity.surname")]
    name = " ".join(str(_usable(p)) for p in parts if p is not None and _usable(p))
    return {
        "full_name": SourceValue(value=name or None, uncertain=any(_uncertain(p) for p in parts)),
        "date_of_birth": _source_value(fields, "identity.date_of_birth"),
        "gender": _source_value(fields, "identity.gender"),
        "address": _source_value(fields, "contact.residential_address"),
    }


def _identity_sources(subject: str, fields: dict[str, FieldOut]) -> dict[str, SourceValue]:
    sources = {
        "full_name": _source_value(fields, "identity.full_name"),
        "date_of_birth": _source_value(fields, "identity.date_of_birth"),
    }
    if subject == AADHAAR:
        year = _usable(fields.get("identity.year_of_birth"))
        dob = sources["date_of_birth"]
        sources["date_of_birth"] = SourceValue(
            value=dob.value,
            uncertain=dob.uncertain,
            year_of_birth=int(year) if isinstance(year, int) else None,
        )
        sources["gender"] = _source_value(fields, "identity.gender")
        sources["address"] = _source_value(fields, "identity.address")
    else:
        sources["pan_number"] = _source_value(fields, "identity.pan_number")
    return sources


def _document_state(document: Document | None) -> str:
    if document is None:
        return "not_uploaded"
    if document.status in PROCESSING_STATES:
        return "processing"
    if document.status in {"failed", "cancelled"}:
        return "failed"
    return "extracted" if document.latest_run_id else "processing"


def _document_out(subject: str, document: Document | None, fields: dict[str, FieldOut]) -> IdentityDocumentOut:
    values = [f for f in fields.values() if f.confidence is not None and f.effective_value is not None]
    confidence = (
        round(sum(f.confidence for f in values if f.confidence is not None) / len(values), 2)
        if values
        else None
    )
    code = document.failure_code if document else None
    return IdentityDocumentOut(
        subject=subject,
        state=_document_state(document),
        document_id=document.id if document else None,
        filename=document.safe_filename if document else None,
        document_status=document.status if document else None,
        failure_code=code,
        action_required=ACTION_REQUIRED.get(code) if code else None,
        extraction_confidence=confidence,
        fields=sorted(fields.values(), key=lambda f: (f.ui_group, f.label)),
    )


_FINDING_STATUS = {"info": "passed", "advisory": "warning", "warning": "warning", "error": "failed"}


def _findings(subject: str, fields: dict[str, FieldOut]) -> list[IdentityFindingOut]:
    results: list[IdentityFindingOut] = []
    for path, field in sorted(fields.items()):
        citation = field.citations[0].model_dump() if field.citations else None
        for item in field.validations:
            if item.code in {"auto_accepted", "medium_confidence", "recommended_field_missing"}:
                continue
            extra = item.model_dump()
            results.append(
                IdentityFindingOut(
                    subject=subject,
                    field_path=path,
                    status=_FINDING_STATUS.get(item.severity, "warning"),
                    rule=str(extra.get("rule") or item.code),
                    reason=str(item.message or item.code),
                    citation=citation,
                )
            )
        if field.extraction_status == "uncertain":
            results.append(
                IdentityFindingOut(
                    subject=subject,
                    field_path=path,
                    status="warning",
                    rule="extraction_certainty",
                    reason="The value was read with uncertainty or conflicting readings.",
                    citation=citation,
                )
            )
    return results


def _format_state(subject: str, fields: dict[str, FieldOut]) -> str:
    if not fields:
        return "not_available"
    number = fields.get("identity.aadhaar_number" if subject == AADHAAR else "identity.pan_number")
    if number is None or number.effective_value is None:
        return "not_available"
    failed = [
        f
        for f in fields.values()
        if any(v.code in FORMAT_ERROR_CODES for v in f.validations)
        and f.review_state not in {"accepted", "corrected"}
    ]
    return "failed" if failed else "passed"


def _latest_verification(
    session: Session, case: Case, tenant_id: str, subject: str
) -> IdentityVerification | None:
    return session.scalar(
        select(IdentityVerification)
        .where(
            IdentityVerification.case_id == case.id,
            IdentityVerification.tenant_id == tenant_id,
            IdentityVerification.subject == subject,
        )
        .order_by(IdentityVerification.created_at.desc(), IdentityVerification.id.desc())
        .limit(1)
    )


def _verification_out(
    subject: str, record: IdentityVerification | None, settings: Settings
) -> IdentityVerificationOut:
    provider = (
        settings.identity_aadhaar_provider if subject == AADHAAR else settings.identity_pan_provider
    )
    configured = provider != "not_configured"
    if record is None:
        return IdentityVerificationOut(subject=subject, status=NOT_VERIFIED, configured=configured)
    return IdentityVerificationOut(
        subject=subject,
        status=record.status,
        configured=configured,
        provider=record.provider,
        reason_code=record.reason_code,
        verified_at=record.verified_at,
        consent_given=record.consent_given,
    )


def _fingerprint(
    docs: dict[str, _Doc], matches: list[dict[str, Any]], verifications: dict[str, str]
) -> str:
    payload = {
        "documents": {
            s: [d.document.id, d.document.version, d.document.latest_run_id] if d.document else None
            for s, d in docs.items()
        },
        "matches": [
            [m["field"], m["match_status"], m["kyc_value"], m["aadhaar_value"], m["pan_value"]]
            for m in matches
        ],
        "verification": verifications,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _issues(
    docs: dict[str, _Doc],
    findings: list[IdentityFindingOut],
    matches: list[dict[str, Any]],
    verification: list[IdentityVerificationOut],
    kyc_present: bool,
) -> list[IdentityIssueOut]:
    issues: list[IdentityIssueOut] = []
    for subject, doc in docs.items():
        state = _document_state(doc.document)
        name = subject.capitalize() if subject == AADHAAR else "PAN"
        if state == "not_uploaded":
            issues.append(
                IdentityIssueOut(
                    code="document_missing",
                    category="mandatory_missing",
                    severity="info",
                    message=f"No {name} document has been uploaded.",
                    subject=subject,
                )
            )
        elif state == "failed":
            code = doc.document.failure_code if doc.document else None
            issues.append(
                IdentityIssueOut(
                    code=code or "processing_failed",
                    category="processing",
                    severity="error",
                    message=ACTION_REQUIRED.get(code or "", f"The {name} document failed processing."),
                    subject=subject,
                )
            )
        elif state == "processing":
            issues.append(
                IdentityIssueOut(
                    code="processing",
                    category="processing",
                    severity="info",
                    message=f"The {name} document is still being processed.",
                    subject=subject,
                )
            )
    for item in findings:
        if item.status == "passed":
            continue
        if item.rule == "extraction_certainty":
            category = "extraction_uncertainty"
        elif item.status == "failed":
            category = "invalid_format"
        else:
            category = "mandatory_missing"
        issues.append(
            IdentityIssueOut(
                code=item.rule,
                category=category,  # type: ignore[arg-type]
                severity="error" if item.status == "failed" else "warning",
                message=item.reason,
                subject=item.subject,
                field=item.field_path,
            )
        )
    for row in matches:
        if row["match_status"] == MISMATCH:
            issues.append(
                IdentityIssueOut(
                    code="cross_document_mismatch",
                    category="data_mismatch",
                    severity="error",
                    message=f"{row['label']}: {row['explanation']}",
                    field=row["field"],
                )
            )
        elif row["match_status"] == REVIEW_REQUIRED:
            issues.append(
                IdentityIssueOut(
                    code="cross_document_review_required",
                    category="extraction_uncertainty",
                    severity="warning",
                    message=f"{row['label']}: {row['explanation']}",
                    field=row["field"],
                )
            )
    if not kyc_present:
        issues.append(
            IdentityIssueOut(
                code="kyc_missing",
                category="mandatory_missing",
                severity="info",
                message="No Individual KYC document is available to compare against.",
            )
        )
    for item in verification:
        if item.status == FAILED:
            issues.append(
                IdentityIssueOut(
                    code="verification_failed",
                    category="verification_failed",
                    severity="error",
                    message=f"Official {item.subject} verification failed.",
                    subject=item.subject,
                )
            )
        elif item.status in {NOT_CONFIGURED, NOT_VERIFIED, CONSENT_MISSING, "provider_error"}:
            issues.append(
                IdentityIssueOut(
                    code=f"verification_{item.status}",
                    category="verification_unavailable",
                    severity="info",
                    message=f"Official {item.subject} verification has not been completed.",
                    subject=item.subject,
                )
            )
    return issues


def _review_state(
    session: Session, case: Case, tenant_id: str, fingerprint: str
) -> tuple[IdentityReviewOut, IdentityReview | None]:
    latest = session.scalar(
        select(IdentityReview)
        .where(IdentityReview.case_id == case.id, IdentityReview.tenant_id == tenant_id)
        .order_by(IdentityReview.reviewed_at.desc(), IdentityReview.id.desc())
        .limit(1)
    )
    if latest is None:
        return IdentityReviewOut(status="not_started"), None
    return (
        IdentityReviewOut(
            status="completed" if latest.fingerprint == fingerprint else "stale",
            decision=latest.decision,
            rationale=latest.rationale,
            reviewer_subject=latest.reviewer_subject,
            reviewed_at=latest.reviewed_at,
            resolved_fields=list(latest.resolved_fields_json or []),
        ),
        latest,
    )


def build_identity_summary(
    session: Session, *, case: Case, tenant_id: str, settings: Settings
) -> IdentitySummaryOut:
    kyc_document = _case_documents(session, case, tenant_id, KYC_DOCUMENT_TYPE)
    kyc_fields = _load_fields(session, kyc_document)
    docs: dict[str, _Doc] = {}
    for subject, document_type in DOCUMENT_TYPES.items():
        document = _case_documents(session, case, tenant_id, document_type)
        docs[subject] = _Doc(subject, document, _load_fields(session, document))

    sources = {
        "kyc": _kyc_sources(kyc_fields),
        AADHAAR: _identity_sources(AADHAAR, docs[AADHAAR].fields),
        PAN: _identity_sources(PAN, docs[PAN].fields),
    }
    present = {
        "kyc": bool(kyc_fields),
        AADHAAR: bool(docs[AADHAAR].fields),
        PAN: bool(docs[PAN].fields),
    }
    rows = match_identity(sources, documents_present=present)
    match_status = overall_match_status(rows)

    findings: list[IdentityFindingOut] = []
    for subject, doc in docs.items():
        findings.extend(_findings(subject, doc.fields))
    verification = [
        _verification_out(
            subject, _latest_verification(session, case, tenant_id, subject), settings
        )
        for subject in (AADHAAR, PAN)
    ]
    fingerprint = _fingerprint(docs, rows, {v.subject: v.status for v in verification})
    review, _ = _review_state(session, case, tenant_id, fingerprint)

    comparable = any(
        r["match_status"] not in {NOT_AVAILABLE, NOT_APPLICABLE} for r in rows
    )
    stages = IdentityStagesOut(
        document_uploaded={
            s: "uploaded" if d.document else "not_uploaded" for s, d in docs.items()
        },
        information_extracted={s: _document_state(d.document) for s, d in docs.items()},
        format_validated={s: _format_state(s, d.fields) for s, d in docs.items()},
        kyc_matched=match_status if comparable else NOT_AVAILABLE,
        authenticity_verified={v.subject: v.status for v in verification},
        human_review_completed=review.status,
    )
    return IdentitySummaryOut(
        case_id=case.external_case_id,
        fingerprint=fingerprint,
        kyc_present=present["kyc"],
        documents=[_document_out(s, d.document, d.fields) for s, d in docs.items()],
        stages=stages,
        match_status=match_status,
        matches=[IdentityMatchOut(**row) for row in rows],
        findings=findings,
        verification=verification,
        review=review,
        issues=_issues(docs, findings, rows, verification, present["kyc"]),
    )


def _persist_snapshot(
    session: Session, *, case: Case, tenant_id: str, actor: str, summary: IdentitySummaryOut
) -> IdentityMatchSnapshot:
    existing = session.scalar(
        select(IdentityMatchSnapshot).where(
            IdentityMatchSnapshot.case_id == case.id,
            IdentityMatchSnapshot.fingerprint == summary.fingerprint,
        )
    )
    if existing is not None:
        return existing
    snapshot = IdentityMatchSnapshot(
        tenant_id=tenant_id,
        case_id=case.id,
        fingerprint=summary.fingerprint,
        overall_status=summary.match_status,
        matches_json=[m.model_dump(mode="json") for m in summary.matches],
        findings_json=[
            {k: v for k, v in f.model_dump(mode="json").items() if k != "citation"}
            for f in summary.findings
        ],
        created_by=actor,
    )
    session.add(snapshot)
    session.flush()
    return snapshot


def route_identity_exceptions(
    session: Session,
    *,
    case: Case,
    tenant_id: str,
    actor: str,
    correlation_id: str,
    summary: IdentitySummaryOut,
) -> int:
    """Send applicable identity exceptions to the existing HILT queue.

    Only actual mismatches and confirmed verification failures route. Missing documents,
    uncertainty and an unconfigured provider do not. Fields a person already decided on are left
    alone, and KYC values are never modified.
    """
    targets: dict[tuple[str, str], str] = {}
    for row in summary.matches:
        if row.match_status != MISMATCH or row.field not in _FIELD_MAP:
            continue
        for pair in row.pairs:
            if pair["status"] != MISMATCH:
                continue
            for source in (pair["left"], pair["right"]):
                if source in (AADHAAR, PAN) and not (source == PAN and row.field in {"gender", "address"}):
                    targets[(source, _FIELD_MAP[row.field])] = ROUTING_MARKER
    for item in summary.verification:
        if item.status == FAILED:
            path = "identity.aadhaar_number" if item.subject == AADHAAR else "identity.pan_number"
            targets[(item.subject, path)] = VERIFICATION_FAILED_MARKER

    routed = 0
    from idp.models import ExtractedField

    for (subject, path), marker in targets.items():
        document = _case_documents(session, case, tenant_id, DOCUMENT_TYPES[subject])
        if document is None or not document.latest_run_id:
            continue
        field = session.scalar(
            select(ExtractedField).where(
                ExtractedField.run_id == document.latest_run_id, ExtractedField.field_path == path
            )
        )
        if field is None or field.normalized_value_json is None:
            continue
        if field.review_state != "accepted" or field.review_version != 0:
            continue
        if any(v.get("code") == marker for v in field.validation_json):
            continue
        message = (
            "Value conflicts with another identity document. Review and resolve it."
            if marker == ROUTING_MARKER
            else "Official verification reported a failure. Review the document."
        )
        field.validation_json = [
            *field.validation_json,
            {"code": marker, "severity": "error", "rule": "identity_exception", "message": message},
        ]
        field.review_state = "pending"
        if document.status == "completed":
            document.status = "review_required"
            job = session.scalar(
                select(ProcessingJob)
                .where(ProcessingJob.document_id == document.id)
                .order_by(ProcessingJob.created_at.desc())
                .limit(1)
            )
            if job is not None:
                job.status = "review_required"
        append_audit(
            session,
            tenant_id=tenant_id,
            case_id=case.id,
            document_id=document.id,
            field_id=field.id,
            actor_subject=actor,
            action="identity.exception_routed",
            outcome="pending_review",
            correlation_id=correlation_id,
            metadata={"subject": subject, "reason": marker},
        )
        routed += 1
    return routed


def _fingerprint_request(subject: str, document: Document, provider: str, masked: str | None, consent: bool) -> str:
    raw = json.dumps(
        [subject, document.id, document.version, provider, masked, consent], sort_keys=True
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def verify_identity(
    session: Session,
    *,
    case: Case,
    principal: Principal,
    settings: Settings,
    payload: IdentityVerifyIn,
    correlation_id: str,
    aadhaar_verifier: AadhaarVerifier | None = None,
    pan_verifier: PanVerifier | None = None,
) -> tuple[IdentitySummaryOut, list[str]]:
    """Run official verification where configured, persist outcomes, refresh matching."""
    tenant_id = principal.tenant_id
    aadhaar_verifier = aadhaar_verifier or build_aadhaar_verifier(settings)
    pan_verifier = pan_verifier or build_pan_verifier(settings)
    consent = Consent(
        given=payload.consent.given,
        purpose=payload.consent.purpose,
        captured_by=principal.subject,
    )
    reused: list[str] = []
    for subject in dict.fromkeys(payload.subjects):
        document = _case_documents(session, case, tenant_id, DOCUMENT_TYPES[subject])
        if document is None or not document.latest_run_id:
            continue
        fields = _load_fields(session, document)
        verifier = aadhaar_verifier if subject == AADHAAR else pan_verifier
        number_path = "identity.aadhaar_number" if subject == AADHAAR else "identity.pan_number"
        masked = fields[number_path].effective_value if number_path in fields else None

        if subject == PAN and payload.pan_number and masked:
            if str(masked)[-4:] != payload.pan_number[-4:]:
                raise AppError(
                    422,
                    "pan_does_not_match_document",
                    "PAN does not match the document",
                    "The supplied PAN does not match the extracted document.",
                )

        fingerprint = _fingerprint_request(
            subject, document, verifier.name, str(masked) if masked else None, consent.given
        )
        existing = session.scalar(
            select(IdentityVerification).where(
                IdentityVerification.case_id == case.id,
                IdentityVerification.tenant_id == tenant_id,
                IdentityVerification.request_fingerprint == fingerprint,
                IdentityVerification.status.in_([VERIFIED, FAILED, NOT_CONFIGURED]),
            )
        )
        if existing is not None:
            reused.append(subject)
            continue

        if verifier.name != "not_configured" and not consent.given:
            result = VerificationResult(
                status=CONSENT_MISSING, provider=verifier.name, reason_code="consent_missing"
            )
        elif subject == AADHAAR:
            qr = base64.b64decode(payload.qr_payload_base64) if payload.qr_payload_base64 else None
            result = verifier.verify(AadhaarVerificationRequest(qr_payload=qr, consent=consent))  # type: ignore[arg-type]
        else:
            if verifier.name != "not_configured" and not payload.pan_number:
                raise AppError(
                    422,
                    "pan_number_required",
                    "PAN required",
                    "The PAN must be supplied from the original document for official verification.",
                )
            dob = fields.get("identity.date_of_birth")
            name = fields.get("identity.full_name")
            result = verifier.verify(  # type: ignore[arg-type]
                PanVerificationRequest(
                    pan_number=payload.pan_number or "",
                    consent=consent,
                    name=str(name.effective_value) if name and name.effective_value else None,
                    date_of_birth=str(dob.effective_value) if dob and dob.effective_value else None,
                )
            )

        session.add(
            IdentityVerification(
                tenant_id=tenant_id,
                case_id=case.id,
                document_id=document.id,
                subject=subject,
                status=result.status,
                provider=result.provider,
                reason_code=result.reason_code,
                masked_identifier=str(masked) if masked else None,
                request_fingerprint=fingerprint,
                consent_given=consent.given,
                consent_purpose=consent.purpose or None,
                consent_recorded_by=principal.subject if consent.given else None,
                attempts=result.attempts,
                result_json=dict(result.details),
                verified_at=result.verified_at,
                created_by=principal.subject,
                correlation_id=correlation_id,
            )
        )
        session.flush()
        append_audit(
            session,
            tenant_id=tenant_id,
            case_id=case.id,
            document_id=document.id,
            actor_subject=principal.subject,
            action="identity.verification_attempted",
            outcome=result.status,
            correlation_id=correlation_id,
            metadata={
                "subject": subject,
                "verification_status": result.status,
                "provider": result.provider,
                "reason": result.reason_code,
                "consent_given": consent.given,
            },
        )

    summary = build_identity_summary(session, case=case, tenant_id=tenant_id, settings=settings)
    _persist_snapshot(session, case=case, tenant_id=tenant_id, actor=principal.subject, summary=summary)
    routed = route_identity_exceptions(
        session,
        case=case,
        tenant_id=tenant_id,
        actor=principal.subject,
        correlation_id=correlation_id,
        summary=summary,
    )
    if routed:
        summary = build_identity_summary(session, case=case, tenant_id=tenant_id, settings=settings)
    append_audit(
        session,
        tenant_id=tenant_id,
        case_id=case.id,
        actor_subject=principal.subject,
        action="identity.matching_refreshed",
        outcome="success",
        correlation_id=correlation_id,
        metadata={
            "match_status": summary.match_status,
            "mismatch_count": sum(m.match_status == MISMATCH for m in summary.matches),
        },
    )
    return summary, reused


def record_identity_review(
    session: Session,
    *,
    case: Case,
    principal: Principal,
    settings: Settings,
    payload: IdentityReviewIn,
    correlation_id: str,
) -> IdentitySummaryOut:
    summary = build_identity_summary(
        session, case=case, tenant_id=principal.tenant_id, settings=settings
    )
    if not any(d.state == "extracted" for d in summary.documents):
        raise AppError(
            409,
            "identity_not_ready",
            "Nothing to review",
            "Upload and process an Aadhaar or PAN document before recording a review.",
        )
    mismatched = [m.field for m in summary.matches if m.match_status == MISMATCH]
    if payload.decision != "confirmed" and not payload.rationale:
        raise AppError(
            422,
            "rationale_required",
            "Rationale required",
            "A rationale is required unless the identity is confirmed.",
        )
    if payload.decision == "confirmed" and mismatched:
        missing = [f for f in mismatched if f not in payload.resolved_fields]
        if missing or not payload.rationale:
            raise AppError(
                422,
                "mismatch_resolution_required",
                "Mismatches must be resolved",
                "Confirming an identity with mismatches needs a rationale and every "
                "mismatched field listed as resolved.",
            )
    unknown = set(payload.resolved_fields) - {m.field for m in summary.matches}
    if unknown:
        raise AppError(
            422, "unknown_field", "Unknown field", "A resolved field is not part of the comparison."
        )

    snapshot = _persist_snapshot(
        session, case=case, tenant_id=principal.tenant_id, actor=principal.subject, summary=summary
    )
    session.add(
        IdentityReview(
            tenant_id=principal.tenant_id,
            case_id=case.id,
            fingerprint=summary.fingerprint,
            decision=payload.decision,
            rationale=payload.rationale,
            resolved_fields_json=list(payload.resolved_fields),
            mismatches_json=[
                m.model_dump(mode="json") for m in summary.matches if m.match_status == MISMATCH
            ],
            reviewer_subject=principal.subject,
            reviewed_at=utc_now(),
            correlation_id=correlation_id,
        )
    )
    append_audit(
        session,
        tenant_id=principal.tenant_id,
        case_id=case.id,
        actor_subject=principal.subject,
        action="identity.reviewed",
        outcome=payload.decision,
        correlation_id=correlation_id,
        metadata={
            "decision": payload.decision,
            "mismatch_count": len(mismatched),
            "match_status": summary.match_status,
            "decision_id": snapshot.id,
        },
    )
    session.flush()
    return build_identity_summary(
        session, case=case, tenant_id=principal.tenant_id, settings=settings
    )
