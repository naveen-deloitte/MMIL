export type ProcessingStatus =
  | "uploaded"
  | "scanning"
  | "ocr"
  | "extracting"
  | "review_required"
  | "completed"
  | "failed"
  | "cancelled";

export type ReviewDecision =
  | "accepted"
  | "corrected"
  | "rejected"
  | "not_applicable";

export interface CaseSummary {
  id: string;
  external_case_id: string;
  applicant_display_name: string;
  proposal_number: string;
  product_name: string;
  workflow_stage: string;
  sla_label: string;
  assigned_at?: string | null;
  resolved_at?: string | null;
  priority?: string | null;
  sla_status?: string | null;
  final_decision?: string | null;
  decision_date?: string | null;
  underwriter_subject?: string | null;
  decision_rationale?: string | null;
  is_demo?: boolean;
}

export type VarianceDecisionType = "retain_original" | "accept_suggested" | "custom_value" | "refer";
export type VarianceStatus = "pending" | "resolved" | "referred";

export interface VarianceDecision {
  id: string;
  decision: VarianceDecisionType | "reset";
  selected_value: number | null;
  justification: string;
  reviewer_subject: string;
  approval_status: string;
  reviewed_at: string;
}

export interface UnderwritingVariance {
  id: string;
  category: string;
  title: string;
  applied_value: number;
  suggested_value: number;
  difference: number;
  currency: string;
  recommendation_source: string;
  recommendation_rationale: string;
  status: VarianceStatus;
  current_decision: VarianceDecision | null;
  history: VarianceDecision[];
}

export interface UnderwritingVarianceWorkspace {
  case: CaseSummary;
  demo_mode: boolean;
  variances: UnderwritingVariance[];
  pending_variances: number;
  resolved_variances: number;
  total_variances: number;
  cases_requiring_decision: number;
}

export interface UnderwritingVarianceDecisionInput {
  decision: VarianceDecisionType;
  selected_value?: number;
  justification: string;
}

export interface CaseListItem {
  case: CaseSummary;
  document_count: number;
  last_activity_at: string;
}

export interface CaseCreateInput {
  external_case_id: string;
  applicant_display_name: string;
  proposal_number: string;
  product_name: string;
}

export interface DocumentSummary {
  id: string;
  version: number;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  document_type: string;
  schema_version: string;
  status: ProcessingStatus;
  failure_code: string | null;
  page_count: number | null;
  viewable: boolean;
  created_at: string;
  job_id: string | null;
  attempts: number;
}

export interface DocumentDeletion {
  document_id: string;
  deleted: boolean;
}

export interface Citation {
  document_id: string;
  document_version: number;
  page: number;
  excerpt: string;
  bbox: Record<string, number> | null;
}

export interface ValidationFinding {
  code: string;
  severity: string;
  message?: string | null;
  rule?: string | null;
}

export interface ReviewRecord {
  id: string;
  version: number;
  decision: ReviewDecision;
  rationale: string | null;
  before_value: unknown;
  after_value: unknown;
  reviewer_subject: string;
  reviewed_at: string;
}

export interface EvidenceField {
  id: string;
  document_id: string;
  run_id: string;
  field_path: string;
  label: string;
  ui_section:
    | "summary"
    | "vitals"
    | "labs"
    | "checks"
    | "assessment"
    | "identity"
    | "contact"
    | "bank_details"
    | "supporting_documents"
    | "consent"
    | "additional";
  ui_group: string;
  source_literal: string | null;
  candidate_value: unknown;
  effective_value: unknown;
  data_type: string;
  unit: string | null;
  extraction_status: "found" | "uncertain" | "not_found";
  confidence: number | null;
  validations: ValidationFinding[];
  citations: Citation[];
  review_state: "pending" | ReviewDecision | "not_reviewable";
  review_version: number;
  latest_review: ReviewRecord | null;
}

