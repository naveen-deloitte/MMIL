from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from idp.audit import append_audit
from idp.config import Settings
from idp.document_types import DocumentTypeRegistry
from idp.errors import AppError
from idp.file_validation import validate_upload
from idp.models import Case, Document, ProcessingJob, UploadIdempotency, new_id
from idp.storage import LocalObjectStore, sanitize_filename


@dataclass(frozen=True)
class IngestionResult:
    document: Document
    job: ProcessingJob
    replayed: bool


def find_case(session: Session, *, tenant_id: str, external_case_id: str) -> Case:
    case = session.scalar(
        select(Case).where(
            Case.tenant_id == tenant_id,
            Case.external_case_id == external_case_id,
        )
    )
    if case is None:
        raise AppError(404, "case_not_found", "Case not found", "The case was not found.")
    return case


def ingest_document(
    session: Session,
    *,
    settings: Settings,
    store: LocalObjectStore,
    registry: DocumentTypeRegistry,
    tenant_id: str,
    external_case_id: str,
    actor_subject: str,
    filename: str | None,
    declared_media_type: str | None,
    content: bytes,
    idempotency_key: str,
    correlation_id: str,
    requested_document_type: str,
) -> IngestionResult:
    case = find_case(session, tenant_id=tenant_id, external_case_id=external_case_id)
    content_hash = hashlib.sha256(content).hexdigest()
    try:
        definition = registry.for_type(requested_document_type).definition
    except KeyError as exc:
        raise AppError(
            422,
            "document_type_not_configured",
            "Unsupported document type",
            "The selected document type is not enabled.",
        ) from exc

    validated = validate_upload(
        content=content,
        filename=filename,
        declared_media_type=declared_media_type,
        settings=settings,
    )
    if validated.media_type not in definition.constraints.media_types:
        raise AppError(
            415,
            "document_type_media_mismatch",
            "Unsupported document type",
            "This media type is not enabled for the selected document type.",
        )
    if validated.page_count > min(settings.max_pages, definition.constraints.max_pages):
        raise AppError(
            422,
            "page_limit_exceeded",
            "Too many pages",
            "The document exceeds the configured document-type page limit.",
        )

    idempotency = session.scalar(
        select(UploadIdempotency).where(
            UploadIdempotency.tenant_id == tenant_id,
            UploadIdempotency.case_id == case.id,
            UploadIdempotency.idempotency_key == idempotency_key,
        )
    )
    if idempotency is not None:
        if idempotency.content_sha256 != content_hash:
            raise AppError(
                409,
                "idempotency_conflict",
                "Upload conflict",
                "This idempotency key was already used for different content.",
            )
        existing = session.get(Document, idempotency.document_id)
        if existing is None:
            raise AppError(
                409,
                "idempotency_record_invalid",
                "Upload conflict",
                "The previous upload record is unavailable.",
            )
        job = session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.document_id == existing.id)
            .order_by(ProcessingJob.created_at.asc())
        )
        assert job is not None
        append_audit(
            session,
            tenant_id=tenant_id,
            case_id=case.id,
            document_id=existing.id,
            actor_subject=actor_subject,
            action="document.upload_replayed",
            outcome="success",
            correlation_id=correlation_id,
            metadata={"status": existing.status},
        )
        return IngestionResult(existing, job, True)

    duplicate_content = session.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.case_id == case.id,
            Document.sha256 == content_hash,
        )
    )
    if duplicate_content is not None:
        session.add(
            UploadIdempotency(
                tenant_id=tenant_id,
                case_id=case.id,
                idempotency_key=idempotency_key,
                content_sha256=content_hash,
                document_id=duplicate_content.id,
            )
        )
        session.flush()
        job = session.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.document_id == duplicate_content.id)
            .order_by(ProcessingJob.created_at.asc())
        )
        assert job is not None
        append_audit(
            session,
            tenant_id=tenant_id,
            case_id=case.id,
            document_id=duplicate_content.id,
            actor_subject=actor_subject,
            action="document.upload_replayed",
            outcome="success",
            correlation_id=correlation_id,
            metadata={"status": duplicate_content.status},
        )
        return IngestionResult(duplicate_content, job, True)

    safe_filename = sanitize_filename(filename, validated.media_type)
    prior_version = session.scalar(
        select(func.max(Document.version)).where(
            Document.case_id == case.id,
            Document.safe_filename == safe_filename,
        )
    )
    document_id = new_id()
    object_key, object_version = store.put_quarantine(
        tenant_id=tenant_id,
        case_id=case.id,
        document_id=document_id,
        safe_filename=safe_filename,
        content=content,
    )
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        case_id=case.id,
        version=(prior_version or 0) + 1,
        original_filename=filename or safe_filename,
        safe_filename=safe_filename,
        media_type=validated.media_type,
        size_bytes=len(content),
        sha256=content_hash,
        object_key=object_key,
        object_version=object_version,
        document_type=definition.document_type,
        schema_version=definition.schema_version,
        status="uploaded",
        page_count=validated.page_count,
        idempotency_key=idempotency_key,
        created_by=actor_subject,
    )
    job = ProcessingJob(
        document_id=document.id,
        status="uploaded",
        max_attempts=settings.job_max_attempts,
        correlation_id=correlation_id,
    )
    idempotency = UploadIdempotency(
        tenant_id=tenant_id,
        case_id=case.id,
        idempotency_key=idempotency_key,
        content_sha256=content_hash,
        document_id=document.id,
    )
    session.add_all([document, job, idempotency])
    session.flush()
    append_audit(
        session,
        tenant_id=tenant_id,
        case_id=case.id,
        document_id=document.id,
        actor_subject=actor_subject,
        action="document.uploaded",
        outcome="success",
        correlation_id=correlation_id,
        metadata={
            "media_type": validated.media_type,
            "size_bytes": len(content),
            "document_type": definition.document_type,
            "schema_version": definition.schema_version,
            "page_count": validated.page_count,
        },
    )
    return IngestionResult(document, job, False)
