from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from idp.audit import append_audit
from idp.auth import Principal
from idp.errors import AppError, ProcessingError
from idp.models import (
    Case,
    Document,
    UnderwritingDecision,
    UnderwritingVariance,
    UnderwritingVarianceDecision,
)
from idp.schemas import (
    AuditPage,
    CaseCreateIn,
    CaseListItem,
    CaseSummary,
    DocumentDeletionOut,
    DocumentSummary,
    EvidenceOut,
    ExtractionHistoryOut,
    ExtractionOut,
    HealthOut,
    ReviewRequest,
    ReviewResponse,
    UnderwritingDecisionHistoryOut,
    UnderwritingDecisionIn,
    UnderwritingVarianceDecisionIn,
    UnderwritingVarianceOut,
    UnderwritingVarianceWorkspaceOut,
    UploadOut,
    WorkspaceOut,
)
from idp.identity.schemas import (
    IdentityMatchesOut,
    IdentityReviewIn,
    IdentitySummaryOut,
    IdentityVerifyIn,
    IdentityVerifyOut,
)
from idp.identity.service import (
    build_identity_summary,
    record_identity_review,
    verify_identity,
)
from idp.services.ingestion import find_case, ingest_document
from idp.services.processing import retry_document
from idp.services.reviews import ReviewInput, review_fields
from idp.services.underwriting_decisions import (
    build_decision_history,
    record_underwriting_decision,
)
from idp.services.workspace import (
    audit_page,
    build_workspace,
    document_summary,
    extraction_history,
    latest_extraction,
)

router = APIRouter(prefix="/api/v1")


