from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from idp.audit import append_audit
from idp.auth import Principal
from idp.errors import AppError
from idp.models import Case, Document, UnderwritingDecision
from idp.schemas import (
    DecisionReadinessOut,
    UnderwritingDecisionHistoryOut,
    UnderwritingDecisionIn,
    UnderwritingDecisionOut,
)
from idp.services.workspace import build_workspace


def build_decision_history(
    session: Session,
    *,
    case: Case,
    principal: Principal,
) -> UnderwritingDecisionHistoryOut:
    workspace = build_workspace(
        session,
        tenant_id=case.tenant_id,
        external_case_id=case.external_case_id,
    )
    pending_critical_flags = sum(
        exception.status == "pending" and exception.severity == "error"
        for exception in workspace.case_review.exceptions
    )
    source_documents_complete = bool(workspace.documents) and all(
        document.status == "completed" for document in workspace.documents
    )
    evidence_review_complete = workspace.counts.pending == 0
    authority_available = principal.has_permission("underwriting_decision") and not case.is_demo
    readiness = DecisionReadinessOut(
        source_documents_total=len(workspace.documents),
        source_documents_complete=source_documents_complete,
        evidence_reviews_pending=workspace.counts.pending,
        evidence_review_complete=evidence_review_complete,
        pending_critical_flags=pending_critical_flags,
        outstanding_information_requests=None,
        information_requests_tracked=False,
        underwriting_guidelines_available=False,
        authority_available=authority_available,
        mandatory_prerequisites_met=(
            source_documents_complete
            and evidence_review_complete
            and pending_critical_flags == 0
            and authority_available
        ),
        underwriter_subject=principal.subject,
        demo_case=case.is_demo,
    )
    decisions = list(
        session.scalars(
            select(UnderwritingDecision)
            .where(
                UnderwritingDecision.tenant_id == case.tenant_id,
                UnderwritingDecision.case_id == case.id,
            )
            .order_by(UnderwritingDecision.decided_at.desc(), UnderwritingDecision.id.desc())
        )
    )
    case_summary = workspace.case
    if decisions:
        latest = decisions[0]
        case_summary = case_summary.model_copy(
            update={
                "final_decision": latest.decision,
                "decision_date": latest.decided_at,
                "underwriter_subject": latest.underwriter_subject,
                "decision_rationale": latest.decision_rationale,
            }
        )
    return UnderwritingDecisionHistoryOut(
        case=case_summary,
        readiness=readiness,
        decisions=[UnderwritingDecisionOut.model_validate(item) for item in decisions],
    )


def record_underwriting_decision(
    session: Session,
    *,
    case: Case,
    principal: Principal,
    payload: UnderwritingDecisionIn,
    correlation_id: str,
) -> UnderwritingDecision:
    history = build_decision_history(session, case=case, principal=principal)
    if not history.readiness.mandatory_prerequisites_met:
        raise AppError(
            409,
            "decision_prerequisites_not_met",
            "Decision cannot be recorded",
            "Complete source processing, evidence review, and underwriting authorization "
            "before submitting a final decision.",
        )

    evidence_ids = set(payload.supporting_document_ids)
    if evidence_ids:
        matching_ids = set(
            session.scalars(
                select(Document.id).where(
                    Document.id.in_(evidence_ids),
                    Document.tenant_id == case.tenant_id,
                    Document.case_id == case.id,
                )
            )
        )
        if matching_ids != evidence_ids:
            raise AppError(
                422,
                "invalid_decision_evidence",
                "Invalid supporting evidence",
                "Supporting evidence must belong to this case.",
            )

    rationale = {
        "approve": payload.decision_rationale,
        "decline": payload.decline_reason,
        "postpone": payload.postponement_reason,
        "refer": payload.referral_reason,
    }[payload.decision]
    decision = UnderwritingDecision(
        tenant_id=case.tenant_id,
        case_id=case.id,
        decision=payload.decision,
        approved_sum_assured=payload.approved_sum_assured,
        applicable_premium=payload.applicable_premium,
        decision_rationale=rationale or "",
        additional_terms=payload.additional_terms,
        decline_reason=payload.decline_reason,
        postponement_reason=payload.postponement_reason,
        additional_requirements=payload.additional_requirements,
        expected_reassessment_date=payload.expected_reassessment_date,
        referral_reason=payload.referral_reason,
        target_authority=payload.target_authority,
        decision_notes=payload.decision_notes,
        supporting_document_ids=payload.supporting_document_ids,
        authority_reference=payload.authority_reference,
        guideline_reference=payload.guideline_reference,
        authority_attested=payload.authority_attested,
        information_requests_acknowledged=payload.information_requests_acknowledged,
        underwriter_subject=principal.subject,
    )
    case.workflow_stage = "hilt_escalated" if payload.decision == "refer" else "resolved"
    session.add(decision)
    session.flush()
    append_audit(
        session,
        tenant_id=case.tenant_id,
        case_id=case.id,
        actor_subject=principal.subject,
        action="underwriting.decision_recorded",
        outcome="success",
        correlation_id=correlation_id,
        metadata={
            "decision": payload.decision,
            "decision_id": decision.id,
            "workflow_stage": case.workflow_stage,
        },
    )
    return decision
