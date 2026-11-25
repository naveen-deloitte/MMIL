from __future__ import annotations

import logging
import math
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
from idp.extraction.deidentification import (
    redact_pages,
    restore_provider_analysis,
    restore_provider_citations,
)
from idp.extraction.engine import (
    EXTRACTOR_VERSION,
    Citation,
    ExtractedCandidate,
    SchemaExtractor,
    extract_additional_facts,
    normalize_value,
    validate_grounding,
)
from idp.extraction.kyc_form import KYC_FORM_FIELD_ALIASES
from idp.extraction.providers import (
    DeterministicLocalProvider,
    ExtractionProvider,
    build_provider,
)
from idp.extraction.scanner import DevelopmentBasicScanner, Scanner
from idp.extraction.text import PageText, PageTextService
from idp.models import (
    AdditionalFact,
    Case,
    Document,
    DocumentPage,
    ExtractedField,
    ExtractionRun,
    ProcessingJob,
    utc_now,
)
from idp.services.review_policy import ReviewInput, decide_review_states
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


def _apply_review_policy(
    candidates: list[ExtractedCandidate],
    *,
    document_type: str,
    case_applicant_name: str | None,
) -> tuple[list[ExtractedCandidate], dict[str, str]]:
    """Return candidates with explanatory validations, and each field's initial review state."""
    outcomes = decide_review_states(
        (
            ReviewInput(
                field_path=c.field_path,
                value=c.normalized_value,
                status=c.status,
                confidence=c.confidence,
                validations=c.validations,
            )
            for c in candidates
        ),
        document_type=document_type,
        case_applicant_name=case_applicant_name,
    )
    updated: list[ExtractedCandidate] = []
    for candidate in candidates:
        outcome = outcomes[candidate.field_path]
        if outcome.added_validations:
            candidate = replace(
                candidate, validations=[*candidate.validations, *outcome.added_validations]
            )
        updated.append(candidate)
    return updated, {path: outcome.state for path, outcome in outcomes.items()}


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
        self.provider = provider
        self.worker_id = worker_id or f"{socket.gethostname()}-{id(self)}"

    def _provider_for(self, document_type: str) -> ExtractionProvider:
        if document_type == "kyc_individual":
            return DeterministicLocalProvider()
        if self.provider is None:
            self.provider = build_provider(self.settings)
        return self.provider

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
        stage = "document_scan"
        try:
            with self.database.session() as session:
                job, document = self._load_job_document(session, job_id)
                if job.status != "scanning":
                    raise ProcessingError("job_not_claimed", retryable=False)
                try:
                    registry = self.registry.for_type(document.document_type)
                except KeyError as exc:
                    raise ProcessingError(
                        "document_type_not_configured", retryable=False
                    ) from exc
                provider = self._provider_for(document.document_type)
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

            stage = "text_extraction"
            if document.document_type == "kyc_individual":
                pages = self.text_service.extract(
                    path,
                    document.media_type,
                    form_field_aliases=KYC_FORM_FIELD_ALIASES,
                )
            else:
                pages = self.text_service.extract(path, document.media_type)
            if len(pages) != document.page_count:
                raise ProcessingError("page_count_mismatch", retryable=False)

            with self.database.session() as session:
                job, document = self._load_job_document(session, job_id)
                transition(job, document, "extracting")

            extractor = SchemaExtractor(registry.definition)
            if provider.name == "deterministic-local":
                candidates = extractor.extract(
                    document_id=document.id,
                    document_version=document.version,
                    pages=pages,
                )
            else:
                candidates = extractor.empty_candidates()
            provider_pages = pages
            if provider.name != "deterministic-local":
                provider_pages = redact_pages(pages)
            stage = "provider_request"
            provider_response = provider.extract(
                pages=provider_pages,
                definition=registry.definition,
            )
            stage = "provider_item_validation"
            provider_rejection_counts: dict[str, int] = {}
            additional_facts = []
            ai_analysis = None
            if provider_response.ai_analysis_error:
                provider_rejection_counts[provider_response.ai_analysis_error] = 1
            if provider.name == "deterministic-local":
                additional_facts = extract_additional_facts(
                    raw_facts=provider_response.additional_facts,
                    definition=registry.definition,
                    primary_fields=candidates,
                    pages=pages,
                    document_id=document.id,
                    document_version=document.version,
                )
            else:
                for item in provider_response.fields:
                    try:
                        restored_fields, _ = restore_provider_citations(
                            [item], [], pages, provider_pages
                        )
                        candidates = merge_provider_fields(
                            candidates=candidates,
                            provider_fields=restored_fields,
                            pages=pages,
                            document_id=document.id,
                            document_version=document.version,
                            registry=registry,
                        )
                    except ProcessingError as exc:
                        provider_rejection_counts[exc.code] = (
                            provider_rejection_counts.get(exc.code, 0) + 1
                        )
                for item in provider_response.additional_facts:
                    try:
                        _, restored_facts = restore_provider_citations(
                            [], [item], pages, provider_pages
                        )
                        additional_facts.extend(
                            extract_additional_facts(
                                raw_facts=restored_facts,
                                definition=registry.definition,
                                primary_fields=candidates,
                                pages=pages,
                                document_id=document.id,
                                document_version=document.version,
                            )
                        )
                    except ProcessingError as exc:
                        provider_rejection_counts[exc.code] = (
                            provider_rejection_counts.get(exc.code, 0) + 1
                        )
            if provider_response.ai_analysis is not None:
                ai_analysis, rejected_analysis_items = restore_provider_analysis(
                    provider_response.ai_analysis,
                    pages,
                    provider_pages,
                    document_id=document.id,
                    document_version=document.version,
                )
                if rejected_analysis_items:
                    provider_rejection_counts["provider_citation_invalid"] = (
                        provider_rejection_counts.get("provider_citation_invalid", 0)
                        + rejected_analysis_items
                    )
            if provider.name != "deterministic-local" and provider_rejection_counts and not (
                any(candidate.normalized_value is not None for candidate in candidates)
                or additional_facts
                or ai_analysis
            ):
                raise ProcessingError("provider_items_unusable", retryable=False)
            validate_grounding(candidates, pages, document.id, document.version)

            stage = "persistence"
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
                    configuration_checksum=registry.definition.checksum,
                    extractor_version=EXTRACTOR_VERSION,
                    provider=provider.name,
                    model_version=provider.model_version,
                    prompt_version=registry.definition.extraction.prompt_version,
                    correlation_id=job.correlation_id,
                    completed_at=utc_now(),
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    input_tokens=provider_response.input_tokens,
                    output_tokens=provider_response.output_tokens,
                    ai_analysis_json=ai_analysis,
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
                case = session.get(Case, document.case_id)
                candidates, review_states = _apply_review_policy(
                    candidates,
                    document_type=document.document_type,
                    case_applicant_name=case.applicant_display_name if case else None,
                )
                reviewable_count = 0
                for candidate in candidates:
                    initial_state = review_states[candidate.field_path]
                    if initial_state == "pending":
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
                            review_state=initial_state,
                        )
                    )
                for fact in additional_facts:
                    session.add(
                        AdditionalFact(
                            run_id=run.id,
                            document_id=document.id,
                            name=fact.name,
                            category=fact.category,
                            data_type=fact.data_type,
                            unit=fact.unit,
                            source_literal=fact.source_literal,
                            normalized_value_json=fact.normalized_value,
                            extraction_status=fact.status,
                            confidence=fact.confidence,
                            validation_json=fact.validations,
                            citations_json=[citation.as_dict() for citation in fact.citations],
                            linked_field_path=fact.linked_field_path,
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
                        "provider": provider.name,
                        "schema_version": document.schema_version,
                        "result_count": reviewable_count,
                        "additional_fact_count": len(additional_facts),
                        "ai_analysis_available": ai_analysis is not None,
                        "rejected_provider_items": sum(provider_rejection_counts.values()),
                        "provider_item_rejections": provider_rejection_counts,
                    },
                )
        except ProcessingError as exc:
            logger.warning(
                "Document processing failed job_id=%s stage=%s failure_code=%s",
                job_id,
                stage,
                exc.code,
            )
            self._record_failure(job_id, exc, stage=stage)
        except Exception as exc:
            # Log only the exception class and opaque job ID. Do not render provider/parser text.
            logger.error(
                "Document processing failed job_id=%s stage=%s exception_type=%s",
                job_id,
                stage,
                type(exc).__name__,
            )
            self._record_failure(
                job_id,
                ProcessingError("internal_processing_error", retryable=True),
                stage=stage,
            )

    def _record_failure(self, job_id: str, error: ProcessingError, *, stage: str) -> None:
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
                metadata={
                    "failure_code": error.code,
                    "failure_stage": stage,
                    "attempt": job.attempts,
                },
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
    if job is None:
        raise AppError(
            409,
            "document_not_retryable",
            "Document cannot be retried",
            "The document has no processing job to retry.",
        )
    if job.status != "failed":
        run = session.get(ExtractionRun, document.latest_run_id)
        analysis = run.ai_analysis_json if run is not None else None
        summary_missing = not isinstance(analysis, dict) or not analysis.get("summary")
        if (
            document.status not in {"review_required", "completed"}
            or run is None
            or run.provider == "deterministic-local"
            or not summary_missing
        ):
            raise AppError(
                409,
                "document_not_retryable",
                "Document cannot be retried",
                "Only a failed document or a completed AI run without a summary can be retried.",
            )
        new_job = ProcessingJob(
            document_id=document.id,
            max_attempts=job.max_attempts,
            correlation_id=correlation_id,
        )
        document.status = "uploaded"
        document.failure_code = None
        session.add(new_job)
        session.flush()
        append_audit(
            session,
            tenant_id=document.tenant_id,
            case_id=document.case_id,
            document_id=document.id,
            actor_subject=actor_subject,
            action="document.ai_summary_retry_requested",
            outcome="success",
            correlation_id=correlation_id,
            metadata={"reason": "missing_ai_summary"},
        )
        return new_job
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
        path = item.get("field_path")
        if not isinstance(path, str) or not path:
            raise ProcessingError("invalid_provider_field", retryable=False)
        existing = by_path.get(path)
        if existing is None:
            raise ProcessingError("invalid_provider_field", retryable=False)
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
            raise ProcessingError("provider_citation_invalid", retryable=False)
        try:
            value = normalize_value(definition.data_type, literal)
        except ValueError as exc:
            raise ProcessingError("provider_field_value_invalid", retryable=False) from exc
        confidence_raw = item.get("confidence")
        if (
            isinstance(confidence_raw, bool)
            or not isinstance(confidence_raw, (int, float))
            or not math.isfinite(confidence_raw)
            or not 0 <= confidence_raw <= 1
        ):
            raise ProcessingError("provider_field_confidence_invalid", retryable=False)
        confidence = float(confidence_raw)
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
