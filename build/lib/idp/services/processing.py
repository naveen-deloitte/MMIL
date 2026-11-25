from __future__ import annotations

import logging
import socket
import time
from dataclasses import replace
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from idp.audit import append_audit
from idp.config import Settings
from idp.database import Database
from idp.document_types import DocumentTypeRegistry
from idp.errors import AppError, ProcessingError
from idp.extraction.engine import (
    EXTRACTOR_VERSION,
    Citation,
    ExtractedCandidate,
    SchemaExtractor,
    normalize_value,
    validate_grounding,
)
from idp.extraction.providers import ExtractionProvider, build_provider
from idp.extraction.scanner import DevelopmentBasicScanner, Scanner
from idp.extraction.text import PageText, PageTextService
from idp.models import (
    Document,
    DocumentPage,
    ExtractedField,
    ExtractionRun,
    ProcessingJob,
    utc_now,
)
from idp.storage import LocalObjectStore

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "uploaded": {"scanning", "cancelled"},
    "scanning": {"ocr", "failed", "cancelled"},
    "ocr": {"extracting", "failed", "cancelled"},
    "extracting": {"review_required", "completed", "failed", "cancelled"},
    "review_required": {"completed", "cancelled"},
    "completed": set(),
    "failed": {"uploaded", "cancelled"},
    "cancelled": set(),
}


def assert_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise AppError(
            409,
            "invalid_status_transition",
            "Invalid processing state",
            "The requested processing state transition is not allowed.",
        )


def transition(job: ProcessingJob, document: Document, target: str) -> None:
    assert_transition(job.status, target)
    job.status = target
    document.status = target
    document.failure_code = None
    job.failure_code = None
    if target == "scanning" and job.started_at is None:
        job.started_at = utc_now()
    if target in {"completed", "cancelled"}:
        job.completed_at = utc_now()


