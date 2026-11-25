from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from idp.audit import append_audit
from idp.auth import Principal
from idp.errors import AppError
from idp.models import Document
from idp.schemas import (
    AuditPage,
    DocumentSummary,
    EvidenceOut,
    ExtractionOut,
    HealthOut,
    ReviewRequest,
    ReviewResponse,
    UploadOut,
    WorkspaceOut,
)
from idp.services.ingestion import find_case, ingest_document
from idp.services.processing import retry_document
from idp.services.reviews import ReviewInput, review_fields
from idp.services.workspace import (
    audit_page,
    build_workspace,
    document_summary,
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


def get_document(session: Session, *, tenant_id: str, document_id: str) -> Document:
    document = session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        raise AppError(
            404, "document_not_found", "Document not found", "The document was not found."
        )
    return document


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


@router.get("/cases/{case_id}/workspace", response_model=WorkspaceOut, tags=["medical evidence"])
def workspace(
    case_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> WorkspaceOut:
    principal.require("view")
    return build_workspace(session, tenant_id=principal.tenant_id, external_case_id=case_id)


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
    document = get_document(session, tenant_id=principal.tenant_id, document_id=document_id)
    return document_summary(session, document)


@router.get("/documents/{document_id}/content", tags=["documents"])
def document_content(
    request: Request,
    document_id: str,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> FileResponse:
    principal.require("view")
    document = get_document(session, tenant_id=principal.tenant_id, document_id=document_id)
    if document.storage_state != "clean":
        raise AppError(
            409,
            "document_not_scanned",
            "Document unavailable",
            "The document cannot be viewed until scanning completes.",
        )
    try:
        path = request.app.state.object_store.verify_sha256(
            document.object_key, document.sha256
        )
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
        "Content-Security-Policy": "default-src 'none'; sandbox",
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
    document = get_document(session, tenant_id=principal.tenant_id, document_id=document_id)
    retry_document(
        session,
        document=document,
        actor_subject=principal.subject,
        correlation_id=request.state.correlation_id,
    )
    return document_summary(session, document)


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
    document, run, fields = latest_extraction(
        session, tenant_id=principal.tenant_id, document_id=document_id
    )
    return ExtractionOut(document=document_summary(session, document), run=run, fields=fields)


@router.get("/cases/{case_id}/evidence", response_model=EvidenceOut, tags=["medical evidence"])
def evidence(
    case_id: str,
    section: str = Query(default="medical", pattern="^medical$"),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_session),
) -> EvidenceOut:
    del section
    principal.require("view")
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
    document = get_document(session, tenant_id=principal.tenant_id, document_id=document_id)
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
    case = find_case(session, tenant_id=principal.tenant_id, external_case_id=case_id)
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