export interface AdditionalFact {
  id: string;
  document_id: string;
  run_id: string;
  name: string;
  category: string;
  source_literal: string;
  value: unknown;
  data_type: string;
  unit: string | null;
  extraction_status: "found" | "uncertain";
  confidence: number;
  validations: ValidationFinding[];
  citations: Citation[];
  linked_field_path: string | null;
}

export interface RunSummary {
  id: string;
  document_id: string;
  sequence: number;
  status: string;
  document_type: string;
  schema_version: string;
  configuration_checksum: string;
  extractor_version: string;
  provider: string;
  model_version: string;
  prompt_version: string;
  started_at: string;
  completed_at: string | null;
  latency_ms: number | null;
  ai_analysis: AiAnalysis | null;
}

export interface GroundedStatement {
  text: string;
  citations: Citation[];
}

export interface AiAnalysis {
  summary: GroundedStatement | null;
  key_medical_findings: GroundedStatement[];
  recommendations: GroundedStatement[];
  vitals_summary: GroundedStatement | null;
  major_vital_factors: GroundedStatement[];
  lab_results: LabResult[];
  knockout_checks: KnockoutCheck[];
}

export interface LabResult {
  category: string;
  name: string;
  value: string;
  unit: string | null;
  reference_range: string | null;
  reported_flag: string | null;
  confidence: number;
  citations: Citation[];
}

export interface KnockoutCheck {
  factor: string;
  value: string;
  confidence: number;
  citations: Citation[];
}

export interface EvidenceCounts {
  found: number;
  uncertain: number;
  not_found: number;
  pending: number;
  accepted: number;
  corrected: number;
  rejected: number;
  not_applicable: number;
}

export interface Workspace {
  case: CaseSummary;
  documents: DocumentSummary[];
  runs: RunSummary[];
  fields: EvidenceField[];
  additional_facts: AdditionalFact[];
  counts: EvidenceCounts;
  case_review: CaseReviewSummary;
}

export type UnderwritingDecisionType = "approve" | "decline" | "postpone" | "refer";

export interface UnderwritingDecisionReadiness {
  source_documents_total: number;
  source_documents_complete: boolean;
  evidence_reviews_pending: number;
  evidence_review_complete: boolean;
  pending_critical_flags: number;
  outstanding_information_requests: number | null;
  information_requests_tracked: boolean;
  underwriting_guidelines_available: boolean;
  authority_available: boolean;
  mandatory_prerequisites_met: boolean;
  underwriter_subject: string;
  demo_case: boolean;
}

export interface UnderwritingDecisionRecord {
  id: string;
  decision: UnderwritingDecisionType;
  approved_sum_assured: string | number | null;
  applicable_premium: string | number | null;
  decision_rationale: string;
  additional_terms: string | null;
  decline_reason: string | null;
  postponement_reason: string | null;
  additional_requirements: string | null;
  expected_reassessment_date: string | null;
  referral_reason: string | null;
  target_authority: string | null;
  decision_notes: string | null;
  supporting_document_ids: string[];
  authority_reference: string;
  guideline_reference: string;
  underwriter_subject: string;
  decided_at: string;
}

export interface UnderwritingDecisionHistory {
  case: CaseSummary;
  readiness: UnderwritingDecisionReadiness;
  decisions: UnderwritingDecisionRecord[];
}

export interface UnderwritingDecisionInput {
  decision: UnderwritingDecisionType;
  approved_sum_assured?: string;
  applicable_premium?: string;
  decision_rationale?: string;
  additional_terms?: string;
  decline_reason?: string;
  postponement_reason?: string;
  additional_requirements?: string;
  expected_reassessment_date?: string;
  referral_reason?: string;
  target_authority?: string;
  decision_notes?: string;
  supporting_document_ids?: string[];
  authority_reference?: string;
  guideline_reference?: string;
  authority_attested?: boolean;
  information_requests_acknowledged?: boolean;
}

export interface CaseReviewException {
  id: string;
  kind: "field" | "cross_document_conflict" | "document";
  category: string;
  title: string;
  status: "pending" | "resolved" | "advisory";
  severity: "error" | "warning" | "info";
  field_ids: string[];
  document_ids: string[];
  message: string;
}