class ProcessingService:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        store: LocalObjectStore,
        registry: DocumentTypeRegistry,
        scanner: Scanner | None = None,
        text_service: PageTextService | None = None,
        provider: ExtractionProvider | None = None,
        worker_id: str | None = None,
    ):
        self.settings = settings
        self.database = database
        self.store = store
        self.registry = registry
        if settings.environment == "production" and scanner is None:
            raise ProcessingError("production_scanner_not_configured", retryable=False)
        self.scanner = scanner or DevelopmentBasicScanner()
        self.text_service = text_service or PageTextService(settings)
        self.provider = provider or build_provider(settings)
        self.worker_id = worker_id or f"{socket.gethostname()}-{id(self)}"

    def process_next(self) -> str | None:
        job_id = self._claim_next()
        if job_id is None:
            return None
        self.process_job(job_id)
        return job_id

    def _claim_next(self) -> str | None:
        now = utc_now()
        with self.database.session() as session:
            query = (
                select(ProcessingJob)
                .where(
                    ProcessingJob.status == "uploaded",
                    ProcessingJob.available_at <= now,
                    or_(
                        ProcessingJob.lease_expires_at.is_(None),
                        ProcessingJob.lease_expires_at < now,
                    ),
                )
                .order_by(ProcessingJob.created_at.asc())
                .limit(1)
            )
            if session.bind and session.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            job = session.scalar(query)
            if job is None:
                return None
            document = session.get(Document, job.document_id)
            if document is None:
                job.status = "failed"
                job.failure_code = "document_missing"
                return job.id
            transition(job, document, "scanning")
            job.attempts += 1
            job.lease_owner = self.worker_id
            job.lease_expires_at = now + timedelta(seconds=self.settings.worker_lease_seconds)
            append_audit(
                session,
                tenant_id=document.tenant_id,
                case_id=document.case_id,
                document_id=document.id,
                actor_subject="system:worker",
                action="document.processing_started",
                outcome="success",
                correlation_id=job.correlation_id,
                metadata={"attempt": job.attempts, "status": "scanning"},
            )
            return job.id

    def process_job(self, job_id: str) -> None:
        started = time.perf_counter()
        try:
            with self.database.session() as session:
                job, document = self._load_job_document(session, job_id)
                if job.status != "scanning":
                    raise ProcessingError("job_not_claimed", retryable=False)
                path = self.store.verify_sha256(document.object_key, document.sha256)
                self.scanner.scan(path)
                document.storage_state = "clean"
                transition(job, document, "ocr")
                append_audit(
                    session,
                    tenant_id=document.tenant_id,
                    case_id=document.case_id,
                    document_id=document.id,
                    actor_subject="system:worker",
                    action="document.scan_completed",
                    outcome="success",
                    correlation_id=job.correlation_id,
                    metadata={"status": "ocr"},
                )

            pages = self.text_service.extract(path, document.media_type)
            if len(pages) != document.page_count:
                raise ProcessingError("page_count_mismatch", retryable=False)

            with self.database.session() as session:
                job, document = self._load_job_document(session, job_id)
                transition(job, document, "extracting")

            extractor = SchemaExtractor(self.registry.definition)
            candidates = extractor.extract(
                document_id=document.id,
                document_version=document.version,
                pages=pages,
            )
            provider_response = self.provider.extract(
                pages=pages, definition=self.registry.definition
            )
            if provider_response.fields:
                candidates = merge_provider_fields(
                    candidates=candidates,
                    provider_fields=provider_response.fields,
                    pages=pages,
                    document_id=document.id,
                    document_version=document.version,
                    registry=self.registry,
                )
            validate_grounding(candidates, pages, document.id, document.version)

            with self.database.session() as session:
                job, document = self._load_job_document(session, job_id)
                if job.status != "extracting":
                    raise ProcessingError("job_state_changed", retryable=False)
                sequence = (
                    session.scalar(
                        select(func.max(ExtractionRun.sequence)).where(
                            ExtractionRun.document_id == document.id
                        )
                    )
                    or 0
                ) + 1
                run = ExtractionRun(
                    document_id=document.id,
                    sequence=sequence,
                    status="succeeded",
                    document_type=document.document_type,
                    schema_version=document.schema_version,
                    extractor_version=EXTRACTOR_VERSION,
                    provider=self.provider.name,
                    model_version=self.provider.model_version,
                    prompt_version=self.settings.prompt_version,
                    correlation_id=job.correlation_id,
                    completed_at=utc_now(),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    input_tokens=provider_response.input_tokens,
                    output_tokens=provider_response.output_tokens,
                )
                session.add(run)
                session.flush()
                for page in pages:
                    session.add(
                        DocumentPage(
                            document_id=document.id,
                            run_id=run.id,
                            page_number=page.page_number,
                            text=page.text,
                            width=page.width,
                            height=page.height,
                            blocks_json=[block.as_dict() for block in page.blocks],
                            text_engine=page.engine,
                            text_engine_version=page.engine_version,
                            ocr_used=page.ocr_used,
                        )
                    )
                reviewable_count = 0
                for candidate in candidates:
                    if candidate.normalized_value is not None:
                        reviewable_count += 1
                    session.add(
                        ExtractedField(
                            run_id=run.id,
                            document_id=document.id,
                            field_path=candidate.field_path,
                            label=candidate.label,
                            ui_section=candidate.ui_section,
                            ui_group=candidate.ui_group,
                            source_literal=candidate.source_literal,
                            normalized_value_json=candidate.normalized_value,
                            data_type=candidate.data_type,
                            unit=candidate.unit,
                            extraction_status=candidate.status,
                            confidence=candidate.confidence,
                            validation_json=candidate.validations,
                            citations_json=[citation.as_dict() for citation in candidate.citations],
                            review_state=(
                                "pending"
                                if candidate.normalized_value is not None
                                else "not_reviewable"
                            ),
                        )
                    )
                document.latest_run_id = run.id
                target = "review_required" if reviewable_count else "completed"
                transition(job, document, target)
                job.lease_owner = None
                job.lease_expires_at = None
                append_audit(
                    session,
                    tenant_id=document.tenant_id,
                    case_id=document.case_id,
                    document_id=document.id,
                    run_id=run.id,
                    actor_subject="system:worker",
                    action="document.extraction_completed",
                    outcome="success",
                    correlation_id=job.correlation_id,
                    metadata={
                        "status": target,
                        "provider": self.provider.name,
                        "schema_version": document.schema_version,
                        "result_count": reviewable_count,
                    },
                )
        except ProcessingError as exc:
            self._record_failure(job_id, exc)
        except Exception as exc:
            # Log only the exception class and opaque job ID. Do not render provider/parser text.
            logger.error(
                "Document processing failed job_id=%s exception_type=%s",
                job_id,
                type(exc).__name__,
            )
            self._record_failure(
                job_id, ProcessingError("internal_processing_error", retryable=True)
            )

    def _record_failure(self, job_id: str, error: ProcessingError) -> None:
        with self.database.session() as session:
            job, document = self._load_job_document(session, job_id)
            current = job.status
            if current not in {"scanning", "ocr", "extracting"}:
                return
            transition(job, document, "failed")
            job.failure_code = error.code
            document.failure_code = error.code
            job.lease_owner = None
            job.lease_expires_at = None
            exhausted = job.attempts >= job.max_attempts
            will_retry = error.retryable and not exhausted
            append_audit(
                session,
                tenant_id=document.tenant_id,
                case_id=document.case_id,
                document_id=document.id,
                actor_subject="system:worker",
                action="document.processing_failed",
                outcome="retry_scheduled" if will_retry else "failed",
                correlation_id=job.correlation_id,
                metadata={"failure_code": error.code, "attempt": job.attempts},
            )
            if will_retry:
                assert_transition("failed", "uploaded")
                job.status = "uploaded"
                document.status = "uploaded"
                delay_seconds = min(60, 2 ** max(0, job.attempts - 1))
                job.available_at = utc_now() + timedelta(seconds=delay_seconds)

    @staticmethod
    def _load_job_document(session: Session, job_id: str) -> tuple[ProcessingJob, Document]:
        job = session.get(ProcessingJob, job_id)
        if job is None:
            raise ProcessingError("job_missing", retryable=False)
        document = session.get(Document, job.document_id)
        if document is None:
            raise ProcessingError("document_missing", retryable=False)
        return job, document


