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
    | "consent";
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
