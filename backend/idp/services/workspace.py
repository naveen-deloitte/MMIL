from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from idp.models import (
    AdditionalFact,
    AuditEvent,
    Case,
    Document,
    EvidenceReview,
    ExtractedField,
    ExtractionRun,
    ProcessingJob,
)
from idp.schemas import (
    AdditionalFactOut,
    AuditEventOut,
    AuditPage,
    CaseSummary,
    CitationOut,
    DocumentSummary,
    EvidenceCounts,
    FieldOut,
    ReviewOut,
    RunSummary,
    ValidationOut,
    WorkspaceOut,
)
from idp.services.ingestion import find_case


def document_summary(session: Session, document: Document) -> DocumentSummary:
    job = session.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document.id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    return DocumentSummary(
        id=document.id,
        version=document.version,
        filename=document.safe_filename,
        media_type=document.media_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        document_type=document.document_type,
        schema_version=document.schema_version,
        status=document.status,
        failure_code=document.failure_code,
        page_count=document.page_count,
        viewable=document.storage_state == "clean",
        created_at=document.created_at,
        job_id=job.id if job else None,
        attempts=job.attempts if job else 0,
    )


def build_workspace(session: Session, *, tenant_id: str, external_case_id: str) -> WorkspaceOut:
    case = find_case(session, tenant_id=tenant_id, external_case_id=external_case_id)
    documents = list(
        session.scalars(
            select(Document).where(Document.case_id == case.id).order_by(Document.created_at.desc())
        )
    )
    latest_run_ids = [document.latest_run_id for document in documents if document.latest_run_id]
    runs: list[ExtractionRun] = []
    fields: list[ExtractedField] = []
    facts: list[AdditionalFact] = []
    if latest_run_ids:
        runs = list(
            session.scalars(
                select(ExtractionRun)
                .where(ExtractionRun.id.in_(latest_run_ids))
                .order_by(ExtractionRun.completed_at.desc())
            )
        )
        fields = list(
            session.scalars(
                select(ExtractedField)
                .where(ExtractedField.run_id.in_(latest_run_ids))
                .order_by(ExtractedField.ui_section, ExtractedField.ui_group, ExtractedField.label)
            )
        )
        facts = list(
            session.scalars(
                select(AdditionalFact)
                .where(AdditionalFact.run_id.in_(latest_run_ids))
                .order_by(AdditionalFact.category, AdditionalFact.name)
            )
        )

    field_outputs = [_field_output(session, field) for field in fields]
    extraction_counts = Counter(field.extraction_status for field in field_outputs)
    review_counts = Counter(field.review_state for field in field_outputs)
    counts = EvidenceCounts(
        found=extraction_counts["found"],
        uncertain=extraction_counts["uncertain"],
        not_found=extraction_counts["not_found"],
        pending=review_counts["pending"],
        accepted=review_counts["accepted"],
        corrected=review_counts["corrected"],
        rejected=review_counts["rejected"],
        not_applicable=review_counts["not_applicable"],
    )
    return WorkspaceOut(
        case=CaseSummary.model_validate(case),
        documents=[document_summary(session, document) for document in documents],
        runs=[RunSummary.model_validate(run) for run in runs],
        fields=field_outputs,
        additional_facts=[_fact_output(fact) for fact in facts],
        counts=counts,
    )


def latest_extraction(
    session: Session, *, tenant_id: str, document_id: str
) -> tuple[Document, RunSummary | None, list[FieldOut], list[AdditionalFactOut]]:
    document = session.scalar(
        select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
    )
    if document is None:
        from idp.errors import AppError

        raise AppError(
            404, "document_not_found", "Document not found", "The document was not found."
        )
    if not document.latest_run_id:
        return document, None, [], []
    run = session.get(ExtractionRun, document.latest_run_id)
    fields = list(
        session.scalars(
            select(ExtractedField)
            .where(ExtractedField.run_id == document.latest_run_id)
            .order_by(ExtractedField.ui_section, ExtractedField.ui_group, ExtractedField.label)
        )
    )
    facts = list(
        session.scalars(
            select(AdditionalFact)
            .where(AdditionalFact.run_id == document.latest_run_id)
            .order_by(AdditionalFact.category, AdditionalFact.name)
        )
    )
    return (
        document,
        RunSummary.model_validate(run) if run else None,
        [_field_output(session, field) for field in fields],
        [_fact_output(fact) for fact in facts],
    )


def audit_page(
    session: Session,
    *,
    tenant_id: str,
    case: Case,
    offset: int,
    limit: int,
) -> AuditPage:
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id, AuditEvent.case_id == case.id)
            .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    has_more = len(events) > limit
    visible = events[:limit]
    return AuditPage(
        items=[
            AuditEventOut(
                id=event.id,
                actor_subject=event.actor_subject,
                action=event.action,
                outcome=event.outcome,
                correlation_id=event.correlation_id,
                metadata=event.metadata_json,
                occurred_at=event.occurred_at,
                document_id=event.document_id,
                run_id=event.run_id,
                field_id=event.field_id,
            )
            for event in visible
        ],
        next_offset=offset + limit if has_more else None,
    )


def _fact_output(fact: AdditionalFact) -> AdditionalFactOut:
    return AdditionalFactOut(
        id=fact.id,
        document_id=fact.document_id,
        run_id=fact.run_id,
        name=fact.name,
        category=fact.category,
        source_literal=fact.source_literal,
        value=fact.normalized_value_json,
        data_type=fact.data_type,
        unit=fact.unit,
        extraction_status=fact.extraction_status,
        confidence=fact.confidence,
        validations=[ValidationOut.model_validate(item) for item in fact.validation_json],
        citations=[CitationOut.model_validate(item) for item in fact.citations_json],
        linked_field_path=fact.linked_field_path,
    )


def _field_output(session: Session, field: ExtractedField) -> FieldOut:
    review = session.scalar(
        select(EvidenceReview)
        .where(EvidenceReview.field_id == field.id)
        .order_by(EvidenceReview.version.desc())
        .limit(1)
    )
    latest_review = None
    effective_value: Any | None = field.normalized_value_json
    if review is not None:
        effective_value = review.after_value_json
        latest_review = ReviewOut(
            id=review.id,
            version=review.version,
            decision=review.decision,
            rationale=review.rationale,
            before_value=review.before_value_json,
            after_value=review.after_value_json,
            reviewer_subject=review.reviewer_subject,
            reviewed_at=review.reviewed_at,
        )
    return FieldOut(
        id=field.id,
        document_id=field.document_id,
        run_id=field.run_id,
        field_path=field.field_path,
        label=field.label,
        ui_section=field.ui_section,
        ui_group=field.ui_group,
        source_literal=field.source_literal,
        candidate_value=field.normalized_value_json,
        effective_value=effective_value,
        data_type=field.data_type,
        unit=field.unit,
        extraction_status=field.extraction_status,
        confidence=field.confidence,
        validations=[ValidationOut.model_validate(item) for item in field.validation_json],
        citations=[CitationOut.model_validate(item) for item in field.citations_json],
        review_state=field.review_state,
        review_version=field.review_version,
        latest_review=latest_review,
    )