def retry_document(
    session: Session,
    *,
    document: Document,
    actor_subject: str,
    correlation_id: str,
) -> ProcessingJob:
    job = session.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document.id)
        .order_by(ProcessingJob.created_at.desc())
    )
    if job is None or job.status != "failed":
        raise AppError(
            409,
            "document_not_retryable",
            "Document cannot be retried",
            "Only a failed document can be retried.",
        )
    assert_transition(job.status, "uploaded")
    job.status = "uploaded"
    document.status = "uploaded"
    job.failure_code = None
    document.failure_code = None
    job.available_at = utc_now()
    job.lease_owner = None
    job.lease_expires_at = None
    job.correlation_id = correlation_id
    append_audit(
        session,
        tenant_id=document.tenant_id,
        case_id=document.case_id,
        document_id=document.id,
        actor_subject=actor_subject,
        action="document.retry_requested",
        outcome="success",
        correlation_id=correlation_id,
        metadata={"attempt": job.attempts, "status": "uploaded"},
    )
    return job


def merge_provider_fields(
    *,
    candidates: list[ExtractedCandidate],
    provider_fields: list[dict[str, Any]],
    pages: list[PageText],
    document_id: str,
    document_version: int,
    registry: DocumentTypeRegistry,
) -> list[ExtractedCandidate]:
    by_path = {candidate.field_path: candidate for candidate in candidates}
    page_map = {page.page_number: page for page in pages}
    for item in provider_fields:
        path = str(item.get("field_path", ""))
        existing = by_path.get(path)
        if existing is None or existing.normalized_value is not None:
            continue
        definition = registry.field(path)
        page_number = item.get("page")
        literal = item.get("source_literal")
        excerpt = item.get("excerpt")
        if (
            not isinstance(page_number, int)
            or not isinstance(literal, str)
            or not isinstance(excerpt, str)
            or page_number not in page_map
            or excerpt not in page_map[page_number].text
            or literal not in excerpt
        ):
            raise ProcessingError("citation_invalid", retryable=False)
        try:
            value = normalize_value(definition.data_type, literal)
        except ValueError as exc:
            raise ProcessingError("invalid_provider_output", retryable=False) from exc
        confidence_raw = item.get("confidence", 0.5)
        try:
            confidence = min(1.0, max(0.0, float(confidence_raw)))
        except (TypeError, ValueError) as exc:
            raise ProcessingError("invalid_provider_output", retryable=False) from exc
        by_path[path] = replace(
            existing,
            source_literal=literal,
            normalized_value=value,
            status="found",
            confidence=confidence,
            citations=[
                Citation(
                    document_id=document_id,
                    document_version=document_version,
                    page=page_number,
                    excerpt=excerpt,
                    bbox=None,
                )
            ],
            validations=[],
        )
    return [by_path[candidate.field_path] for candidate in candidates]
