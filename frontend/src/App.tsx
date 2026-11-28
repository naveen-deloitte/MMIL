import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  createCase,
  deleteDocument,
  loadExtractionHistory,
  loadCases,
  loadAudit,
  loadWorkspace,
  retryDocument,
  submitReview,
  uploadDocument,
} from "./api";
import { advisoryNotes, isAutoAccepted } from "./advisory";
import { DashboardWorkload } from "./components/DashboardWorkload";
import { UnderwritingDecisionCockpit } from "./components/UnderwritingDecisionCockpit";
import {
  DemoCaseWorkspace,
  UnderwritingVarianceReview,
} from "./components/UnderwritingVariance";
import { DrawerShell } from "./components/Drawers";
import {
  AdditionalFactsView,
  EvidenceRow,
  KnockoutChecksView,
  LabReportsView,
  SummaryView,
  VitalsView,
} from "./components/EvidenceViews";
import {
  AssessmentFindings,
  AssessmentKpis,
  ProposedPremiumPrompt,
  TermsComparison,
  useCaseAssessment,
} from "./components/CaseAssessment";
import { IdentityVerificationView } from "./components/IdentityViews";
import { FinancialViews } from "./components/FinancialViews";
import { KycViews, kycViews } from "./components/KycViews";
import { ProductSelector } from "./components/ProductSelector";
import { ProposalDetails, useProposal } from "./components/ProposalDetails";
import { ProposalViewer } from "./components/ProposalViewer";
import { SourceViewer } from "./components/SourceViewer";
import { ReviewDialog } from "./components/ReviewDialog";
import {
  initialSourceSelection,
  selectCitation,
  selectDocument,
  type SourceSelection,
} from "./sourceState";
import type {
  AdditionalFact,
  AuditEvent,
  CaseCreateInput,
  CaseListItem,
  CaseSummary,
  Citation,
  DocumentSummary,
  ExtractionHistory,
  EvidenceField,
  ProductSelection,
  ReviewPayload,
  Workspace,
} from "./types";

type MedicalView = "summary" | "vitals" | "lab-reports" | "knockout-checks" | "additional-facts";
type CaseSection =
  | "Document Review"
  | "HITL Review"
  | "Case Evidence"
  | "Identity Verification"
  | "Underwriting Assessment"
  | "Underwriting Variance Review";
type AssessmentView = "Overview" | "Underwriting" | "Decision" | "Ask AI" | "Audit";
type UploadDocumentType =
  | "medical_report"
  | "kyc_individual"
  | "aadhaar_card"
  | "pan_card"
  | "financial_document";
const identityDocumentTypes = new Set(["aadhaar_card", "pan_card"]);
// Documents reviewed as a plain list of extracted fields (no medical/KYC tabs).
const fieldListDocumentTypes = new Set([...identityDocumentTypes, "financial_document", "proposal_form"]);

const caseSections: CaseSection[] = [
  "Document Review",
  "HITL Review",
  "Case Evidence",
  "Identity Verification",
  "Underwriting Assessment",
  "Underwriting Variance Review",
];

const assessmentViews: AssessmentView[] = [
  "Overview",
  "Underwriting",
  "Decision",
  "Ask AI",
  "Audit",
];

const underwritingSections = [
  "Medical evidence",
  "Financial review",
  "Occupation & lifestyle",
  "TSAR & compliance",
  "Agent report",
  "Fraud review",
  "Reinsurance",
] as const;

const medicalViews: Array<{ id: MedicalView; label: string }> = [
  { id: "summary", label: "AI Summary" },
  { id: "vitals", label: "Vitals" },
  { id: "lab-reports", label: "Lab Reports" },
  { id: "knockout-checks", label: "Knockout Checks" },
  { id: "additional-facts", label: "AI Selected Facts" },
];

const activeStatuses = new Set(["uploaded", "scanning", "ocr", "extracting"]);
const DEMO_CASE_ID = "MMIL-DEMO-001";

