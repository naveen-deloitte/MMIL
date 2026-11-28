import type {
  ApiProblem,
  AuditPage,
  CaseCreateInput,
  CaseListItem,
  CaseSummary,
  DocumentDeletion,
  DocumentSummary,
  ExtractionHistory,
  IdentityReviewInput,
  IdentitySummary,
  IdentityVerifyInput,
  ReviewPayload,
  UnderwritingVarianceDecisionInput,
  UnderwritingVarianceWorkspace,
  UnderwritingDecisionHistory,
  UnderwritingDecisionInput,
  Workspace,
} from "./types";

export class ApiError extends Error {
  readonly problem: ApiProblem;

  constructor(problem: ApiProblem) {
    super(problem.detail);
    this.name = "ApiError";
    this.problem = problem;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let problem: ApiProblem = {
      title: "Request failed",
      status: response.status,
      detail: "The request could not be completed.",
      code: "request_failed",
      correlation_id: response.headers.get("X-Correlation-ID") ?? undefined,
    };
    try {
      const body = (await response.json()) as Partial<ApiProblem>;
      problem = { ...problem, ...body };
    } catch {
      // Keep the safe generic response and never expose an HTML/proxy body.
    }
    throw new ApiError(problem);
  }
  return (await response.json()) as T;
}

export function loadWorkspace(caseId: string): Promise<Workspace> {
  return request<Workspace>(`/api/v1/cases/${encodeURIComponent(caseId)}/workspace`);
}

export function loadCases(): Promise<CaseListItem[]> {
  return request<CaseListItem[]>("/api/v1/cases");
}

export function loadUnderwritingVariances(caseId: string): Promise<UnderwritingVarianceWorkspace> {
  return request<UnderwritingVarianceWorkspace>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/underwriting-variances`,
  );
}

export function loadUnderwritingDecisionHistory(caseId: string): Promise<UnderwritingDecisionHistory> {
  return request<UnderwritingDecisionHistory>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/underwriting-decisions`,
  );
}

export function submitUnderwritingDecision(
  caseId: string,
  payload: UnderwritingDecisionInput,
): Promise<UnderwritingDecisionHistory> {
  return request<UnderwritingDecisionHistory>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/underwriting-decisions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function recordUnderwritingVarianceDecision(
  caseId: string,
  varianceId: string,
  payload: UnderwritingVarianceDecisionInput,
): Promise<UnderwritingVarianceWorkspace> {
  return request<UnderwritingVarianceWorkspace>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/underwriting-variances/${encodeURIComponent(varianceId)}/decisions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function resetDemoUnderwritingVariance(caseId: string): Promise<UnderwritingVarianceWorkspace> {
  return request<UnderwritingVarianceWorkspace>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/underwriting-variances/demo-reset`,
    { method: "POST" },
  );
}

export function createCase(payload: CaseCreateInput): Promise<CaseSummary> {
  return request<CaseSummary>("/api/v1/cases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function uploadDocument(
  caseId: string,
  file: File,
  documentType:
    | "medical_report"
    | "kyc_individual"
    | "aadhaar_card"
    | "pan_card" = "medical_report",
): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);
  form.append("document_type", documentType);
  const idempotencyKey =
    typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const result = await request<{ document: DocumentSummary; replayed: boolean }>(
    `/api/v1/cases/${encodeURIComponent(caseId)}/documents`,
    {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: form,
    },
  );
  return result.document;
}

export function retryDocument(documentId: string): Promise<DocumentSummary> {
  return request<DocumentSummary>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/retry`,
    { method: "POST" },
  );
}

export function deleteDocument(documentId: string): Promise<DocumentDeletion> {
  return request<DocumentDeletion>(`/api/v1/documents/${encodeURIComponent(documentId)}`, {
    method: "DELETE",
  });
}

export function loadExtractionHistory(documentId: string): Promise<ExtractionHistory> {
  return request<ExtractionHistory>(
    `/api/v1/documents/${encodeURIComponent(documentId)}/extractions/history`,
  );
}

export async function submitReview(
  documentId: string,
  decision: ReviewPayload,
): Promise<void> {
  await request(`/api/v1/documents/${encodeURIComponent(documentId)}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decisions: [decision] }),
  });
}

export function loadAudit(caseId: string): Promise<AuditPage> {
  return request<AuditPage>(`/api/v1/cases/${encodeURIComponent(caseId)}/audit?limit=50`);
}

export function documentContentUrl(documentId: string, page: number): string {
  const base = `/api/v1/documents/${encodeURIComponent(documentId)}/content`;
  return `${base}#page=${Math.max(1, Math.trunc(page))}`;
}

export function loadIdentitySummary(caseId: string): Promise<IdentitySummary> {
  return request<IdentitySummary>(`/api/v1/cases/${encodeURIComponent(caseId)}/identity/summary`);
}

export function verifyIdentity(
  caseId: string,
  payload: IdentityVerifyInput,
): Promise<{ reused_existing: string[]; summary: IdentitySummary }> {
  return request(`/api/v1/cases/${encodeURIComponent(caseId)}/identity/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function submitIdentityReview(
  caseId: string,
  payload: IdentityReviewInput,
): Promise<IdentitySummary> {
  return request<IdentitySummary>(`/api/v1/cases/${encodeURIComponent(caseId)}/identity/review`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}
