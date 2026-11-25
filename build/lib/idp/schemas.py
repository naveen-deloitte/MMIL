from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    correlation_id: str


class CaseSummary(ApiModel):
    id: str
    external_case_id: str
    applicant_display_name: str
    proposal_number: str
    product_name: str
    workflow_stage: str
    sla_label: str


class DocumentSummary(ApiModel):
    id: str
    version: int
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    document_type: str
    schema_version: str
    status: str
    failure_code: str | None
    page_count: int | None
    viewable: bool
    created_at: datetime
    job_id: str | None = None
    attempts: int = 0


class CitationOut(ApiModel):
    document_id: str
    document_version: int
    page: int
    excerpt: str
    bbox: dict[str, float] | None = None


class ValidationOut(ApiModel):
    code: str
    severity: str


class ReviewOut(ApiModel):
    id: str
    version: int
    decision: str
    rationale: str | None
    before_value: Any | None
    after_value: Any | None
    reviewer_subject: str
    reviewed_at: datetime


class FieldOut(ApiModel):
    id: str
    document_id: str
    run_id: str
    field_path: str
    label: str
    ui_section: str
    ui_group: str
    source_literal: str | None
    candidate_value: Any | None
    effective_value: Any | None
    data_type: str
    unit: str | None
    extraction_status: str
    confidence: float | None
    validations: list[ValidationOut]
    citations: list[CitationOut]
    review_state: str
    review_version: int
    latest_review: ReviewOut | None = None


class RunSummary(ApiModel):
    id: str
    document_id: str
    sequence: int
    status: str
    document_type: str
    schema_version: str
    extractor_version: str
    provider: str
    model_version: str
    prompt_version: str
    started_at: datetime
    completed_at: datetime | None
    latency_ms: int | None


class EvidenceCounts(ApiModel):
    found: int = 0
    uncertain: int = 0
    not_found: int = 0
    pending: int = 0
    accepted: int = 0
    corrected: int = 0
    rejected: int = 0
    not_applicable: int = 0


class ExtractionOut(ApiModel):
    document: DocumentSummary
    run: RunSummary | None
    fields: list[FieldOut]


class EvidenceOut(ApiModel):
    fields: list[FieldOut]
    counts: EvidenceCounts


class WorkspaceOut(ApiModel):
    case: CaseSummary
    documents: list[DocumentSummary]
    runs: list[RunSummary]
    fields: list[FieldOut]
    counts: EvidenceCounts


class UploadOut(ApiModel):
    document: DocumentSummary
    replayed: bool


class ReviewDecisionIn(BaseModel):
    field_id: str
    decision: Literal["accepted", "corrected", "rejected", "not_applicable"]
    expected_version: int = Field(ge=0)
    corrected_value: Any | None = None
    rationale: str | None = Field(default=None, max_length=2000)


class ReviewRequest(BaseModel):
    decisions: list[ReviewDecisionIn] = Field(min_length=1, max_length=200)


class ReviewResponse(ApiModel):
    reviews: list[ReviewOut]
    document_status: str


class AuditEventOut(ApiModel):
    id: str
    actor_subject: str
    action: str
    outcome: str
    correlation_id: str
    metadata: dict[str, Any]
    occurred_at: datetime
    document_id: str | None
    run_id: str | None
    field_id: str | None


class AuditPage(ApiModel):
    items: list[AuditEventOut]
    next_offset: int | None


class HealthOut(ApiModel):
    status: str