def get_session(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.database.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_principal(request: Request) -> Principal:
    return request.app.state.authenticator.authenticate(request)


def get_document(session: Session, *, principal: Principal, document_id: str) -> Document:
    query = (
        select(Document)
        .join(Case, Case.id == Document.case_id)
        .where(
            Document.id == document_id,
            Document.tenant_id == principal.tenant_id,
        )
    )
    if "*" not in principal.case_ids:
        case_access = [Case.external_case_id.in_(principal.case_ids)]
        if principal.is_demo:
            case_access.append(Case.created_by == principal.subject)
        query = query.where(or_(*case_access))
    document = session.scalar(query)
    if document is None:
        raise AppError(
            404, "document_not_found", "Document not found", "The document was not found."
        )
    return document


def require_case_access(session: Session, *, principal: Principal, external_case_id: str) -> Case:
    case = find_case(session, tenant_id=principal.tenant_id, external_case_id=external_case_id)
    if case.is_demo:
        if principal.is_demo:
            return case
        raise AppError(404, "case_not_found", "Case not found", "The case was not found.")
    if principal.is_demo and case.created_by == principal.subject:
        return case
    principal.require_case(external_case_id)
    return case


def get_case_variance(
    session: Session,
    *,
    case: Case,
    tenant_id: str,
    variance_id: str,
) -> UnderwritingVariance:
    variance = session.scalar(
        select(UnderwritingVariance).where(
            UnderwritingVariance.id == variance_id,
            UnderwritingVariance.case_id == case.id,
            UnderwritingVariance.tenant_id == tenant_id,
        )
    )
    if variance is None:
        raise AppError(
            404,
            "underwriting_variance_not_found",
            "Variance not found",
            "The underwriting variance was not found.",
        )
    return variance


def build_variance_workspace(
    session: Session,
    *,
    case: Case,
    tenant_id: str,
) -> UnderwritingVarianceWorkspaceOut:
    variances = list(
        session.scalars(
            select(UnderwritingVariance)
            .where(
                UnderwritingVariance.case_id == case.id,
                UnderwritingVariance.tenant_id == tenant_id,
            )
            .order_by(UnderwritingVariance.created_at, UnderwritingVariance.id)
        )
    )
    result: list[UnderwritingVarianceOut] = []
    for variance in variances:
        history = list(
            session.scalars(
                select(UnderwritingVarianceDecision)
                .where(
                    UnderwritingVarianceDecision.variance_id == variance.id,
                    UnderwritingVarianceDecision.tenant_id == tenant_id,
                )
                .order_by(
                    UnderwritingVarianceDecision.reviewed_at,
                    UnderwritingVarianceDecision.id,
                )
            )
        )
        current = next((decision for decision in history if decision.is_current), None)
        status = (
            "pending"
            if current is None
            else "referred"
            if current.decision == "refer"
            else "resolved"
        )
        result.append(
            UnderwritingVarianceOut(
                id=variance.id,
                category=variance.category,
                title=variance.title,
                applied_value=variance.applied_value,
                suggested_value=variance.suggested_value,
                difference=variance.suggested_value - variance.applied_value,
                currency=variance.currency,
                recommendation_source=variance.recommendation_source,
                recommendation_rationale=variance.recommendation_rationale,
                status=status,
                current_decision=current,
                history=history,
            )
        )

    pending_count = sum(item.status == "pending" for item in result)
    resolved_count = sum(item.status == "resolved" for item in result)
    requires_decision = any(item.status in {"pending", "referred"} for item in result)
    return UnderwritingVarianceWorkspaceOut(
        case=CaseSummary.model_validate(case),
        demo_mode=case.is_demo,
        variances=result,
        pending_variances=pending_count,
        resolved_variances=resolved_count,
        total_variances=len(result),
        cases_requiring_decision=int(requires_decision),
    )


@router.get("/health/live", response_model=HealthOut, tags=["health"])
def live() -> HealthOut:
    return HealthOut(status="ok")


@router.get("/health/ready", response_model=HealthOut, tags=["health"])
def ready(request: Request, session: Session = Depends(get_session)) -> HealthOut:
    del request
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise AppError(
            503, "dependency_unavailable", "Not ready", "A required dependency is unavailable."
        ) from exc
    return HealthOut(status="ready")


@router.get("/cases", response_model=list[CaseListItem], tags=["cases"])
def list_cases(
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> list[CaseListItem]:
    principal.require("view")
    query = (
        select(Case, func.count(Document.id), func.max(Document.updated_at))
        .outerjoin(Document, Document.case_id == Case.id)
        .where(Case.tenant_id == principal.tenant_id, Case.is_demo.is_(False))
        .group_by(Case.id)
    )
    if "*" not in principal.case_ids:
        case_access = [Case.external_case_id.in_(principal.case_ids)]
        if principal.is_demo:
            case_access.append(Case.created_by == principal.subject)
        query = query.where(or_(*case_access))
    rows = session.execute(query.order_by(Case.updated_at.desc())).all()
    latest_decisions: dict[str, UnderwritingDecision] = {}
    case_ids = [case.id for case, _, _ in rows]
    if case_ids:
        for decision in session.scalars(
            select(UnderwritingDecision)
            .where(
                UnderwritingDecision.tenant_id == principal.tenant_id,
                UnderwritingDecision.case_id.in_(case_ids),
            )
            .order_by(UnderwritingDecision.decided_at.desc(), UnderwritingDecision.id.desc())
        ):
            latest_decisions.setdefault(decision.case_id, decision)
    case_summaries: dict[str, CaseSummary] = {}
    for case, _, _ in rows:
        summary = CaseSummary.model_validate(case)
        decision = latest_decisions.get(case.id)
        if decision is not None:
            summary = summary.model_copy(
                update={
                    "final_decision": decision.decision,
                    "decision_date": decision.decided_at,
                    "underwriter_subject": decision.underwriter_subject,
                    "decision_rationale": decision.decision_rationale,
                }
            )
        case_summaries[case.id] = summary
    return [
        CaseListItem(
            case=case_summaries[case.id],
            document_count=document_count,
            last_activity_at=last_document_update or case.updated_at,
        )
        for case, document_count, last_document_update in rows
    ]


@router.post("/cases", response_model=CaseSummary, status_code=201, tags=["cases"])
def create_case(
    request: Request,
    payload: CaseCreateIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> CaseSummary:
    principal.require("upload")
    if not principal.is_demo and "*" not in principal.case_ids:
        raise AppError(
            403,
            "case_creation_requires_tenant_scope",
            "Case creation unavailable",
            "Case creation requires tenant-wide case scope.",
        )
    existing = session.scalar(
        select(Case).where(
            Case.tenant_id == principal.tenant_id,
            Case.external_case_id == payload.external_case_id,
        )
    )
    if existing is not None:
        raise AppError(
            409,
            "case_id_conflict",
            "Case already exists",
            "A case with this identifier already exists.",
        )
    case = Case(
        tenant_id=principal.tenant_id,
        external_case_id=payload.external_case_id,
        applicant_display_name=payload.applicant_display_name,
        proposal_number=payload.proposal_number,
        product_name=payload.product_name,
        created_by=principal.subject,
        is_demo=False,
        workflow_stage=payload.workflow_stage,
        sla_label=payload.sla_label,
    )
    session.add(case)
    session.flush()
    append_audit(
        session,
        tenant_id=case.tenant_id,
        case_id=case.id,
        actor_subject=principal.subject,
        action="case.created",
        outcome="success",
        correlation_id=request.state.correlation_id,
        metadata={"status": "created"},
    )
    return CaseSummary.model_validate(case)


@router.get("/cases/{case_id}/workspace", response_model=WorkspaceOut, tags=["medical evidence"])
def workspace(
    case_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> WorkspaceOut:
    principal.require("view")
    require_case_access(session, principal=principal, external_case_id=case_id)
    return build_workspace(session, tenant_id=principal.tenant_id, external_case_id=case_id)


@router.get(
    "/cases/{case_id}/underwriting-variances",
    response_model=UnderwritingVarianceWorkspaceOut,
    tags=["underwriting"],
)
def underwriting_variances(
    case_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> UnderwritingVarianceWorkspaceOut:
    principal.require("view")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    return build_variance_workspace(session, case=case, tenant_id=principal.tenant_id)


@router.get(
    "/cases/{case_id}/underwriting-decisions",
    response_model=UnderwritingDecisionHistoryOut,
    tags=["underwriting"],
)
def underwriting_decision_history(
    case_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> UnderwritingDecisionHistoryOut:
    principal.require("view")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    return build_decision_history(session, case=case, principal=principal)


@router.post(
    "/cases/{case_id}/underwriting-decisions",
    response_model=UnderwritingDecisionHistoryOut,
    tags=["underwriting"],
)
def submit_underwriting_decision(
    request: Request,
    case_id: str,
    payload: UnderwritingDecisionIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> UnderwritingDecisionHistoryOut:
    principal.require("underwriting_decision")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    record_underwriting_decision(
        session,
        case=case,
        principal=principal,
        payload=payload,
        correlation_id=request.state.correlation_id,
    )
    return build_decision_history(session, case=case, principal=principal)


@router.post(
    "/cases/{case_id}/underwriting-variances/{variance_id}/decisions",
    response_model=UnderwritingVarianceWorkspaceOut,
    tags=["underwriting"],
)
def record_underwriting_variance_decision(
    request: Request,
    case_id: str,
    variance_id: str,
    payload: UnderwritingVarianceDecisionIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> UnderwritingVarianceWorkspaceOut:
    principal.require("review")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    variance = get_case_variance(
        session, case=case, tenant_id=principal.tenant_id, variance_id=variance_id
    )
    if not case.is_demo:
        raise AppError(
            409,
            "variance_decisions_not_configured",
            "Variance decisions unavailable",
            "This case has no connected recommendation and decision service.",
        )
    active_decision = session.scalar(
        select(UnderwritingVarianceDecision.id).where(
            UnderwritingVarianceDecision.tenant_id == principal.tenant_id,
            UnderwritingVarianceDecision.variance_id == variance.id,
            UnderwritingVarianceDecision.is_current.is_(True),
        )
    )
    if active_decision is not None:
        raise AppError(
            409,
            "variance_already_reviewed",
            "Variance already reviewed",
            "Reset the demo case before recording another decision.",
        )

    selected_value = {
        "retain_original": variance.applied_value,
        "accept_suggested": variance.suggested_value,
        "custom_value": payload.selected_value,
        "refer": None,
    }[payload.decision]
    decision = UnderwritingVarianceDecision(
        tenant_id=principal.tenant_id,
        case_id=case.id,
        variance_id=variance.id,
        decision=payload.decision,
        selected_value=selected_value,
        justification=payload.justification,
        reviewer_subject=principal.subject,
        approval_status="demo_only",
        is_current=True,
    )
    session.add(decision)
    append_audit(
        session,
        tenant_id=principal.tenant_id,
        case_id=case.id,
        actor_subject=principal.subject,
        action="underwriting.variance_decision_recorded",
        outcome="success",
        correlation_id=request.state.correlation_id,
        metadata={"decision": payload.decision, "approval_status": "demo_only"},
    )
    session.flush()
    return build_variance_workspace(session, case=case, tenant_id=principal.tenant_id)


@router.post(
    "/cases/{case_id}/underwriting-variances/demo-reset",
    response_model=UnderwritingVarianceWorkspaceOut,
    tags=["underwriting"],
)
def reset_demo_underwriting_variance(
    request: Request,
    case_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> UnderwritingVarianceWorkspaceOut:
    principal.require("review")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    if not case.is_demo:
        raise AppError(404, "case_not_found", "Case not found", "The case was not found.")

    variances = list(
        session.scalars(
            select(UnderwritingVariance).where(
                UnderwritingVariance.tenant_id == principal.tenant_id,
                UnderwritingVariance.case_id == case.id,
            )
        )
    )
    for variance in variances:
        for decision in session.scalars(
            select(UnderwritingVarianceDecision).where(
                UnderwritingVarianceDecision.tenant_id == principal.tenant_id,
                UnderwritingVarianceDecision.variance_id == variance.id,
                UnderwritingVarianceDecision.is_current.is_(True),
            )
        ):
            decision.is_current = False
        session.add(
            UnderwritingVarianceDecision(
                tenant_id=principal.tenant_id,
                case_id=case.id,
                variance_id=variance.id,
                decision="reset",
                selected_value=None,
                justification="Demo state reset for another presentation.",
                reviewer_subject=principal.subject,
                approval_status="not_applicable",
                is_current=False,
            )
        )
    append_audit(
        session,
        tenant_id=principal.tenant_id,
        case_id=case.id,
        actor_subject=principal.subject,
        action="underwriting.variance_demo_reset",
        outcome="success",
        correlation_id=request.state.correlation_id,
        metadata={"decision": "reset"},
    )
    session.flush()
    return build_variance_workspace(session, case=case, tenant_id=principal.tenant_id)


@router.post(
    "/cases/{case_id}/documents",
    response_model=UploadOut,
    status_code=202,
    tags=["documents"],
)
async def upload_document(
    request: Request,
    case_id: str,
    file: UploadFile = File(...),
    document_type: str = Form(default="medical_report"),
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=200),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> UploadOut:
    principal.require("upload")
    require_case_access(session, principal=principal, external_case_id=case_id)
    content = await file.read(request.app.state.settings.max_upload_bytes + 1)
    result = ingest_document(
        session,
        settings=request.app.state.settings,
        store=request.app.state.object_store,
        registry=request.app.state.registry,
        tenant_id=principal.tenant_id,
        external_case_id=case_id,
        actor_subject=principal.subject,
        filename=file.filename,
        declared_media_type=file.content_type,
        content=content,
        idempotency_key=idempotency_key,
        correlation_id=request.state.correlation_id,
        requested_document_type=document_type,
    )
    return UploadOut(
        document=document_summary(session, result.document),
        replayed=result.replayed,
    )


@router.get("/documents/{document_id}", response_model=DocumentSummary, tags=["documents"])
def document_metadata(
    document_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> DocumentSummary:
    principal.require("view")
    document = get_document(session, principal=principal, document_id=document_id)
    return document_summary(session, document)


@router.delete(
    "/documents/{document_id}",
    response_model=DocumentDeletionOut,
    tags=["documents"],
)
def remove_document(
    request: Request,
    document_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> DocumentDeletionOut:
    principal.require("upload")
    document = get_document(session, principal=principal, document_id=document_id)
    object_key = document.object_key
    append_audit(
        session,
        tenant_id=document.tenant_id,
        case_id=document.case_id,
        document_id=document.id,
        actor_subject=principal.subject,
        action="document.deleted",
        outcome="success",
        correlation_id=request.state.correlation_id,
        metadata={"reason": "user_requested"},
    )
    session.execute(delete(Document).where(Document.id == document.id))
    session.flush()
    try:
        request.app.state.object_store.delete(object_key)
    except ProcessingError as exc:
        raise AppError(
            503,
            "document_deletion_failed",
            "Document removal failed",
            "The document source could not be removed. No case records were deleted.",
        ) from exc
    session.commit()
    return DocumentDeletionOut(document_id=document_id, deleted=True)


@router.get("/documents/{document_id}/content", tags=["documents"])
def document_content(
    request: Request,
    document_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> FileResponse:
    principal.require("view")
    document = get_document(session, principal=principal, document_id=document_id)
    if document.storage_state != "clean":
        raise AppError(
            409,
            "document_not_scanned",
            "Document unavailable",
            "The document cannot be viewed until scanning completes.",
        )
    try:
        path = request.app.state.object_store.verify_sha256(document.object_key, document.sha256)
    except Exception as exc:
        raise AppError(
            404,
            "document_content_missing",
            "Document unavailable",
            "Document content is unavailable.",
        ) from exc
    append_audit(
        session,
        tenant_id=document.tenant_id,
        case_id=document.case_id,
        document_id=document.id,
        actor_subject=principal.subject,
        action="document.content_viewed",
        outcome="success",
        correlation_id=request.state.correlation_id,
        metadata={"media_type": document.media_type},
    )
    headers = {
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Security-Policy": (
            "default-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
        ),
    }
    return FileResponse(
        path,
        media_type=document.media_type,
        filename=document.safe_filename,
        content_disposition_type="inline",
        headers=headers,
    )


@router.post("/documents/{document_id}/retry", response_model=DocumentSummary, tags=["documents"])
def retry(
    request: Request,
    document_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> DocumentSummary:
    principal.require("retry")
    document = get_document(session, principal=principal, document_id=document_id)
    retry_document(
        session,
        document=document,
        actor_subject=principal.subject,
        correlation_id=request.state.correlation_id,
    )
    return document_summary(session, document)


@router.get(
    "/documents/{document_id}/extractions/history",
    response_model=ExtractionHistoryOut,
    tags=["medical evidence"],
)
def extraction_history_latest(
    document_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> ExtractionHistoryOut:
    principal.require("view")
    document = get_document(session, principal=principal, document_id=document_id)
    return extraction_history(session, tenant_id=principal.tenant_id, document=document)


@router.get(
    "/documents/{document_id}/extractions/latest",
    response_model=ExtractionOut,
    tags=["medical evidence"],
)
def extraction_latest(
    document_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> ExtractionOut:
    principal.require("view")
    get_document(session, principal=principal, document_id=document_id)
    document, run, fields, facts = latest_extraction(
        session, tenant_id=principal.tenant_id, document_id=document_id
    )
    return ExtractionOut(
        document=document_summary(session, document),
        run=run,
        fields=fields,
        additional_facts=facts,
    )


@router.get("/cases/{case_id}/evidence", response_model=EvidenceOut, tags=["medical evidence"])
def evidence(
    case_id: str,
    section: str = Query(default="medical", pattern="^medical$"),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> EvidenceOut:
    del section
    principal.require("view")
    require_case_access(session, principal=principal, external_case_id=case_id)
    result = build_workspace(session, tenant_id=principal.tenant_id, external_case_id=case_id)
    return EvidenceOut(fields=result.fields, counts=result.counts)


@router.post(
    "/documents/{document_id}/reviews",
    response_model=ReviewResponse,
    tags=["medical evidence"],
)
def submit_reviews(
    request: Request,
    document_id: str,
    payload: ReviewRequest,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> ReviewResponse:
    principal.require("review")
    document = get_document(session, principal=principal, document_id=document_id)
    reviews = review_fields(
        session,
        document=document,
        actor_subject=principal.subject,
        correlation_id=request.state.correlation_id,
        decisions=[
            ReviewInput(
                field_id=item.field_id,
                decision=item.decision,
                expected_version=item.expected_version,
                corrected_value=item.corrected_value,
                rationale=item.rationale,
            )
            for item in payload.decisions
        ],
    )
    session.flush()
    return ReviewResponse(
        reviews=[
            {
                "id": review.id,
                "version": review.version,
                "decision": review.decision,
                "rationale": review.rationale,
                "before_value": review.before_value_json,
                "after_value": review.after_value_json,
                "reviewer_subject": review.reviewer_subject,
                "reviewed_at": review.reviewed_at,
            }
            for review in reviews
        ],
        document_status=document.status,
    )


@router.get("/cases/{case_id}/audit", response_model=AuditPage, tags=["audit"])
def audit(
    request: Request,
    case_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> AuditPage:
    principal.require("audit")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    result = audit_page(
        session,
        tenant_id=principal.tenant_id,
        case=case,
        offset=offset,
        limit=limit,
    )
    append_audit(
        session,
        tenant_id=principal.tenant_id,
        case_id=case.id,
        actor_subject=principal.subject,
        action="case.audit_viewed",
        outcome="success",
        correlation_id=request.state.correlation_id,
        metadata={"result_count": len(result.items)},
    )
    return result


@router.get(
    "/cases/{case_id}/identity/summary", response_model=IdentitySummaryOut, tags=["identity"]
)
def identity_summary(
    request: Request,
    case_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> IdentitySummaryOut:
    principal.require("view")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    return build_identity_summary(
        session,
        case=case,
        tenant_id=principal.tenant_id,
        settings=request.app.state.settings,
    )


@router.get(
    "/cases/{case_id}/identity/matches", response_model=IdentityMatchesOut, tags=["identity"]
)
def identity_matches(
    request: Request,
    case_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> IdentityMatchesOut:
    principal.require("view")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    summary = build_identity_summary(
        session,
        case=case,
        tenant_id=principal.tenant_id,
        settings=request.app.state.settings,
    )
    return IdentityMatchesOut(
        case_id=summary.case_id,
        fingerprint=summary.fingerprint,
        match_status=summary.match_status,
        matches=summary.matches,
    )


@router.post(
    "/cases/{case_id}/identity/verify", response_model=IdentityVerifyOut, tags=["identity"]
)
def identity_verify(
    request: Request,
    case_id: str,
    payload: IdentityVerifyIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> IdentityVerifyOut:
    principal.require("review")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    summary, reused = verify_identity(
        session,
        case=case,
        principal=principal,
        settings=request.app.state.settings,
        payload=payload,
        correlation_id=request.state.correlation_id,
        aadhaar_verifier=getattr(request.app.state, "aadhaar_verifier", None),
        pan_verifier=getattr(request.app.state, "pan_verifier", None),
    )
    return IdentityVerifyOut(reused_existing=reused, summary=summary)


@router.post(
    "/cases/{case_id}/identity/review", response_model=IdentitySummaryOut, tags=["identity"]
)
def identity_review(
    request: Request,
    case_id: str,
    payload: IdentityReviewIn,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> IdentitySummaryOut:
    principal.require("review")
    case = require_case_access(session, principal=principal, external_case_id=case_id)
    return record_identity_review(
        session,
        case=case,
        principal=principal,
        settings=request.app.state.settings,
        payload=payload,
        correlation_id=request.state.correlation_id,
    )
