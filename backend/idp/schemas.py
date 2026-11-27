from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    is_demo: bool = False
    final_decision: str | None = None
    decision_date: datetime | None = None
    underwriter_subject: str | None = None
    decision_rationale: str | None = None


class UnderwritingVarianceDecisionIn(BaseModel):
    decision: Literal["retain_original", "accept_suggested", "custom_value", "refer"]
    selected_value: int | None = Field(default=None, ge=1, le=1_000_000_000)
    justification: str = Field(min_length=1, max_length=2000)

    @field_validator("justification")
    @classmethod
    def require_nonblank_justification(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A decision justification is required.")
        return normalized

    @model_validator(mode="after")
    def validate_selected_value(self) -> UnderwritingVarianceDecisionIn:
        if self.decision == "custom_value" and self.selected_value is None:
            raise ValueError("A custom selected value is required.")
        if self.decision != "custom_value" and self.selected_value is not None:
            raise ValueError("A selected value is only allowed for a custom decision.")
        return self


class UnderwritingDecisionIn(BaseModel):
    decision: Literal["approve", "decline", "postpone", "refer"]
    approved_sum_assured: Decimal | None = Field(
        default=None, gt=0, max_digits=16, decimal_places=2
    )
    applicable_premium: Decimal | None = Field(default=None, gt=0, max_digits=16, decimal_places=2)
    decision_rationale: str | None = Field(default=None, max_length=4000)
    additional_terms: str | None = Field(default=None, max_length=4000)
    decline_reason: str | None = Field(default=None, max_length=4000)
    postponement_reason: str | None = Field(default=None, max_length=4000)
    additional_requirements: str | None = Field(default=None, max_length=4000)
    expected_reassessment_date: date | None = None
    referral_reason: str | None = Field(default=None, max_length=4000)
    target_authority: str | None = Field(default=None, max_length=200)
    decision_notes: str | None = Field(default=None, max_length=4000)
    supporting_document_ids: list[str] = Field(default_factory=list, max_length=100)
    authority_reference: str = Field(default="", max_length=300)
    guideline_reference: str = Field(default="", max_length=300)
    authority_attested: bool = False
    information_requests_acknowledged: bool = False

    @field_validator(
        "decision_rationale",
        "additional_terms",
        "decline_reason",
        "postponement_reason",
        "additional_requirements",
        "referral_reason",
        "target_authority",
        "decision_notes",
    )
    @classmethod
    def strip_decision_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("authority_reference", "guideline_reference")
    @classmethod
    def strip_optional_references(cls, value: str) -> str:
        return value.strip()

    @field_validator("supporting_document_ids")
    @classmethod
    def require_unique_supporting_documents(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Supporting documents must be unique.")
        return value

    @model_validator(mode="after")
    def validate_decision_fields(self) -> UnderwritingDecisionIn:
        required_fields = {
            "approve": ("approved_sum_assured", "applicable_premium", "decision_rationale"),
            "decline": ("decline_reason",),
            "postpone": (
                "postponement_reason",
                "additional_requirements",
                "expected_reassessment_date",
            ),
            "refer": ("referral_reason", "target_authority"),
        }[self.decision]
        if any(getattr(self, name) is None for name in required_fields):
            raise ValueError("The selected decision is missing required details.")
        if (
            self.decision == "postpone"
            and self.expected_reassessment_date is not None
            and self.expected_reassessment_date <= date.today()
        ):
            raise ValueError("The reassessment date must be in the future.")
        return self


class UnderwritingDecisionOut(ApiModel):
    id: str
    decision: Literal["approve", "decline", "postpone", "refer"]
    approved_sum_assured: Decimal | None
    applicable_premium: Decimal | None
    decision_rationale: str
    additional_terms: str | None
    decline_reason: str | None
    postponement_reason: str | None
    additional_requirements: str | None
    expected_reassessment_date: date | None
    referral_reason: str | None
    target_authority: str | None
    decision_notes: str | None
    supporting_document_ids: list[str]
    authority_reference: str
    guideline_reference: str
    authority_attested: bool
    information_requests_acknowledged: bool
    underwriter_subject: str
    decided_at: datetime


class DecisionReadinessOut(BaseModel):
    source_documents_total: int
    source_documents_complete: bool
    evidence_reviews_pending: int
    evidence_review_complete: bool
    pending_critical_flags: int
    outstanding_information_requests: int | None
    information_requests_tracked: bool
    underwriting_guidelines_available: bool
    authority_available: bool
    mandatory_prerequisites_met: bool
    underwriter_subject: str
    demo_case: bool


class UnderwritingDecisionHistoryOut(BaseModel):
    case: CaseSummary
    readiness: DecisionReadinessOut
    decisions: list[UnderwritingDecisionOut] = Field(default_factory=list)


class UnderwritingVarianceDecisionOut(ApiModel):
    id: str
    decision: Literal["retain_original", "accept_suggested", "custom_value", "refer", "reset"]
    selected_value: int | None
    justification: str
    reviewer_subject: str
    approval_status: str
    reviewed_at: datetime


class UnderwritingVarianceOut(ApiModel):
    id: str
    category: str
    title: str
    applied_value: int
    suggested_value: int
    difference: int
    currency: str
    recommendation_source: str
    recommendation_rationale: str
    status: Literal["pending", "resolved", "referred"]
    current_decision: UnderwritingVarianceDecisionOut | None
    history: list[UnderwritingVarianceDecisionOut] = Field(default_factory=list)


class UnderwritingVarianceWorkspaceOut(BaseModel):
    case: CaseSummary
    demo_mode: bool
    variances: list[UnderwritingVarianceOut]
    pending_variances: int
    resolved_variances: int
    total_variances: int
    cases_requiring_decision: int


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


class DocumentDeletionOut(BaseModel):
    document_id: str
    deleted: bool


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


class CaseReviewExceptionOut(BaseModel):
    id: str
    kind: Literal["field", "cross_document_conflict", "document"]
    category: str
    title: str
    status: Literal["pending", "resolved", "advisory"]
    severity: Literal["error", "warning", "info"]
    field_ids: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    message: str


class CaseReviewSummaryOut(BaseModel):
    open_flags: int = 0
    documents_analysed: int = 0
    cross_document_conflicts: int = 0
    resolved_flags: int = 0
    processing_documents: int = 0
    exceptions: list[CaseReviewExceptionOut] = Field(default_factory=list)


class ExtractionOut(ApiModel):
    document: DocumentSummary
    run: RunSummary | None
    fields: list[FieldOut]
    additional_facts: list[AdditionalFactOut] = Field(default_factory=list)


class ExtractionHistoryRunOut(BaseModel):
    run: RunSummary
    field_count: int
    pending_fields: int
    reviewed_fields: int


class ExtractionHistoryOut(BaseModel):
    document: DocumentSummary
    runs: list[ExtractionHistoryRunOut] = Field(default_factory=list)


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
    case_review: CaseReviewSummaryOut


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
