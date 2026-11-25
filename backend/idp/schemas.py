from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class CaseCreateIn(BaseModel):
    external_case_id: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,99}$",
    )
    applicant_display_name: str = Field(min_length=1, max_length=200)
    proposal_number: str = Field(min_length=1, max_length=100)
    product_name: str = Field(min_length=1, max_length=200)
    workflow_stage: str = Field(default="human_review", min_length=1, max_length=50)
    sla_label: str = Field(default="Not set", min_length=1, max_length=100)

    @field_validator(
        "external_case_id",
        "applicant_display_name",
        "proposal_number",
        "product_name",
        "workflow_stage",
        "sla_label",
    )
    @classmethod
    def strip_case_values(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This value cannot be blank.")
        return normalized


class CaseListItem(BaseModel):
    case: CaseSummary
    document_count: int
    last_activity_at: datetime


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


class GroundedStatementOut(BaseModel):
    text: str
    citations: list[CitationOut]


class LabResultOut(BaseModel):
    category: str
    name: str
    value: str
    unit: str | None = None
    reference_range: str | None = None
    reported_flag: str | None = None
    confidence: float = Field(ge=0, le=1)
    citations: list[CitationOut]


class KnockoutCheckOut(BaseModel):
    factor: str
    value: str
    confidence: float = Field(ge=0, le=1)
    citations: list[CitationOut]


class AiAnalysisOut(BaseModel):
    summary: GroundedStatementOut | None = None
    key_medical_findings: list[GroundedStatementOut] = Field(default_factory=list)
    recommendations: list[GroundedStatementOut] = Field(default_factory=list)
    vitals_summary: GroundedStatementOut | None = None
    major_vital_factors: list[GroundedStatementOut] = Field(default_factory=list)
    lab_results: list[LabResultOut] = Field(default_factory=list)
    knockout_checks: list[KnockoutCheckOut] = Field(default_factory=list)


class ValidationOut(ApiModel):
    code: str
    severity: str
    message: str | None = None


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


class AdditionalFactOut(ApiModel):
    id: str
    document_id: str
    run_id: str
    name: str
    category: str
    source_literal: str
    value: Any
    data_type: str
    unit: str | None
    extraction_status: str
    confidence: float
    validations: list[ValidationOut]
    citations: list[CitationOut]
    linked_field_path: str | None = None


class RunSummary(ApiModel):
    id: str
    document_id: str
    sequence: int
    status: str
    document_type: str
    schema_version: str
    configuration_checksum: str
    extractor_version: str
    provider: str
    model_version: str
    prompt_version: str
    started_at: datetime
    completed_at: datetime | None
    latency_ms: int | None
    ai_analysis: AiAnalysisOut | None = Field(
        default=None,
        validation_alias="ai_analysis_json",
    )


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
    additional_facts: list[AdditionalFactOut] = Field(default_factory=list)


class EvidenceOut(ApiModel):
    fields: list[FieldOut]
    counts: EvidenceCounts


class WorkspaceOut(ApiModel):
    case: CaseSummary
    documents: list[DocumentSummary]
    runs: list[RunSummary]
    fields: list[FieldOut]
    additional_facts: list[AdditionalFactOut] = Field(default_factory=list)
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
