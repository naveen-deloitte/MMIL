from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime, TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """Persist UTC and restore timezone information on SQLite and PostgreSQL."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        normalized = normalized.astimezone(timezone.utc)
        if dialect.name == "sqlite":
            return normalized.replace(tzinfo=None)
        return normalized

    def process_result_value(self, value: datetime | None, _dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_case_id", name="uq_case_tenant_external"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    external_case_id: Mapped[str] = mapped_column(String(100), nullable=False)
    applicant_display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    proposal_number: Mapped[str] = mapped_column(String(100), nullable=False)
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(200))
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    workflow_stage: Mapped[str] = mapped_column(String(50), nullable=False, default="human_review")
    sla_label: Mapped[str] = mapped_column(String(100), nullable=False, default="Not set")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    documents: Mapped[list[Document]] = relationship(back_populates="case")


class UnderwritingVariance(Base):
    __tablename__ = "underwriting_variances"
    __table_args__ = (
        UniqueConstraint("case_id", "category", name="uq_variance_case_category"),
        Index("ix_variance_tenant_case", "tenant_id", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    applied_value: Mapped[int] = mapped_column(Integer, nullable=False)
    suggested_value: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    recommendation_source: Mapped[str] = mapped_column(String(200), nullable=False)
    recommendation_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class UnderwritingVarianceDecision(Base):
    __tablename__ = "underwriting_variance_decisions"
    __table_args__ = (
        Index("ix_variance_decision_history", "variance_id", "reviewed_at"),
        Index("ix_variance_decision_current", "variance_id", "is_current"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    variance_id: Mapped[str] = mapped_column(
        ForeignKey("underwriting_variances.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_value: Mapped[int | None] = mapped_column(Integer)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    approval_status: Mapped[str] = mapped_column(String(30), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class UnderwritingDecision(Base):
    __tablename__ = "underwriting_decisions"
    __table_args__ = (
        Index("ix_underwriting_decision_history", "tenant_id", "case_id", "decided_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    approved_sum_assured: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    applicable_premium: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    decision_rationale: Mapped[str] = mapped_column(Text, nullable=False)
    additional_terms: Mapped[str | None] = mapped_column(Text)
    decline_reason: Mapped[str | None] = mapped_column(Text)
    postponement_reason: Mapped[str | None] = mapped_column(Text)
    additional_requirements: Mapped[str | None] = mapped_column(Text)
    expected_reassessment_date: Mapped[date | None] = mapped_column(Date)
    referral_reason: Mapped[str | None] = mapped_column(Text)
    target_authority: Mapped[str | None] = mapped_column(String(200))
    decision_notes: Mapped[str | None] = mapped_column(Text)
    supporting_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    authority_reference: Mapped[str] = mapped_column(String(300), nullable=False)
    guideline_reference: Mapped[str] = mapped_column(String(300), nullable=False)
    authority_attested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    information_requests_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    underwriter_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_id", "idempotency_key", name="uq_document_idempotency"),
        UniqueConstraint("tenant_id", "case_id", "sha256", name="uq_document_content_hash"),
        Index("ix_document_case_created", "case_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_key: Mapped[str] = mapped_column(String(700), nullable=False, unique=True)
    object_version: Mapped[str] = mapped_column(String(100), nullable=False, default="local-v1")
    storage_state: Mapped[str] = mapped_column(String(30), nullable=False, default="quarantine")
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="uploaded", index=True)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    page_count: Mapped[int | None] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    latest_run_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    case: Mapped[Case] = relationship(back_populates="documents")
    jobs: Mapped[list[ProcessingJob]] = relationship(back_populates="document")
    runs: Mapped[list[ExtractionRun]] = relationship(back_populates="document")


class UploadIdempotency(Base):
    __tablename__ = "upload_idempotency"
    __table_args__ = (
        UniqueConstraint("tenant_id", "case_id", "idempotency_key", name="uq_upload_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (Index("ix_job_claim", "status", "available_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="uploaded")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200))
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    failure_code: Mapped[str | None] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="jobs")


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    __table_args__ = (
        UniqueConstraint("document_id", "sequence", name="uq_run_document_sequence"),
        Index("ix_run_document_completed", "document_id", "completed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    configuration_checksum: Mapped[str] = mapped_column(String(80), nullable=False)
    ai_analysis_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)

    document: Mapped[Document] = relationship(back_populates="runs")
    pages: Mapped[list[DocumentPage]] = relationship(back_populates="run")
    fields: Mapped[list[ExtractedField]] = relationship(back_populates="run")
    additional_facts: Mapped[list[AdditionalFact]] = relationship(back_populates="run")


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("run_id", "page_number", name="uq_page_run_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[float] = mapped_column(Float, nullable=False)
    height: Mapped[float] = mapped_column(Float, nullable=False)
    blocks_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    text_engine: Mapped[str] = mapped_column(String(100), nullable=False)
    text_engine_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ocr_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    run: Mapped[ExtractionRun] = relationship(back_populates="pages")


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (
        UniqueConstraint("run_id", "field_path", name="uq_field_run_path"),
        Index("ix_field_document_section", "document_id", "ui_section"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    field_path: Mapped[str] = mapped_column(String(250), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    ui_section: Mapped[str] = mapped_column(String(50), nullable=False)
    ui_group: Mapped[str] = mapped_column(String(100), nullable=False, default="Other")
    source_literal: Mapped[str | None] = mapped_column(Text)
    normalized_value_json: Mapped[Any | None] = mapped_column(JSON)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    extraction_status: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    validation_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    review_state: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    review_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    run: Mapped[ExtractionRun] = relationship(back_populates="fields")
    reviews: Mapped[list[EvidenceReview]] = relationship(back_populates="field")


class AdditionalFact(Base):
    __tablename__ = "additional_facts"
    __table_args__ = (Index("ix_fact_run_category", "run_id", "category"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("extraction_runs.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    data_type: Mapped[str] = mapped_column(String(50), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50))
    source_literal: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    extraction_status: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    validation_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    linked_field_path: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)

    run: Mapped[ExtractionRun] = relationship(back_populates="additional_facts")


class EvidenceReview(Base):
    __tablename__ = "evidence_reviews"
    __table_args__ = (
        UniqueConstraint("field_id", "version", name="uq_review_field_version"),
        Index("ix_review_case_time", "case_id", "reviewed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    field_id: Mapped[str] = mapped_column(
        ForeignKey("extracted_fields.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    before_value_json: Mapped[Any | None] = mapped_column(JSON)
    after_value_json: Mapped[Any | None] = mapped_column(JSON)
    reviewer_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)

    field: Mapped[ExtractedField] = relationship(back_populates="reviews")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_tenant_case_time", "tenant_id", "case_id", "occurred_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    case_id: Mapped[str | None] = mapped_column(String(36))
    document_id: Mapped[str | None] = mapped_column(String(36))
    run_id: Mapped[str | None] = mapped_column(String(36))
    field_id: Mapped[str | None] = mapped_column(String(36))
    actor_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class IdentityVerification(Base):
    """One official verification attempt for an Aadhaar or PAN. Holds no raw identity data."""

    __tablename__ = "identity_verifications"
    __table_args__ = (
        Index("ix_identity_verification_case", "tenant_id", "case_id", "subject", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    subject: Mapped[str] = mapped_column(String(20), nullable=False)  # aadhaar | pan
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    masked_identifier: Mapped[str | None] = mapped_column(String(40))
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_given: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    consent_purpose: Mapped[str | None] = mapped_column(String(200))
    consent_recorded_by: Mapped[str | None] = mapped_column(String(200))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class IdentityMatchSnapshot(Base):
    """Persisted cross-document comparison. Values are masked; unique per input fingerprint."""

    __tablename__ = "identity_match_snapshots"
    __table_args__ = (
        UniqueConstraint("case_id", "fingerprint", name="uq_identity_snapshot_fingerprint"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    overall_status: Mapped[str] = mapped_column(String(30), nullable=False)
    matches_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    findings_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)


class IdentityReview(Base):
    """Underwriter decision on the identity comparison. Append-only history."""

    __tablename__ = "identity_reviews"
    __table_args__ = (Index("ix_identity_review_case", "tenant_id", "case_id", "reviewed_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)
    resolved_fields_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    mismatches_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    reviewer_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