export interface CaseReviewSummary {
  open_flags: number;
  documents_analysed: number;
  cross_document_conflicts: number;
  resolved_flags: number;
  processing_documents: number;
  exceptions: CaseReviewException[];
}

export interface ExtractionHistoryRun {
  run: RunSummary;
  field_count: number;
  pending_fields: number;
  reviewed_fields: number;
}

export interface ExtractionHistory {
  document: DocumentSummary;
  runs: ExtractionHistoryRun[];
}

export interface AuditEvent {
  id: string;
  actor_subject: string;
  action: string;
  outcome: string;
  correlation_id: string;
  metadata: Record<string, unknown>;
  occurred_at: string;
  document_id: string | null;
  run_id: string | null;
  field_id: string | null;
}

export interface AuditPage {
  items: AuditEvent[];
  next_offset: number | null;
}

export interface ApiProblem {
  type?: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  correlation_id?: string;
}

export interface ReviewPayload {
  field_id: string;
  decision: ReviewDecision;
  expected_version: number;
  corrected_value?: unknown;
  rationale?: string;
}

export type IdentitySubject = "aadhaar" | "pan";
export type MatchStatus =
  | "match"
  | "normalized_match"
  | "review_required"
  | "mismatch"
  | "not_available"
  | "not_applicable";
export type VerificationStatus =
  | "not_verified"
  | "not_configured"
  | "verified"
  | "failed"
  | "consent_missing"
  | "provider_error";

export interface IdentityDocument {
  subject: IdentitySubject;
  state: "not_uploaded" | "processing" | "failed" | "extracted";
  document_id: string | null;
  filename: string | null;
  document_status: string | null;
  failure_code: string | null;
  action_required: string | null;
  extraction_confidence: number | null;
  fields: EvidenceField[];
}

export interface IdentityFinding {
  subject: IdentitySubject;
  field_path: string;
  status: "passed" | "warning" | "failed";
  rule: string;
  reason: string;
  citation: Record<string, unknown> | null;
}

export interface IdentityMatch {
  field: string;
  label: string;
  kyc_value: string | null;
  aadhaar_value: string | null;
  pan_value: string | null;
  match_status: MatchStatus;
  confidence: number;
  explanation: string;
  pairs: Array<{ left: string; right: string; status: MatchStatus; reason: string }>;
  not_applicable_sources: string[];
  missing_sources: string[];
}

export interface IdentityVerification {
  subject: IdentitySubject;
  status: VerificationStatus;
  configured: boolean;
  provider: string | null;
  reason_code: string | null;
  verified_at: string | null;
  consent_given: boolean | null;
}

export interface IdentityIssue {
  code: string;
  category: string;
  severity: "info" | "warning" | "error";
  message: string;
  subject: IdentitySubject | null;
  field: string | null;
}

export interface IdentityReview {
  status: "not_started" | "completed" | "stale";
  decision: string | null;
  rationale: string | null;
  reviewer_subject: string | null;
  reviewed_at: string | null;
  resolved_fields: string[];
}

export interface IdentitySummary {
  case_id: string;
  fingerprint: string;
  kyc_present: boolean;
  documents: IdentityDocument[];
  stages: {
    document_uploaded: Record<string, string>;
    information_extracted: Record<string, string>;
    format_validated: Record<string, string>;
    kyc_matched: string;
    authenticity_verified: Record<string, string>;
    human_review_completed: string;
  };
  match_status: MatchStatus;
  matches: IdentityMatch[];
  findings: IdentityFinding[];
  verification: IdentityVerification[];
  review: IdentityReview;
  issues: IdentityIssue[];
}

export interface IdentityVerifyInput {
  subjects: IdentitySubject[];
  consent: { given: boolean; purpose: string };
  pan_number?: string;
}

export interface IdentityReviewInput {
  decision: "confirmed" | "rejected" | "follow_up_required";
  rationale?: string;
  resolved_fields: string[];
}
