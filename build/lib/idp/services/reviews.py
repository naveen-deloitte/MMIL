from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from idp.audit import append_audit
from idp.errors import AppError, StaleReviewError
from idp.extraction.engine import normalize_value
from idp.models import Document, EvidenceReview, ExtractedField, ProcessingJob
from idp.services.processing import transition

REVIEW_DECISIONS = {"accepted", "corrected", "rejected", "not_applicable"}
TERMINAL_REVIEW_STATES = REVIEW_DECISIONS


@dataclass(frozen=True)
class ReviewInput:
    field_id: str
    decision: str
    expected_version: int
    corrected_value: Any | None = None
    rationale: str | None = None


def review_fields(
    session: Session,
    *,
    document: Document,
    actor_subject: str,
    correlation_id: str,
    decisions: list[ReviewInput],
) -> list[EvidenceReview]:
    if not decisions:
        raise AppError(422, "empty_review", "Invalid review", "At least one field is required.")
    if len({decision.field_id for decision in decisions}) != len(decisions):
        raise AppError(
            422,
            "duplicate_review_field",
            "Invalid review",
            "A field can appear only once in a review request.",
        )

    reviews: list[EvidenceReview] = []
    for item in decisions:
        query = select(ExtractedField).where(
            ExtractedField.id == item.field_id,
            ExtractedField.document_id == document.id,
            ExtractedField.run_id == document.latest_run_id,
        )
        if session.bind and session.bind.dialect.name == "postgresql":
            query = query.with_for_update()
        field = session.scalar(query)
        if field is None:
            raise AppError(404, "field_not_found", "Field not found", "The field was not found.")
        if field.normalized_value_json is None:
            raise AppError(
                422,
                "field_not_reviewable",
                "Field cannot be reviewed",
                "Only extracted values can receive a review decision.",
            )
        if item.expected_version != field.review_version:
            raise StaleReviewError()
        if item.decision not in REVIEW_DECISIONS:
            raise AppError(
                422,
                "invalid_review_decision",
                "Invalid review",
                "The review decision is not supported.",
            )

        rationale = (item.rationale or "").strip()
        if len(rationale) > 2000:
            raise AppError(
                422,
                "rationale_too_long",
                "Invalid review",
                "The rationale exceeds the 2000 character limit.",
            )
        if item.decision in {"corrected", "rejected", "not_applicable"} and not rationale:
            raise AppError(
                422,
                "rationale_required",
                "Rationale required",
                "A rationale is required for this decision.",
            )

        prior = session.scalar(
            select(EvidenceReview)
            .where(EvidenceReview.field_id == field.id)
            .order_by(EvidenceReview.version.desc())
            .limit(1)
        )
        before_value = prior.after_value_json if prior is not None else field.normalized_value_json
        if item.decision == "corrected":
            if item.corrected_value is None or item.corrected_value == "":
                raise AppError(
                    422,
                    "corrected_value_required",
                    "Corrected value required",
                    "Enter the corrected value.",
                )
            try:
                after_value = _normalize_correction(field.data_type, item.corrected_value)
            except (TypeError, ValueError) as exc:
                raise AppError(
                    422,
                    "invalid_corrected_value",
                    "Invalid corrected value",
                    "The corrected value does not match the field type.",
                ) from exc
        elif item.decision == "accepted":
            after_value = before_value
        else:
            after_value = None

        new_version = field.review_version + 1
        review = EvidenceReview(
            field_id=field.id,
            document_id=document.id,
            case_id=document.case_id,
            version=new_version,
            decision=item.decision,
            rationale=rationale or None,
            before_value_json=before_value,
            after_value_json=after_value,
            reviewer_subject=actor_subject,
            correlation_id=correlation_id,
        )
        session.add(review)
        update_result = session.execute(
            update(ExtractedField)
            .where(
                ExtractedField.id == field.id,
                ExtractedField.review_version == item.expected_version,
            )
            .values(review_state=item.decision, review_version=new_version)
        )
        if update_result.rowcount != 1:
            raise StaleReviewError()
        field.review_state = item.decision
        field.review_version = new_version
        reviews.append(review)
        append_audit(
            session,
            tenant_id=document.tenant_id,
            case_id=document.case_id,
            document_id=document.id,
            run_id=field.run_id,
            field_id=field.id,
            actor_subject=actor_subject,
            action="evidence.reviewed",
            outcome="success",
            correlation_id=correlation_id,
            metadata={"decision": item.decision, "review_version": new_version},
        )

    session.flush()
    pending = session.scalar(
        select(ExtractedField.id)
        .where(
            ExtractedField.run_id == document.latest_run_id,
            ExtractedField.source_literal.is_not(None),
            ExtractedField.review_state.not_in(TERMINAL_REVIEW_STATES),
        )
        .limit(1)
    )
    if pending is None and document.status == "review_required":
        job = session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.document_id == document.id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        )
        if job is not None and job.status == "review_required":
            transition(job, document, "completed")
            append_audit(
                session,
                tenant_id=document.tenant_id,
                case_id=document.case_id,
                document_id=document.id,
                actor_subject=actor_subject,
                action="document.review_completed",
                outcome="success",
                correlation_id=correlation_id,
                metadata={"status": "completed"},
            )
    return reviews


def _normalize_correction(data_type: str, value: Any) -> Any:
    if data_type == "measurement_pair" and isinstance(value, dict):
        systolic = int(value["systolic"])
        diastolic = int(value["diastolic"])
        return {"systolic": systolic, "diastolic": diastolic}
    if data_type == "text":
        return normalize_value(data_type, str(value))
    if data_type == "boolean" and isinstance(value, bool):
        return value
    return normalize_value(data_type, str(value))