export default function App() {
  const [activeCaseId, setActiveCaseId] = useState<string | null>(readCaseId);
  const [caseItems, setCaseItems] = useState<CaseListItem[]>([]);
  const [demoCase, setDemoCase] = useState<CaseSummary | null>(null);
  const [demoCaseError, setDemoCaseError] = useState<string | null>(null);
  const [caseListLoading, setCaseListLoading] = useState(true);
  const [caseListError, setCaseListError] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(Boolean(readCaseId()));
  const [aiPanelOpen, setAiPanelOpen] = useState(true);
  const [pageError, setPageError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  // Document whose "processing is queued" message stays visible until processing finishes.
  const [trackedUploadId, setTrackedUploadId] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<CaseSection>("Document Review");
  const [activeView, setActiveView] = useState<string>("summary");
  const [assessmentView, setAssessmentView] = useState<AssessmentView>("Overview");
  const [activeUnderwritingSection, setActiveUnderwritingSection] =
    useState<(typeof underwritingSections)[number]>("Medical evidence");
  const [uploadDocumentType, setUploadDocumentType] = useState<UploadDocumentType>("medical_report");
  const [source, setSource] = useState<SourceSelection>(() => initialSourceSelection(readCaseId() ?? ""));
  const [reviewField, setReviewField] = useState<EvidenceField | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);
  const [history, setHistory] = useState<ExtractionHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [hitlDocumentType, setHitlDocumentType] = useState("all");
  const [hitlStatus, setHitlStatus] = useState("pending");
  const [removalDocument, setRemovalDocument] = useState<DocumentSummary | null>(null);
  const [removalBusy, setRemovalBusy] = useState(false);
  const [removalError, setRemovalError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async (quiet = false) => {
    if (!activeCaseId) return;
    try {
      const next = await loadWorkspace(activeCaseId);
      setWorkspace(next);
      setPageError(null);
    } catch (error) {
      setPageError(messageFor(error));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [activeCaseId]);

  const refreshCases = useCallback(async () => {
    setCaseListLoading(true);
    setCaseListError(null);
    const [casesResult, demoResult] = await Promise.allSettled([
      loadCases(),
      activeCaseId ? Promise.resolve(null) : loadWorkspace(DEMO_CASE_ID),
    ]);

    if (casesResult.status === "fulfilled") {
      setCaseItems(Array.isArray(casesResult.value) ? casesResult.value : []);
    } else {
      setCaseListError(messageFor(casesResult.reason));
    }

    if (demoResult.status === "fulfilled") {
      const demoSummary = demoResult.value?.case;
      if (demoSummary?.is_demo && demoSummary.external_case_id === DEMO_CASE_ID) {
        setDemoCase(demoSummary);
        setDemoCaseError(null);
      } else {
        setDemoCase(null);
        setDemoCaseError(null);
      }
    } else if (activeCaseId) {
      setDemoCase(null);
      setDemoCaseError(null);
    } else {
      setDemoCase(null);
      setDemoCaseError(messageFor(demoResult.reason));
    }
    setCaseListLoading(false);
  }, [activeCaseId]);

  useEffect(() => {
    void refreshCases();
    if (activeCaseId) {
      void refresh();
    } else {
      setWorkspace(null);
      setLoading(false);
    }
  }, [activeCaseId, refresh, refreshCases]);

  useEffect(() => {
    const handlePopState = () => {
      const nextCaseId = readCaseId();
      setActiveCaseId(nextCaseId);
      setWorkspace(null);
      setLoading(Boolean(nextCaseId));
      setPageError(null);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const processing = workspace?.documents.some((document) => activeStatuses.has(document.status));
  // Replace the "queued" message once the tracked upload reaches a final status.
  useEffect(() => {
    if (!trackedUploadId || !workspace) return;
    const tracked = workspace.documents.find((item) => item.id === trackedUploadId);
    if (!tracked) return;
    if (tracked.status === "completed") {
      setNotice(`${tracked.filename} processed.`);
    } else if (tracked.status === "review_required") {
      setNotice(`${tracked.filename} processed. Some fields need your review.`);
    } else if (tracked.status === "failed" || tracked.status === "cancelled") {
      setNotice(`${tracked.filename} could not be processed. Retry it from Documents.`);
    } else {
      return;
    }
    setTrackedUploadId(null);
  }, [trackedUploadId, workspace]);

  // Hide messages automatically, except while an upload is still being processed.
  useEffect(() => {
    if (!notice || trackedUploadId || notice.startsWith("Uploading ")) return;
    const timer = window.setTimeout(() => setNotice(""), 5000);
    return () => window.clearTimeout(timer);
  }, [notice, trackedUploadId]);

  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(() => void refresh(true), 1800);
    return () => window.clearInterval(timer);
  }, [processing, refresh]);

  useEffect(() => {
    if (!workspace) return;
    if (!workspace.documents.some((document) => document.id === activeDocumentId)) {
      setActiveDocumentId(workspace.documents[0]?.id ?? null);
    }
  }, [activeDocumentId, workspace]);

  const latestDocument = workspace?.documents[0] ?? null;
  const selectedDocument = workspace?.documents.find((item) => item.id === activeDocumentId) ?? latestDocument;
  const latestRun = workspace?.runs.find((run) => run.document_id === selectedDocument?.id);
  const latestDocumentFields = workspace?.fields.filter(
    (field) => field.document_id === selectedDocument?.id,
  ) ?? [];
  const isKycDocument = selectedDocument?.document_type === "kyc_individual";
  const isIdentityDocument = identityDocumentTypes.has(selectedDocument?.document_type ?? "");
  const isFieldListDocument = fieldListDocumentTypes.has(selectedDocument?.document_type ?? "");
  const visibleViews = isKycDocument ? kycViews : medicalViews;
  const activeKycView = kycViews.find((view) => view.id === activeView)?.id ?? "overview";
  const selectedView = isKycDocument ? activeKycView : activeView;
  const canGenerateSummary = Boolean(
    selectedDocument
      && ["completed", "review_required"].includes(selectedDocument.status)
      && latestRun
      && latestRun.provider !== "deterministic-local"
      && !latestRun.ai_analysis?.summary,
  );
  const canReprocessLocal = Boolean(
    selectedDocument
      && ["completed", "review_required"].includes(selectedDocument.status)
      && latestRun?.provider === "deterministic-local",
  );

  useEffect(() => {
    if (!selectedDocument) {
      setHistory(null);
      setHistoryError(null);
      return;
    }
    let cancelled = false;
    setHistoryLoading(true);
    setHistoryError(null);
    void loadExtractionHistory(selectedDocument.id)
      .then((result) => {
        if (!cancelled) setHistory(result);
      })
      .catch((error: unknown) => {
        if (!cancelled) setHistoryError(messageFor(error));
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedDocument?.id, latestRun?.id]);

  function navigateToCase(caseId: string | null) {
    const url = new URL(window.location.href);
    if (caseId) url.searchParams.set("case", caseId);
    else url.searchParams.delete("case");
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setActiveCaseId(caseId);
    setWorkspace(null);
    setPageError(null);
    setLoading(Boolean(caseId));
    setActiveDocumentId(null);
    setHistory(null);
    setSource((current) => ({ ...current, open: false }));
  }

  async function handleCreateCase(input: CaseCreateInput) {
    const created = await createCase(input);
    setNotice(`${created.external_case_id} was created.`);
    navigateToCase(created.external_case_id);
  }

  async function handleUpload(file: File | undefined) {
    if (!file) return;
    setNotice(`Uploading ${file.name}…`);
    try {
      const caseId = workspace?.case.external_case_id;
      if (!caseId) throw new Error("Open a case before uploading a document.");
      const document = await uploadDocument(caseId, file, uploadDocumentType);
      setActiveSection(
        identityDocumentTypes.has(document.document_type) ? "Identity Verification" : "Document Review",
      );
      setActiveDocumentId(document.id);
      setActiveView(document.document_type === "kyc_individual" ? "overview" : "summary");
      setNotice(`${document.filename} uploaded. Processing is queued.`);
      setTrackedUploadId(document.id);
      await refresh(true);
      setSource((current) => selectDocument(current, caseId, document));
    } catch (error) {
      setNotice(messageFor(error));
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function openSource(document?: DocumentSummary) {
    const target = document ?? selectedDocument;
    if (!target) {
      setNotice("Upload a document before opening the source viewer.");
      return;
    }
    setSource((current) => selectDocument(current, workspace?.case.external_case_id ?? "", target));
  }

  function openCitation(item: EvidenceField | AdditionalFact, citationIndex = 0) {
    const citation = item.citations[citationIndex];
    if (!citation) return;
    setSource((current) => selectCitation(current, workspace?.case.external_case_id ?? "", item.id, citation));
    const label = "label" in item ? item.label : item.name;
    setNotice(`Opened ${label} source on page ${citation.page}.`);
  }

  function openAnalysisCitation(citation: Citation) {
    setSource((current) =>
      selectCitation(current, workspace?.case.external_case_id ?? "", "ai-analysis", citation),
    );
    setNotice(`Opened AI analysis source on page ${citation.page}.`);
  }

  async function handleReview(payload: ReviewPayload) {
    if (!reviewField) return;
    setReviewBusy(true);
    setReviewError(null);
    try {
      await submitReview(reviewField.document_id, payload);
      setNotice(`${reviewField.label} review saved.`);
      setReviewField(null);
      await refresh(true);
    } catch (error) {
      if (error instanceof ApiError && error.problem.code === "stale_review") {
        setReviewError("Another reviewer changed this field. The page has been refreshed; compare the current decision before saving again.");
        await refresh(true);
      } else {
        setReviewError(messageFor(error));
      }
    } finally {
      setReviewBusy(false);
    }
  }

  async function handleRetry(document: DocumentSummary) {
    try {
      await retryDocument(document.id);
      setNotice(`${document.filename} was queued for retry.`);
      setTrackedUploadId(document.id);
      await refresh(true);
    } catch (error) {
      setNotice(messageFor(error));
    }
  }

  async function handleRemoveDocument(document: DocumentSummary) {
    setRemovalBusy(true);
    setRemovalError(null);
    try {
      const result = await deleteDocument(document.id);
      if (!result.deleted) throw new Error("The document was not removed.");
      setTrackedUploadId((current) => current === document.id ? null : current);
      setSource((current) => current.documentId === document.id ? { ...current, open: false } : current);
      setReviewField((current) => current?.document_id === document.id ? null : current);
      setRemovalDocument(null);
      setNotice(`${document.filename} and its extracted evidence were permanently removed.`);
      await refresh(true);
      await refreshCases();
    } catch (error) {
      setRemovalError(messageFor(error));
    } finally {
      setRemovalBusy(false);
    }
  }

  async function loadAuditHistory() {
    setAuditLoading(true);
    setAuditError(null);
    try {
      const page = await loadAudit(workspace?.case.external_case_id ?? "");
      setAuditEvents(page.items);
    } catch (error) {
      setAuditError(messageFor(error));
    } finally {
      setAuditLoading(false);
    }
  }

  const fieldDocumentNames = useMemo(
    () => new Map(workspace?.documents.map((document) => [document.id, document.filename]) ?? []),
    [workspace?.documents],
  );

  if (!activeCaseId) {
    return (
      <CasesHome
        cases={caseItems}
        demoCase={demoCase}
        demoCaseError={demoCaseError}
        loading={caseListLoading}
        error={caseListError}
        notice={notice}
        onCreate={handleCreateCase}
        onOpen={(caseId) => navigateToCase(caseId)}
        onRefresh={() => void refreshCases()}
      />
    );
  }

  if (loading) {
    return <div className="page-state" role="status"><div className="spinner" /><h1>Loading evidence workspace…</h1></div>;
  }
  if (!workspace || pageError) {
    return (
      <div className="page-state" role="alert">
        <div className="logo">MMIL</div>
        <h1>Evidence workspace unavailable</h1>
        <p>{pageError ?? "The case could not be loaded."}</p>
        <button type="button" className="primary-button" onClick={() => { setLoading(true); void refresh(); }}>Try again</button>
      </div>
    );
  }

  if (workspace.case.is_demo) {
    return (
      <DemoCaseWorkspace
        caseSummary={workspace.case}
        onBack={() => navigateToCase(null)}
      />
    );
  }

  return (
    <div className="application-shell">
      <header className="global-header">
        <div className="brand-lockup">
          <div className="logo">MMIL</div>
          <div><strong>Mahindra Manulife<br />Operations Workbench</strong><span>NB & UW · Policy servicing · Claims</span></div>
        </div>
        <div className="header-controls">
          <label className="role-picker">
            View as role
            <select aria-label="View as role" defaultValue="underwriter">
              <option value="underwriter">Underwriter</option>
              <option value="nb_ops">NB & UW Operations</option>
            </select>
          </label>
        </div>
      </header>

      <section className="case-header" aria-labelledby="case-title">
        <div>
          <button type="button" className="back-button" onClick={() => navigateToCase(null)} title="Back to dashboard"><span aria-hidden="true">←</span> Dashboard</button>
          <h1 id="case-title">{workspace.case.applicant_display_name} · {workspace.case.external_case_id}</h1>
          <div className="tag-row">
            <span className="tag info">{workspace.case.product_name}</span>
            <span className="tag neutral">{workspace.case.proposal_number}</span>
            <span className="tag warning">UW review</span>
            <span className="tag success">SLA {workspace.case.sla_label}</span>
          </div>
        </div>
        <div className="case-actions">
          <input
            ref={fileInput}
            className="visually-hidden"
            id="document-upload"
            type="file"
            accept="application/pdf,image/jpeg,image/png,image/tiff"
            onChange={(event) => void handleUpload(event.target.files?.[0])}
          />
          <label className="upload-type-control">
            <span>Document type</span>
            <select
              aria-label="Document type"
              value={uploadDocumentType}
              onChange={(event) => {
                const value = event.target.value;
                if (
                  value === "medical_report"
                  || value === "kyc_individual"
                  || value === "aadhaar_card"
                  || value === "pan_card"
                  || value === "financial_document"
                ) {
                  setUploadDocumentType(value);
                }
              }}
            >
              <option value="medical_report">Medical report</option>
              <option value="kyc_individual">Individual KYC</option>
              <option value="aadhaar_card">Aadhaar Card</option>
              <option value="pan_card">PAN Card</option>
              <option value="financial_document">Financial document</option>
            </select>
          </label>
          <button type="button" className="primary-button" onClick={() => fileInput.current?.click()}>Add document</button>
          <button type="button" className="secondary-button" onClick={() => setReviewDrawerOpen(true)}>Request requirements</button>
          <button type="button" className="secondary-button" onClick={() => setActiveSection("Document Review")}>Manage documents <span className="button-count">{workspace.documents.length}</span></button>
          <button type="button" className="secondary-button" onClick={() => openSource()}>View source</button>
          <button type="button" className="secondary-button" onClick={() => setActiveSection("HITL Review")}>
            HITL review <span className="button-count">{workspace.case_review.open_flags}</span>
          </button>
          <button type="button" className="primary-button" onClick={() => { setActiveSection("Underwriting Assessment"); setAssessmentView("Decision"); }}>Decision cockpit</button>
        </div>
      </section>

      <ProgressStrip document={selectedDocument} />

      <main className={`main-layout ${aiPanelOpen ? "" : "ai-collapsed"}`}>
        <button
          type="button"
          className="ai-panel-toggle"
          aria-label={aiPanelOpen ? "Hide review panel" : "Show review panel"}
          aria-controls="ai-decision-panel"
          aria-expanded={aiPanelOpen}
          title={aiPanelOpen ? "Hide review panel" : "Show review panel"}
          onClick={() => setAiPanelOpen((current) => !current)}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="3.5" y="4" width="17" height="16" rx="1.5" />
            <path d={aiPanelOpen ? "M15 4v16M8 9l3 3-3 3" : "M15 4v16M11 9l-3 3 3 3"} />
          </svg>
        </button>
        <section className="evidence-pane" aria-label={isKycDocument ? "KYC review" : "Medical evidence"}>
          <nav className="case-section-tabs" aria-label="Case workspace sections">
            {caseSections.map((section) => (
              <button
                type="button"
                key={section}
                className={activeSection === section ? "active" : ""}
                aria-current={activeSection === section ? "page" : undefined}
                onClick={() => {
                  setActiveSection(section);
                }}
              >
                {section}
              </button>
            ))}
          </nav>
          <div className="evidence-scroll">
            {activeSection === "Document Review" ? (
              <>
                <DocumentReviewHeader
                  documents={workspace.documents}
                  document={selectedDocument}
                  history={history}
                  historyLoading={historyLoading}
                  historyError={historyError}
                  onSelect={(document) => setActiveDocumentId(document.id)}
                  onOpenSource={openSource}
                  onRetry={(document) => void handleRetry(document)}
                  onRemove={(document) => {
                    setRemovalError(null);
                    setRemovalDocument(document);
                  }}
                />
                {!isFieldListDocument ? (
                <nav className="medical-tabs" aria-label={isKycDocument ? "KYC assessment views" : "Medical assessment views"}>
                  {visibleViews.map((view) => (
                    <button
                      key={view.id}
                      type="button"
                      className={selectedView === view.id ? "active" : ""}
                      aria-current={selectedView === view.id ? "page" : undefined}
                      onClick={() => setActiveView(view.id)}
                    >
                      {view.label}
                      {(view.id === "summary" || view.id === "overview")
                        && latestDocumentFields.filter((field) => field.review_state === "pending").length
                        ? <span>{latestDocumentFields.filter((field) => field.review_state === "pending").length}</span>
                        : null}
                    </button>
                  ))}
                </nav>
                ) : null}
                {!selectedDocument ? (
                  <div className="section-empty-state">
                    <strong>No documents uploaded</strong>
                    <p>Add a document to review extracted fields and source citations.</p>
                  </div>
                ) : selectedDocument.document_type === "financial_document" ? (
                  <FinancialViews
                    document={selectedDocument}
                    fields={latestDocumentFields}
                    emptyMessage={
                      selectedDocument.status === "failed"
                        ? `Processing failed${selectedDocument.failure_code ? `: ${selectedDocument.failure_code.replaceAll("_", " ")}` : ""}. Retry from the document list.`
                        : "No extracted fields yet."
                    }
                    onCitation={openCitation}
                    onReview={(item) => { setReviewError(null); setReviewField(item); }}
                  />
                ) : isFieldListDocument ? (
                  <div className="identity-document-fields">
                    {latestDocumentFields.length === 0 ? (
                      <p className="data-note">
                        {selectedDocument.status === "failed"
                          ? isIdentityDocument
                            ? "Processing failed. Open Identity Verification for the action required."
                            : `Processing failed${selectedDocument.failure_code ? `: ${selectedDocument.failure_code.replaceAll("_", " ")}` : ""}. Retry from the document list.`
                          : "No extracted fields yet."}
                      </p>
                    ) : null}
                    {latestDocumentFields.map((field) => (
                      <EvidenceRow
                        key={field.id}
                        field={field}
                        onCitation={openCitation}
                        onReview={(item) => { setReviewError(null); setReviewField(item); }}
                      />
                    ))}
                    <p className="data-note">
                      {isIdentityDocument
                        ? "Open Identity Verification for matching and verification status."
                        : selectedDocument.document_type === "proposal_form"
                          ? "Values on the proposal form are applicant declarations. See Case overview › Proposal & policy details."
                          : "Extracted values are used in the case assessment once reviewed."}
                    </p>
                  </div>
                ) : isKycDocument ? (
                  <KycViews
                    activeView={activeKycView}
                    document={selectedDocument}
                    fields={latestDocumentFields}
                    onCitation={openCitation}
                    onReview={(field) => { setReviewError(null); setReviewField(field); }}
                  />
                ) : (
                  <>
                    {activeView === "summary" ? (
                      <SummaryView
                        fields={latestDocumentFields}
                        analysis={latestRun?.ai_analysis ?? null}
                        canGenerateSummary={canGenerateSummary}
                        canReprocessLocal={canReprocessLocal}
                        isLocalRun={latestRun?.provider === "deterministic-local"}
                        onGenerateSummary={() => {
                          if (selectedDocument) void handleRetry(selectedDocument);
                        }}
                        onReprocessLocal={() => {
                          if (selectedDocument) void handleRetry(selectedDocument);
                        }}
                        onAiCitation={openAnalysisCitation}
                        onCitation={openCitation}
                        onReview={(field) => {
                          setReviewError(null);
                          setReviewField(field);
                        }}
                      />
                    ) : null}
                    {activeView === "vitals" ? <VitalsView fields={latestDocumentFields} analysis={latestRun?.ai_analysis ?? null} onAiCitation={openAnalysisCitation} onCitation={openCitation} onReview={(field) => { setReviewError(null); setReviewField(field); }} /> : null}
                    {activeView === "lab-reports" ? <LabReportsView results={latestRun?.ai_analysis?.lab_results ?? []} onCitation={openAnalysisCitation} /> : null}
                    {activeView === "knockout-checks" ? <KnockoutChecksView checks={latestRun?.ai_analysis?.knockout_checks ?? []} onCitation={openAnalysisCitation} /> : null}
                    {activeView === "additional-facts" ? <AdditionalFactsView facts={workspace.additional_facts.filter((fact) => fact.document_id === selectedDocument?.id)} onCitation={openCitation} /> : null}
                    <p className="data-note">Extracted candidates require human review before use as case evidence. No underwriting or clinical decision is made here.</p>
                  </>
                )}
              </>
            ) : null}
            {activeSection === "Identity Verification" ? (
              <IdentityVerificationView
                caseId={workspace.case.external_case_id}
                refreshKey={`${workspace.counts.pending}-${workspace.counts.accepted}-${workspace.counts.corrected}-${workspace.counts.rejected}-${workspace.documents.map((item) => `${item.id}:${item.status}`).join(",")}`}
                onCitation={openCitation}
                onReview={(field) => { setReviewError(null); setReviewField(field); }}
                onOpenDocument={(documentId) => {
                  const target = workspace.documents.find((item) => item.id === documentId);
                  if (target) {
                    setActiveDocumentId(documentId);
                    openSource(target);
                  }
                }}
                onChanged={() => void refresh(true)}
              />
            ) : null}
            {activeSection === "Underwriting Variance Review" ? (
              <UnderwritingVarianceReview caseId={workspace.case.external_case_id} />
            ) : null}
            {activeSection === "HITL Review" ? (
              <HitlReviewSection
                workspace={workspace}
                documentType={hitlDocumentType}
                status={hitlStatus}
                documentNames={fieldDocumentNames}
                onDocumentTypeChange={setHitlDocumentType}
                onStatusChange={setHitlStatus}
                onReview={(field) => { setReviewError(null); setReviewField(field); }}
                onCitation={openCitation}
                onSelectDocument={(documentId) => {
                  setActiveDocumentId(documentId);
                  setActiveSection("Document Review");
                }}
                onRetry={(document) => void handleRetry(document)}
              />
            ) : null}
            {activeSection === "Case Evidence" ? (
              <CaseEvidenceSection
                workspace={workspace}
                documentNames={fieldDocumentNames}
                onCitation={openCitation}
                onReview={(field) => { setReviewError(null); setReviewField(field); }}
                onSelectDocument={(documentId) => {
                  setActiveDocumentId(documentId);
                  setActiveSection("Document Review");
                }}
              />
            ) : null}
            {activeSection === "Underwriting Assessment" ? (
              <>
                <nav className="medical-tabs assessment-tabs" aria-label="Underwriting assessment views">
                  {assessmentViews.map((view) => (
                    <button
                      key={view}
                      type="button"
                      className={assessmentView === view ? "active" : ""}
                      aria-current={assessmentView === view ? "page" : undefined}
                      onClick={() => {
                        setAssessmentView(view);
                        if (view === "Audit") void loadAuditHistory();
                      }}
                    >
                      {view}
                    </button>
                  ))}
                </nav>
                {assessmentView === "Overview" ? (
                  <OverviewSection
                    workspace={workspace}
                    onOpenDocuments={() => setActiveSection("Document Review")}
                    onOpenAssessment={() => setActiveSection("Document Review")}
                    onOpenReview={() => setActiveSection("HITL Review")}
                    onAiCitation={openAnalysisCitation}
                    onCaseUpdated={() => void refresh(true)}
                    onOpenDocument={(documentId) => {
                      const target = workspace.documents.find((item) => item.id === documentId);
                      if (target) openSource(target);
                    }}
                  />
                ) : null}
                {assessmentView === "Underwriting" ? (
                  <UnderwritingSection
                    sections={underwritingSections}
                    activeSection={activeUnderwritingSection}
                    onSelect={setActiveUnderwritingSection}
                    isKycDocument={isKycDocument}
                    document={selectedDocument}
                    fields={latestDocumentFields}
                    caseInfo={{
                      applicant: workspace.case.applicant_display_name,
                      caseId: workspace.case.external_case_id,
                      proposal: workspace.case.proposal_number,
                    }}
                    onOpenAssessment={() => setActiveSection("Document Review")}
                    onOpenReview={() => setActiveSection("HITL Review")}
                    onCitation={openCitation}
                    onReview={(field) => { setReviewError(null); setReviewField(field); }}
                  />
                ) : null}
                {assessmentView === "Decision" ? (
                  <DecisionSection
                    workspace={workspace}
                    onAiCitation={openAnalysisCitation}
                    onReview={() => setActiveSection("HITL Review")}
                    onRequirements={() => setReviewDrawerOpen(true)}
                    onOpenAssessment={() => setActiveSection("Document Review")}
                    onDecisionRecorded={() => { void refresh(true); void refreshCases(); }}
                  />
                ) : null}
                {assessmentView === "Ask AI" ? (
                  <AskAiSection
                    onOpenAssessment={() => setActiveSection("Document Review")}
                    onReview={() => setActiveSection("HITL Review")}
                  />
                ) : null}
                {assessmentView === "Audit" ? (
                  <AuditSection events={auditEvents} loading={auditLoading} error={auditError} />
                ) : null}
              </>
            ) : null}
          </div>
        </section>

        <aside id="ai-decision-panel" className="permanent-ai-panel" aria-label="AI decision support" inert={!aiPanelOpen}>
          <div className="ai-panel-inner">
            <ReviewRail
              workspace={workspace}
              documentNames={fieldDocumentNames}
              onReview={(field) => { setReviewError(null); setReviewField(field); }}
              onCitation={(field) => openCitation(field)}
            />
          </div>
        </aside>

        {source.open ? (
          <SourceViewer
            documents={workspace.documents}
            selection={source}
            onClose={() => setSource((current) => ({ ...current, open: false }))}
            onDocumentChange={(document) => setSource((current) => selectDocument(current, workspace.case.external_case_id, document))}
            onPageChange={(page) => setSource((current) => ({ ...current, page, excerpt: null, fieldId: null }))}
          />
        ) : null}

      </main>

      <div className="live-region" aria-live="polite" aria-atomic="true">{notice}</div>

      {reviewField ? (
        <ReviewDialog
          field={workspace.fields.find((field) => field.id === reviewField.id) ?? reviewField}
          busy={reviewBusy}
          error={reviewError}
          onClose={() => !reviewBusy && setReviewField(null)}
          onSubmit={handleReview}
          onViewSource={() => { setReviewField(null); openCitation(reviewField); }}
        />
      ) : null}
      {reviewDrawerOpen ? (
        <DrawerShell
          title="Evidence review"
          eyebrow="Human-in-the-loop review"
          onClose={() => setReviewDrawerOpen(false)}
          closeLabel="Close evidence review"
          drawerClassName="review-queue-drawer"
          contentClassName="review-drawer-content"
        >
          <ReviewRail
            workspace={workspace}
            documentNames={fieldDocumentNames}
            onReview={(field) => {
              setReviewDrawerOpen(false);
              setReviewError(null);
              setReviewField(field);
            }}
            onCitation={(field) => {
              setReviewDrawerOpen(false);
              openCitation(field);
            }}
          />
        </DrawerShell>
      ) : null}
      {removalDocument ? (
        <DeleteDocumentDialog
          document={removalDocument}
          busy={removalBusy}
          error={removalError}
          onCancel={() => !removalBusy && setRemovalDocument(null)}
          onConfirm={() => void handleRemoveDocument(removalDocument)}
        />
      ) : null}
    </div>
  );
}

function CasesHome({
  cases,
  demoCase,
  demoCaseError,
  loading,
  error,
  notice,
  onCreate,
  onOpen,
  onRefresh,
}: {
  cases: CaseListItem[];
  demoCase: CaseSummary | null;
  demoCaseError: string | null;
  loading: boolean;
  error: string | null;
  notice: string;
  onCreate: (input: CaseCreateInput) => Promise<void>;
  onOpen: (caseId: string) => void;
  onRefresh: () => void;
}) {
  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState<CaseCreateInput>({
    external_case_id: "",
    applicant_display_name: "",
    proposal_number: "",
    product_name: "",
  });
  const [productSelection, setProductSelection] = useState<ProductSelection | null>(null);
  // Free-text product entry is only offered when no product catalogue is configured.
  const [catalogueAvailable, setCatalogueAvailable] = useState<boolean | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [proposalCaseId, setProposalCaseId] = useState<string | null>(null);
  const refreshedAt = useMemo(
    () => (loading || error ? null : new Date()),
    [cases, error, loading],
  );

  async function submitCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (catalogueAvailable && !productSelection) {
      setFormError("Select an insurance product.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const { product_name, ...identity } = form;
      await onCreate(
        catalogueAvailable && productSelection
          ? { ...identity, product: productSelection }
          : { ...identity, product_name },
      );
    } catch (submitError) {
      setFormError(messageFor(submitError));
    } finally {
      setSaving(false);
    }
  }

  function updateField(field: keyof CaseCreateInput, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  return (
    <div className="application-shell case-home-shell">
      <header className="global-header">
        <div className="brand-lockup">
          <div className="logo">MMIL</div>
          <div><strong>Mahindra Manulife<br />Operations Workbench</strong></div>
        </div>
        <div className="header-controls">
          <span className="current-role"><span aria-hidden="true">●</span> Underwriter</span>
        </div>
      </header>
      <main className="cases-page">
        <section className="dashboard-welcome">
          <div>
            <span className="eyebrow">UNDERWRITING OPERATIONS</span>
            <h1>Underwriting Workbench</h1>
            <p>Review cases and keep your workload moving.</p>
          </div>
          <div className="dashboard-welcome-actions">
            <small>{refreshedAt ? `Last updated ${refreshedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : "Last updated —"}</small>
            <button type="button" className="secondary-button" onClick={onRefresh} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
            <button type="button" className="primary-button" onClick={() => { setFormOpen(true); setFormError(null); }}>
              Create new case
            </button>
          </div>
        </section>

        {notice ? <div className="notice blue cases-notice" role="status">{notice}</div> : null}
        {error ? (
          <div className="case-error" role="alert">
            <span>{error}</span>
            <button type="button" className="text-button" onClick={onRefresh}>Try again</button>
          </div>
        ) : null}

        {formOpen ? (
          <section className="case-create-panel" aria-labelledby="create-case-title">
            <div className="case-create-heading">
              <div><span className="eyebrow">New workspace</span><h2 id="create-case-title">Create a case</h2></div>
              <button
                type="button"
                className="icon-button"
                aria-label="Close create case form"
                onClick={() => setFormOpen(false)}
              >
                ×
              </button>
            </div>
            <form onSubmit={(event) => void submitCase(event)}>
              <div className="case-form-grid">
                <label className="form-field">
                  Case ID
                  <input
                    required
                    minLength={3}
                    maxLength={100}
                    pattern="[A-Za-z0-9][A-Za-z0-9._-]{2,99}"
                    value={form.external_case_id}
                    onChange={(event) => updateField("external_case_id", event.target.value)}
                    placeholder="e.g. UW-2027-001234"
                  />
                </label>
                <label className="form-field">
                  Applicant name
                  <input
                    required
                    maxLength={200}
                    value={form.applicant_display_name}
                    onChange={(event) => updateField("applicant_display_name", event.target.value)}
                  />
                </label>
                <label className="form-field">
                  Proposal number
                  <input
                    required
                    maxLength={100}
                    value={form.proposal_number}
                    onChange={(event) => updateField("proposal_number", event.target.value)}
                  />
                </label>
                {catalogueAvailable === false ? (
                  <label className="form-field">
                    Product
                    <input
                      required
                      maxLength={200}
                      value={form.product_name ?? ""}
                      onChange={(event) => updateField("product_name", event.target.value)}
                    />
                  </label>
                ) : null}
              </div>
              <ProductSelector
                onCatalogueLoaded={(list) => setCatalogueAvailable(list.catalogue_configured && list.items.length > 0)}
                onChange={(selection) => setProductSelection(selection)}
              />
              {formError ? <div className="form-error" role="alert">{formError}</div> : null}
              <div className="case-form-actions">
                <button type="button" className="secondary-button" onClick={() => setFormOpen(false)} disabled={saving}>
                  Cancel
                </button>
                <button type="submit" className="primary-button" disabled={saving}>
                  {saving ? "Creating…" : "Create case"}
                </button>
              </div>
            </form>
          </section>
        ) : null}

        {loading ? (
          <div className="dashboard-loading" role="status"><div className="spinner" />Loading underwriting cases…</div>
        ) : null}
        {!loading && !error ? (
          <DashboardWorkload
            cases={cases}
            demoCase={demoCase}
            demoCaseError={demoCaseError}
            onOpen={onOpen}
            onCreateCase={() => { setFormOpen(true); setFormError(null); }}
            onViewProposal={setProposalCaseId}
          />
        ) : null}
      </main>
      {proposalCaseId ? (
        <ProposalViewer caseId={proposalCaseId} onClose={() => setProposalCaseId(null)} />
      ) : null}
      <div className="live-region" aria-live="polite" aria-atomic="true">{notice}</div>
    </div>
  );
}

function readCaseId(): string | null {
  const caseId = new URLSearchParams(window.location.search).get("case")?.trim();
  return caseId || null;
}

function ProgressStrip({ document }: { document: DocumentSummary | null }) {
  const steps = [
    ["uploaded", "Uploaded"],
    ["scanning", "Safety scan"],
    ["ocr", "Text & OCR"],
    ["extracting", "Extraction"],
    ["review_required", "Human review"],
    ["completed", "Evidence complete"],
  ] as const;
  const status = document?.status;
  const currentIndex = status ? steps.findIndex(([id]) => id === status) : -1;
  return (
    <section className="progress-strip" aria-label="Document processing progress">
      <ol>
        {steps.map(([id, label], index) => (
          <li key={id} className={index < currentIndex || status === "completed" ? "done" : index === currentIndex ? "current" : ""}>
            <span className="progress-dot" />
            <span>{label}</span>
          </li>
        ))}
      </ol>
      <div className="progress-summary">
        <span><strong>Current focus:</strong> {document ? document.status.replaceAll("_", " ") : "Waiting for a document"}</span>
        <span><strong>Next action:</strong> {nextAction(document)}</span>
      </div>
    </section>
  );
}

function nextAction(document: DocumentSummary | null): string {
  if (!document) return "Upload a medical report or KYC form";
  if (document.status === "review_required") return "Review pending candidate fields";
  if (document.status === "completed") return "Evidence review is complete";
  if (document.status === "failed") return `Resolve ${document.failure_code?.replaceAll("_", " ") ?? "processing failure"} and retry`;
  return "The worker is processing the immutable source";
}

function ReviewRail({
  workspace,
  documentNames,
  onReview,
  onCitation,
}: {
  workspace: Workspace;
  documentNames: Map<string, string>;
  onReview: (field: EvidenceField) => void;
  onCitation: (field: EvidenceField) => void;
}) {
  const pending = workspace.fields.filter((field) => field.review_state === "pending");
  const advisories = advisoryNotes(workspace.fields);
  const autoAccepted = workspace.fields.filter(isAutoAccepted).length;
  return (
    <div className="review-rail" aria-label="Evidence review status">
      <div className="rail-summary">
        <span className="eyebrow">{pending.length ? "Human review required" : "No critical issues"}</span>
        <strong>{workspace.counts.pending} critical item{workspace.counts.pending === 1 ? "" : "s"} to review</strong>
        <p>Only suspicious values are sent here. Advisory notes are listed below and do not block completion.</p>
      </div>
      <div className="rail-counts rail-counts-4">
        <div><strong>{autoAccepted}</strong><span>Auto-accepted</span></div>
        <div><strong>{workspace.counts.accepted - autoAccepted}</strong><span>Accepted</span></div>
        <div><strong>{workspace.counts.corrected}</strong><span>Corrected</span></div>
        <div><strong>{workspace.counts.rejected}</strong><span>Rejected</span></div>
      </div>
      <div className="rail-findings">
        <h3>Critical · needs review</h3>
        {!pending.length ? <p className="quiet-message">No critical items.</p> : null}
        {pending.slice(0, 12).map((field) => (
          <article key={field.id}>
            <button type="button" onClick={() => onReview(field)}>
              <span className="pending-marker" aria-hidden="true">○</span>
              <span><strong>{field.label}</strong><small>{documentNames.get(field.document_id) ?? "Source document"}</small></span>
              <span aria-hidden="true">+</span>
            </button>
            {field.citations.length ? <button className="rail-source" type="button" onClick={() => onCitation(field)}>Page {field.citations[0].page}</button> : null}
          </article>
        ))}

        <h3 className="advisory-heading">Advisory notes <span>{advisories.length}</span></h3>
        {!advisories.length ? <p className="quiet-message">No advisory notes.</p> : null}
        <ul className="advisory-list">
          {advisories.map((note) => (
            <li key={note.key} className={note.priority === "high" ? "high" : ""}>
              <div>
                <strong>{note.field.label}</strong>
                <span className="advisory-tag">{note.label}</span>
              </div>
              {note.message ? <p>{note.message}</p> : null}
              <div className="advisory-actions">
                <small>{documentNames.get(note.field.document_id) ?? "Source document"}</small>
                {note.field.citations.length ? (
                  <button type="button" className="text-button" onClick={() => onCitation(note.field)}>Page {note.field.citations[0].page}</button>
                ) : null}
                {note.field.candidate_value !== null ? (
                  <button type="button" className="text-button" onClick={() => onReview(note.field)}>Review</button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function OverviewSection({
  workspace,
  onOpenDocuments,
  onOpenAssessment,
  onOpenReview,
  onAiCitation,
  onCaseUpdated,
  onOpenDocument,
}: {
  workspace: Workspace;
  onOpenDocuments: () => void;
  onOpenAssessment: () => void;
  onOpenReview: () => void;
  onAiCitation: (citation: Citation) => void;
  onCaseUpdated: () => void;
  onOpenDocument: (documentId: string) => void;
}) {
  const { case: caseInfo, documents, counts, fields } = workspace;
  const refreshKey = workspaceRefreshKey(workspace);
  const assessment = useCaseAssessment(caseInfo.external_case_id, refreshKey);
  const proposal = useProposal(caseInfo.external_case_id, `${refreshKey}|${assessment.view?.latest?.version ?? 0}`);
  const policy = (caseInfo.policy_details ?? null) as {
    rating_inputs?: { age?: number | null; gender?: string | null } | null;
  } | null;
  const pending = fields.filter((field) => field.review_state === "pending").length;
  const completeness = documents.length > 0 && fields.length > 0;
  const nextAction = documents.length === 0
    ? "Add the application or evidence documents to start a source-linked review."
    : pending > 0
      ? `${pending} extracted candidate${pending === 1 ? "" : "s"} need human review before use as evidence.`
      : "Review the available assessment and confirm whether more evidence is needed.";

  return (
    <div className="case-overview">
      <div className="section-intro">
        <div><span className="eyebrow">Underwriting workspace</span><h2>Case overview</h2></div>
        <span className="tag neutral">{caseInfo.workflow_stage.replaceAll("_", " ")}</span>
      </div>
      <AssessmentKpis view={assessment.view} loading={assessment.loading} error={assessment.error} />
      <ProposedPremiumPrompt
        caseId={caseInfo.external_case_id}
        view={assessment.view}
        onUpdated={() => {
          onCaseUpdated();
          void assessment.reload();
        }}
      />
      <div className="overview-proposal-layout">
        <section className="card-section">
          <div className="section-heading"><h3>Applicant profile</h3></div>
          <OverviewRow label="Life assured" value={caseInfo.applicant_display_name} />
          <OverviewRow
            label="Age / gender"
            value={policy?.rating_inputs?.age != null || policy?.rating_inputs?.gender
              ? `${policy?.rating_inputs?.age ?? "—"} / ${policy?.rating_inputs?.gender ?? "—"}`
              : "Not supplied"}
          />
          <OverviewRow label="City" value="Not supplied" />
          <OverviewRow label="Case ID" value={caseInfo.external_case_id} />
          <OverviewRow label="Workflow stage" value={caseInfo.workflow_stage.replaceAll("_", " ")} />
          <OverviewRow label="SLA" value={caseInfo.sla_label || "Not supplied"} />
          <p className="analysis-disclaimer">
            Occupation, annual income and channel are shown in Proposal & policy details with their source.
          </p>
        </section>
        <ProposalDetails
          view={proposal.view}
          loading={proposal.loading}
          error={proposal.error}
          onRetry={() => void proposal.reload()}
          onCitation={onAiCitation}
          onOpenProposal={() => {
            if (proposal.view?.proposal_document) onOpenDocument(proposal.view.proposal_document.id);
          }}
        />
      </div>
      <AssessmentFindings
        view={assessment.view}
        loading={assessment.loading}
        error={assessment.error}
        refreshing={assessment.refreshing}
        canRefresh
        onRefresh={() => void assessment.refresh()}
        onCitation={onAiCitation}
      />
      <div className="overview-insights-grid">
        <section className="card-section">
          <div className="section-heading"><h3>Risk heatmap</h3></div>
          <div className="overview-heatmap">
            <OverviewHeatCell title="KYC" value={documents.some((doc) => doc.document_type === "kyc_individual") ? "Evidence available" : "Not supplied"} />
            <OverviewHeatCell title="AML" value="Not connected" />
            <OverviewHeatCell title="Medical" value={documents.some((doc) => doc.document_type === "medical_report") ? "Review evidence" : "Not supplied"} warning={documents.some((doc) => doc.document_type === "medical_report")} />
            <OverviewHeatCell title="Financial" value={documents.some((doc) => doc.document_type === "financial_document") ? "Evidence available" : "Not supplied"} />
            <OverviewHeatCell title="IIB" value="Not connected" />
            <OverviewHeatCell title="Fraud" value="Not connected" />
          </div>
          <p className="analysis-disclaimer">Status reflects connected document availability only; it is not an underwriting risk assessment.</p>
        </section>
        <section className="card-section">
          <div className="section-heading"><h3>Data completeness</h3></div>
          <ul className="check-list overview-checklist">
            <li><span className="complete-mark">✓</span><div><strong>Case and proposal identifiers available</strong><small>Applicant, proposal, product and workflow are linked.</small></div></li>
            <li><span className={documents.length ? "complete-mark" : "pending-mark"}>{documents.length ? "✓" : "!"}</span><div><strong>{documents.length ? "Source documents attached" : "Source documents required"}</strong><small>{documents.length ? `${documents.length} document${documents.length === 1 ? "" : "s"} on the case.` : "Upload a medical report or individual KYC document."}</small></div></li>
            <li><span className={completeness ? "pending-mark" : "complete-mark"}>{completeness ? "!" : "✓"}</span><div><strong>{pending ? "Human evidence review required" : "Evidence review status"}</strong><small>{pending ? `${pending} candidate fields remain pending.` : completeness ? "No candidate fields are pending." : "Evidence extraction has not started."}</small></div></li>
          </ul>
        </section>
        <section className="card-section">
          <div className="section-heading"><h3>Next best actions</h3></div>
          <p className="quiet-message">{nextAction}</p>
          <div className="overview-action-list">
            {pending > 0 ? <button type="button" className="secondary-button" onClick={onOpenReview}>Review pending evidence <span className="button-count">{pending}</span></button> : null}
            <button type="button" className="secondary-button" onClick={onOpenAssessment}>Open AI assessment</button>
            <button type="button" className="secondary-button" onClick={onOpenDocuments}>View documents</button>
          </div>
          <p className="analysis-disclaimer">Actions support review; no recommendation automatically approves or declines a case.</p>
        </section>
      </div>
    </div>
  );
}

function OverviewKpi({ label, value, detail, tone }: { label: string; value: number | string; detail: string; tone?: "warning" | "success" }) {
  return (
    <article className={`overview-kpi ${tone ?? ""}`}>
      <span>{label}</span><strong>{value}</strong><small>{detail}</small>
    </article>
  );
}

function OverviewRow({ label, value }: { label: string; value: string }) {
  return <div className="overview-row"><span>{label}</span><strong>{value}</strong></div>;
}

function OverviewHeatCell({ title, value, warning = false }: { title: string; value: string; warning?: boolean }) {
  return <div className={warning ? "heat-cell warning" : "heat-cell"}><strong>{title}</strong><span>{value}</span></div>;
}

/**
 * Sections whose evidence comes from the customer or a third party, so a document can be requested.
 * TSAR, agent, fraud and reinsurance come from internal systems and are not requested by email.
 */
const documentRequestSections: ReadonlySet<string> = new Set([
  "Medical evidence",
  "Financial review",
  "Occupation & lifestyle",
]);

/** Field sections that hold medical evidence. Bank, identity, contact and consent fields belong to other tabs. */
const medicalUiSections: ReadonlySet<EvidenceField["ui_section"]> = new Set([
  "summary",
  "vitals",
  "labs",
  "checks",
  "assessment",
]);

/** Opens the user's mail app with a prefilled document request. Recipient is left blank on purpose. */
function buildDocumentRequestMailto(
  caseInfo: { applicant: string; caseId: string; proposal: string },
  section: string,
): string {
  const subject = `Document request: ${section} - ${caseInfo.caseId}`;
  const body = [
    "Hello,",
    "",
    `To continue the underwriting review, please share the supporting document(s) for "${section}".`,
    "",
    `Case ID: ${caseInfo.caseId}`,
    `Proposal number: ${caseInfo.proposal}`,
    `Life assured: ${caseInfo.applicant}`,
    "",
    "Documents required:",
    "- ",
    "",
    "Thank you.",
  ].join("\r\n");
  return `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function UnderwritingSection({
  sections,
  activeSection,
  onSelect,
  isKycDocument,
  document,
  fields,
  caseInfo,
  onOpenAssessment,
  onOpenReview,
  onCitation,
  onReview,
}: {
  sections: readonly string[];
  activeSection: string;
  onSelect: (section: (typeof underwritingSections)[number]) => void;
  isKycDocument: boolean;
  document: DocumentSummary | null;
  fields: EvidenceField[];
  caseInfo: { applicant: string; caseId: string; proposal: string };
  onOpenAssessment: () => void;
  onOpenReview: () => void;
  onCitation: (field: EvidenceField) => void;
  onReview: (field: EvidenceField) => void;
}) {
  const selectedFields = fields.filter((field) => {
    if (activeSection === "Medical evidence") return medicalUiSections.has(field.ui_section);
    if (activeSection === "TSAR & compliance") return field.ui_section === "identity" || field.ui_section === "consent";
    if (activeSection === "Financial review") return field.ui_section === "bank_details";
    return false;
  });
  const hasConnectedEvidence = selectedFields.length > 0;

  return (
    <div className="underwriting-section">
      <div className="section-intro">
        <div><span className="eyebrow">Case assessment</span><h2>Underwriting</h2></div>
        <span className="tag neutral">{document ? document.filename : "No source document"}</span>
      </div>
      <nav className="underwriting-subnav" aria-label="Underwriting assessment areas">
        {sections.map((section) => (
          <button type="button" key={section} className={activeSection === section ? "active" : ""} onClick={() => {
            onSelect(section as (typeof underwritingSections)[number]);
          }}>{section}</button>
        ))}
      </nav>
      {activeSection === "Medical evidence" || activeSection === "TSAR & compliance" || activeSection === "Financial review" ? (
        <section className="card-section">
          <div className="section-heading">
            <div><h3>{activeSection}</h3><p>Source-linked candidates from the uploaded document. No underwriting decision is inferred.</p></div>
            {fields.some((field) => field.review_state === "pending") ? <button type="button" className="secondary-button compact" onClick={onOpenReview}>Open evidence review</button> : null}
          </div>
          {hasConnectedEvidence ? (
            <div className="evidence-list">
              {selectedFields.map((field) => (
                <article className="evidence-row" key={field.id}>
                  <div className="evidence-value-block">
                    <div className="evidence-label-line"><h4>{field.label}</h4><span className={`status-badge status-${field.review_state}`}>{field.review_state.replaceAll("_", " ")}</span></div>
                    <div className="field-value">{String(field.effective_value ?? "Not found")}</div>
                    {field.citations[0] ? <div className="citation-preview">Source citation · page {field.citations[0].page}<blockquote>{field.citations[0].excerpt}</blockquote></div> : null}
                  </div>
                  <div className="field-actions">
                    {field.review_state !== "not_reviewable" ? <button type="button" className="text-button" onClick={() => onReview(field)}>Review</button> : null}
                    {field.citations.length ? <button type="button" className="text-button" onClick={() => onCitation(field)}>View source</button> : null}
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <div className="section-empty-state">
              <strong>{isKycDocument && activeSection === "TSAR & compliance"
                ? "Identity evidence is not included in this document."
                : isKycDocument && activeSection === "Medical evidence"
                  ? "This is a KYC document. Medical evidence is not included in it."
                  : "No connected evidence for this section."}</strong>
              <p>Upload the relevant case document or connect the approved source before assessing this area.</p>
              <div className="section-empty-actions">
                {documentRequestSections.has(activeSection) ? (
                  <a className="primary-button" href={buildDocumentRequestMailto(caseInfo, activeSection)}>Ask for document</a>
                ) : null}
                <button type="button" className="secondary-button" onClick={onOpenAssessment}>Open AI assessment</button>
              </div>
            </div>
          )}
        </section>
      ) : (
        <section className="card-section section-empty-state">
          <span className="eyebrow">Source not connected</span>
          <h3>{activeSection}</h3>
          <p>This workspace currently provides source-linked medical and individual KYC evidence. No financial, lifestyle, agent, fraud or reinsurance data is available for this case; status is intentionally left unassessed.</p>
          <div className="section-empty-actions">
            {documentRequestSections.has(activeSection) ? (
              <a className="primary-button" href={buildDocumentRequestMailto(caseInfo, activeSection)}>Ask for document</a>
            ) : null}
            <button type="button" className="secondary-button" onClick={onOpenAssessment}>Review available evidence</button>
          </div>
        </section>
      )}
    </div>
  );
}

function DocumentReviewHeader({
  documents,
  document,
  history,
  historyLoading,
  historyError,
  onSelect,
  onOpenSource,
  onRetry,
  onRemove,
}: {
  documents: DocumentSummary[];
  document: DocumentSummary | null;
  history: ExtractionHistory | null;
  historyLoading: boolean;
  historyError: string | null;
  onSelect: (document: DocumentSummary) => void;
  onOpenSource: (document: DocumentSummary) => void;
  onRetry: (document: DocumentSummary) => void;
  onRemove: (document: DocumentSummary) => void;
}) {
  return (
    <section className="document-review-header card-section" aria-label="Selected document review">
      <div className="section-intro">
        <div>
          <span className="eyebrow">Document-level evidence</span>
          <h2>Document Review</h2>
          <p>Select a source to inspect its extracted fields, citations, and processing history.</p>
        </div>
        {documents.length ? (
          <label className="document-select-control">
            <span>Selected document</span>
            <select
              aria-label="Selected document"
              value={document?.id ?? ""}
              onChange={(event) => {
                const next = documents.find((item) => item.id === event.target.value);
                if (next) onSelect(next);
              }}
            >
              {documents.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.filename} · {item.document_type.replaceAll("_", " ")}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      {document ? (
        <>
          <div className="document-review-summary">
            <div>
              <strong>{document.filename}</strong>
              <span>{document.document_type.replaceAll("_", " ")} · Version {document.version} · {document.page_count ?? "—"} pages</span>
              <span className={`status-badge status-${document.status}`}>{document.status.replaceAll("_", " ")}</span>
            </div>
            <div className="document-actions">
              <button type="button" className="secondary-button compact" onClick={() => onOpenSource(document)}>View source</button>
              {document.status === "failed" ? (
                <button type="button" className="text-button" onClick={() => onRetry(document)}>Retry processing</button>
              ) : null}
              <button type="button" className="danger-button compact" onClick={() => onRemove(document)}>Remove document</button>
            </div>
          </div>
          <details className="extraction-history" open>
            <summary>Extraction history</summary>
            {historyLoading ? <p role="status">Loading extraction history…</p> : null}
            {historyError ? <p role="alert" className="form-error">{historyError}</p> : null}
            {!historyLoading && !historyError && history?.runs.length === 0 ? (
              <p className="quiet-message">No extraction runs are available for this document yet.</p>
            ) : null}
            {history?.runs.length ? (
              <ol className="history-list">
                {history.runs.map(({ run, field_count, pending_fields, reviewed_fields }) => (
                  <li key={run.id}>
                    <div>
                      <strong>Run {run.sequence}</strong>
                      <span className={`status-badge status-${run.status}`}>{run.status.replaceAll("_", " ")}</span>
                      <small>{new Date(run.started_at).toLocaleString()} · {run.provider} · {run.extractor_version}</small>
                    </div>
                    <p>{field_count} extracted fields · {pending_fields} pending · {reviewed_fields} reviewed</p>
                  </li>
                ))}
              </ol>
            ) : null}
          </details>
        </>
      ) : (
        <div className="section-empty-state">
          <strong>No documents uploaded</strong>
          <p>Add a document to review extracted fields and source citations.</p>
        </div>
      )}
    </section>
  );
}

function DeleteDocumentDialog({
  document: documentToRemove,
  busy,
  error,
  onCancel,
  onConfirm,
}: {
  document: DocumentSummary;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const cancelButton = useRef<HTMLButtonElement>(null);
  const busyRef = useRef(busy);
  const cancelRef = useRef(onCancel);
  busyRef.current = busy;
  cancelRef.current = onCancel;
  useEffect(() => {
    cancelButton.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) cancelRef.current();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <div
      className="drawer-backdrop delete-document-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onCancel();
      }}
    >
      <section
        className="delete-document-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="delete-document-title"
        aria-describedby="delete-document-warning"
      >
        <span className="eyebrow">Permanent action</span>
        <h2 id="delete-document-title">Remove {documentToRemove.filename}?</h2>
        <p id="delete-document-warning">
          This permanently deletes the original file, extracted evidence, reviews, and extraction history.
          A minimal audit event is retained. This cannot be undone.
        </p>
        {error ? <p role="alert" className="form-error">{error}</p> : null}
        <div className="dialog-actions">
          <button ref={cancelButton} type="button" className="secondary-button" disabled={busy} onClick={onCancel}>Cancel</button>
          <button type="button" className="danger-button" disabled={busy} onClick={onConfirm}>
            {busy ? "Removing…" : "Permanently remove"}
          </button>
        </div>
      </section>
    </div>
  );
}

function HitlReviewSection({
  workspace,
  documentType,
  status,
  documentNames,
  onDocumentTypeChange,
  onStatusChange,
  onReview,
  onCitation,
  onSelectDocument,
  onRetry,
}: {
  workspace: Workspace;
  documentType: string;
  status: string;
  documentNames: Map<string, string>;
  onDocumentTypeChange: (value: string) => void;
  onStatusChange: (value: string) => void;
  onReview: (field: EvidenceField) => void;
  onCitation: (field: EvidenceField) => void;
  onSelectDocument: (documentId: string) => void;
  onRetry: (document: DocumentSummary) => void;
}) {
  const documentTypes = [...new Set(workspace.documents.map((document) => document.document_type))];
  const fieldsById = new Map(workspace.fields.map((field) => [field.id, field]));
  const documentsById = new Map(workspace.documents.map((document) => [document.id, document]));
  const exceptions = workspace.case_review.exceptions.filter((item) => {
    const matchesStatus = status === "all" || item.status === status;
    const matchesType = documentType === "all" || item.document_ids.some(
      (id) => documentsById.get(id)?.document_type === documentType,
    );
    return matchesStatus && matchesType;
  });
  const processingDocuments = workspace.documents.filter((document) =>
    activeStatuses.has(document.status),
  );

  return (
    <section className="workbench-section hitl-review-section">
      <div className="section-intro">
        <div><span className="eyebrow">Case-level human review</span><h2>HITL Review</h2><p>Exceptions are derived from extraction, validation, processing, and cross-document comparisons.</p></div>
        <span className="tag warning">{workspace.case_review.open_flags} open flags</span>
      </div>
      <div className="case-review-metrics" aria-label="Case review summary">
        <div><strong>{workspace.case_review.open_flags}</strong><span>Open flags</span></div>
        <div><strong>{workspace.case_review.documents_analysed}</strong><span>Documents analysed</span></div>
        <div><strong>{workspace.case_review.cross_document_conflicts}</strong><span>Cross-document conflicts</span></div>
        <div><strong>{workspace.case_review.resolved_flags}</strong><span>Resolved flags</span></div>
      </div>
      {processingDocuments.length ? (
        <div className="processing-notices">
          <h3>Processing in progress</h3>
          {processingDocuments.map((document) => (
            <p key={document.id}>
              <span className={`status-badge status-${document.status}`}>{document.status.replaceAll("_", " ")}</span>
              {" "}{document.filename} is still processing. Its extracted results will appear here when the run completes.
            </p>
          ))}
        </div>
      ) : null}
      <div className="hitl-filters">
        <label>
          Document type
          <select aria-label="Filter by document type" value={documentType} onChange={(event) => onDocumentTypeChange(event.target.value)}>
            <option value="all">All document types</option>
            {documentTypes.map((type) => <option key={type} value={type}>{type.replaceAll("_", " ")}</option>)}
          </select>
        </label>
        <label>
          Review status
          <select aria-label="Filter by review status" value={status} onChange={(event) => onStatusChange(event.target.value)}>
            <option value="pending">Open / pending</option>
            <option value="all">All statuses</option>
            <option value="resolved">Resolved</option>
            <option value="advisory">Advisory</option>
          </select>
        </label>
      </div>
      {exceptions.length ? (
        <div className="case-exception-list">
          {exceptions.map((exception) => (
            <article className={`case-exception-card exception-${exception.status}`} key={exception.id}>
              <div className="case-exception-heading">
                <div><span className={`tag ${exception.severity === "error" ? "danger" : exception.severity === "info" ? "success" : "warning"}`}>{exception.category}</span><h3>{exception.title}</h3></div>
                <span className={`status-badge status-${exception.status}`}>{exception.status}</span>
              </div>
              <p>{exception.message}</p>
              {exception.document_ids.length ? (
                <div className="exception-document-links">
                  {exception.document_ids.map((id) => (
                    <button type="button" className="text-button" key={id} onClick={() => onSelectDocument(id)}>
                      {documentNames.get(id) ?? "Open source document"}
                    </button>
                  ))}
                </div>
              ) : null}
              {exception.field_ids.map((fieldId) => {
                const field = fieldsById.get(fieldId);
                if (!field) return null;
                return (
                  <div className="exception-field-row" key={field.id}>
                    <span><strong>{field.label}:</strong> {formatEvidenceValue(field.effective_value)}</span>
                    <div>
                      {field.citations.length ? <button type="button" className="text-button" onClick={() => onCitation(field)}>Page {field.citations[0].page}</button> : null}
                      {field.review_state === "pending" ? <button type="button" className="secondary-button compact" onClick={() => onReview(field)}>Review field</button> : null}
                    </div>
                  </div>
                );
              })}
              {exception.kind === "document" && exception.document_ids.some((id) => documentsById.get(id)?.status === "failed") ? (
                <button type="button" className="secondary-button compact" onClick={() => {
                  const failed = exception.document_ids.map((id) => documentsById.get(id)).find((item) => item?.status === "failed");
                  if (failed) onRetry(failed);
                }}>Retry processing</button>
              ) : null}
            </article>
          ))}
        </div>
      ) : (
        <div className="section-empty-state">
          <strong>{status === "pending" ? "No open review exceptions" : "No exceptions match these filters"}</strong>
          <p>Advisory and completed items are available by changing the review-status filter.</p>
        </div>
      )}
      <p className="data-note">Field corrections and decisions use the existing versioned, audited review flow. Additional facts remain source-only and are not independently reviewable.</p>
    </section>
  );
}

function CaseEvidenceSection({
  workspace,
  documentNames,
  onCitation,
  onReview,
  onSelectDocument,
}: {
  workspace: Workspace;
  documentNames: Map<string, string>;
  onCitation: (item: EvidenceField | AdditionalFact) => void;
  onReview: (field: EvidenceField) => void;
  onSelectDocument: (documentId: string) => void;
}) {
  const groupedFields = new Map<string, EvidenceField[]>();
  for (const field of workspace.fields) {
    const group = groupedFields.get(field.field_path) ?? [];
    group.push(field);
    groupedFields.set(field.field_path, group);
  }
  const conflictStatusByField = new Map<string, "pending" | "resolved">();
  for (const exception of workspace.case_review.exceptions) {
    if (exception.kind !== "cross_document_conflict") continue;
    for (const fieldId of exception.field_ids) {
      conflictStatusByField.set(fieldId, exception.status === "resolved" ? "resolved" : "pending");
    }
  }

  return (
    <section className="workbench-section case-evidence-section">
      <div className="section-intro">
        <div><span className="eyebrow">Cross-document evidence</span><h2>Case Evidence</h2><p>Values remain linked to their source document; no conflicting value is selected as authoritative.</p></div>
        <span className="tag warning">{workspace.case_review.cross_document_conflicts} conflicts</span>
      </div>
      {!groupedFields.size && !workspace.additional_facts.length ? (
        <div className="section-empty-state">
          <strong>No extracted case evidence yet</strong>
          <p>Evidence will be grouped here after documents have completed extraction.</p>
        </div>
      ) : null}
      {[...groupedFields.entries()].map(([fieldPath, fields]) => {
        const conflictStatuses = fields
          .map((field) => conflictStatusByField.get(field.id))
          .filter((status): status is "pending" | "resolved" => status !== undefined);
        const conflict = conflictStatuses.length > 0;
        const resolvedConflict = conflict && conflictStatuses.every((status) => status === "resolved");
        return (
          <section className="case-evidence-group card-section" key={fieldPath}>
            <div className="section-heading">
              <div><span className="eyebrow">{fields[0].ui_group}</span><h3>{fields[0].label}</h3><small>{fieldPath}</small></div>
              <span className={`tag ${conflict ? resolvedConflict ? "success" : "warning" : "neutral"}`}>
                {conflict ? resolvedConflict ? "Conflict reviewed · no source selected" : "Conflict · review sources" : `${fields.length} source${fields.length === 1 ? "" : "s"}`}
              </span>
            </div>
            {fields.map((field) => (
              <article className="case-evidence-value" key={field.id}>
                <div>
                  <strong>{formatEvidenceValue(field.candidate_value)}</strong>
                  <span>{documentNames.get(field.document_id) ?? "Source document"} · {field.unit ?? field.data_type} · {field.review_state.replaceAll("_", " ")}</span>
                  {formatEvidenceValue(field.effective_value) !== formatEvidenceValue(field.candidate_value) ? (
                    <small>Reviewed value: {formatEvidenceValue(field.effective_value)}</small>
                  ) : null}
                  {field.latest_review?.rationale ? <small>Review rationale: {field.latest_review.rationale}</small> : null}
                  {field.citations[0] ? <blockquote>{field.citations[0].excerpt}</blockquote> : null}
                </div>
                <div className="field-actions">
                  <button type="button" className="text-button" onClick={() => onSelectDocument(field.document_id)}>Document</button>
                  {field.citations.length ? <button type="button" className="text-button" onClick={() => onCitation(field)}>Page {field.citations[0].page}</button> : null}
                  {field.review_state === "pending" ? <button type="button" className="text-button" onClick={() => onReview(field)}>Review</button> : null}
                </div>
              </article>
            ))}
          </section>
        );
      })}
      {workspace.additional_facts.length ? (
        <section className="case-evidence-group card-section">
          <div className="section-heading"><div><span className="eyebrow">Source-only facts</span><h3>Additional extracted facts</h3></div></div>
          {workspace.additional_facts.map((fact) => (
            <article className="case-evidence-value" key={fact.id}>
              <div>
                <strong>{fact.name}: {formatEvidenceValue(fact.value)}</strong>
                <span>{documentNames.get(fact.document_id) ?? "Source document"} · {fact.category} · {fact.extraction_status}</span>
                {fact.citations[0] ? <blockquote>{fact.citations[0].excerpt}</blockquote> : null}
              </div>
              <div className="field-actions">
                <button type="button" className="text-button" onClick={() => onSelectDocument(fact.document_id)}>Document</button>
                {fact.citations.length ? <button type="button" className="text-button" onClick={() => onCitation(fact)}>Page {fact.citations[0].page}</button> : null}
              </div>
            </article>
          ))}
        </section>
      ) : null}
      <p className="data-note">Conflicts are identified only for matching canonical field paths, compatible data types, and exactly matching units. Human review is required; the system does not choose a source of truth.</p>
    </section>
  );
}

function formatEvidenceValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not found";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function DecisionSection({
  workspace,
  onReview,
  onRequirements,
  onOpenAssessment,
  onDecisionRecorded,
  onAiCitation,
}: {
  workspace: Workspace;
  onReview: () => void;
  onRequirements: () => void;
  onOpenAssessment: () => void;
  onDecisionRecorded: () => void;
  onAiCitation: (citation: Citation) => void;
}) {
  const assessment = useCaseAssessment(workspace.case.external_case_id, workspaceRefreshKey(workspace));
  return (
    <>
      {/* Shown for the underwriter's independent review. Nothing here records a decision. */}
      <AssessmentFindings
        view={assessment.view}
        loading={assessment.loading}
        error={assessment.error}
        refreshing={assessment.refreshing}
        canRefresh={false}
        onRefresh={() => void assessment.refresh()}
        onCitation={onAiCitation}
      />
      {assessment.view ? <TermsComparison view={assessment.view} /> : null}
      <UnderwritingDecisionCockpit
        workspace={workspace}
        onReview={onReview}
        onRequirements={onRequirements}
        onOpenAssessment={onOpenAssessment}
        onDecisionRecorded={() => {
          onDecisionRecorded();
          void assessment.reload();
        }}
      />
    </>
  );
}

function workspaceRefreshKey(workspace: Workspace): string {
  const { counts } = workspace;
  return [
    workspace.case.external_case_id,
    workspace.case.final_decision ?? "",
    counts.pending,
    counts.accepted,
    counts.corrected,
    counts.rejected,
    workspace.documents.map((doc) => `${doc.id}:${doc.status}`).join(","),
  ].join("|");
}

function AskAiSection({ onOpenAssessment, onReview }: { onOpenAssessment: () => void; onReview: () => void }) {
  return (
    <div className="workbench-section">
      <div className="section-intro"><div><span className="eyebrow">Human-reviewed assistance</span><h2>Ask AI</h2><p>AI assistance is limited to connected, source-grounded assessment results.</p></div></div>
      <section className="card-section ask-ai-empty">
        <div className="ai-assistant-mark">AI</div>
        <h3>Case chat is not connected</h3>
        <p>This workspace does not have a conversational AI service. No answer will be generated from unverified or illustrative data.</p>
        <div className="overview-action-list">
          <button type="button" className="secondary-button" onClick={onOpenAssessment}>View source-grounded AI assessment</button>
          <button type="button" className="secondary-button" onClick={onReview}>Review pending evidence</button>
        </div>
      </section>
    </div>
  );
}

function AuditSection({ events, loading, error }: { events: AuditEvent[]; loading: boolean; error: string | null }) {
  return (
    <div className="workbench-section">
      <div className="section-intro"><div><span className="eyebrow">Read-only event metadata</span><h2>Audit</h2><p>Case activity returned by the audit service.</p></div></div>
      <section className="card-section">
        <div className="notice blue">Audit entries exclude document text, extracted values, corrections, and review rationale.</div>
        {loading ? <p role="status">Loading audit history…</p> : null}
        {error ? <p role="alert" className="form-error">{error}</p> : null}
        {!loading && !error && !events.length ? <p className="quiet-message">No audit events are available.</p> : null}
        <ol className="audit-list">
          {events.map((event) => (
            <li key={event.id}>
              <span className={`audit-dot ${event.outcome === "success" ? "success" : "warning"}`} aria-hidden="true" />
              <div>
                <h3>{event.action.replaceAll(".", " · ").replaceAll("_", " ")}</h3>
                <p>{event.actor_subject} · {new Date(event.occurred_at).toLocaleString()}</p>
                <small>Outcome: {event.outcome.replaceAll("_", " ")} · Correlation {event.correlation_id}</small>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return `${error.problem.detail}${error.problem.correlation_id ? ` Reference ${error.problem.correlation_id}.` : ""}`;
  return "The operation could not be completed.";
}
