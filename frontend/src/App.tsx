import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  createCase,
  loadCases,
  loadAudit,
  loadWorkspace,
  retryDocument,
  submitReview,
  uploadDocument,
} from "./api";
import { advisoryNotes, isAutoAccepted } from "./advisory";
import { DashboardCharts } from "./components/DashboardCharts";
import { DrawerShell, DocumentsDrawer } from "./components/Drawers";
import {
  AdditionalFactsView,
  KnockoutChecksView,
  LabReportsView,
  SummaryView,
  VitalsView,
} from "./components/EvidenceViews";
import { KycViews, kycViews } from "./components/KycViews";
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
  Citation,
  DocumentSummary,
  EvidenceField,
  ReviewPayload,
  Workspace,
} from "./types";

type MedicalView = "summary" | "vitals" | "lab-reports" | "knockout-checks" | "additional-facts";
type CaseSection = "Overview" | "AI Assessment" | "Underwriting" | "Documents" | "Simulator" | "Decision" | "Ask AI" | "Audit";
type UploadDocumentType = "medical_report" | "kyc_individual";

const caseSections: CaseSection[] = [
  "Overview",
  "AI Assessment",
  "Underwriting",
  "Documents",
  "Simulator",
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

export default function App() {
  const [activeCaseId, setActiveCaseId] = useState<string | null>(readCaseId);
  const [caseItems, setCaseItems] = useState<CaseListItem[]>([]);
  const [caseListLoading, setCaseListLoading] = useState(true);
  const [caseListError, setCaseListError] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [loading, setLoading] = useState(Boolean(readCaseId()));
  const [aiPanelOpen, setAiPanelOpen] = useState(true);
  const [sidebarSearch, setSidebarSearch] = useState("");
  const [pageError, setPageError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  // Document whose "processing is queued" message stays visible until processing finishes.
  const [trackedUploadId, setTrackedUploadId] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<CaseSection>("Overview");
  const [activeView, setActiveView] = useState<string>("summary");
  const [activeUnderwritingSection, setActiveUnderwritingSection] =
    useState<(typeof underwritingSections)[number]>("Medical evidence");
  const [uploadDocumentType, setUploadDocumentType] = useState<UploadDocumentType>("medical_report");
  const [source, setSource] = useState<SourceSelection>(() => initialSourceSelection(readCaseId() ?? ""));
  const [reviewField, setReviewField] = useState<EvidenceField | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [reviewDrawerOpen, setReviewDrawerOpen] = useState(false);
  const [documentsOpen, setDocumentsOpen] = useState(false);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
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
    try {
      const next = await loadCases();
      setCaseItems(Array.isArray(next) ? next : []);
    } catch (error) {
      setCaseListError(messageFor(error));
    } finally {
      setCaseListLoading(false);
    }
  }, []);

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

  const latestDocument = workspace?.documents[0] ?? null;
  const latestRun = workspace?.runs.find((run) => run.document_id === latestDocument?.id);
  const latestDocumentFields = workspace?.fields.filter(
    (field) => field.document_id === latestDocument?.id,
  ) ?? [];
  const isKycDocument = latestDocument?.document_type === "kyc_individual";
  const visibleViews = isKycDocument ? kycViews : medicalViews;
  const activeKycView = kycViews.find((view) => view.id === activeView)?.id ?? "overview";
  const selectedView = isKycDocument ? activeKycView : activeView;
  const canGenerateSummary = Boolean(
    latestDocument
      && ["completed", "review_required"].includes(latestDocument.status)
      && latestRun
      && latestRun.provider !== "deterministic-local"
      && !latestRun.ai_analysis?.summary,
  );
  const selectedDocument = workspace?.documents.find((item) => item.id === source.documentId) ?? null;

  function navigateToCase(caseId: string | null) {
    const url = new URL(window.location.href);
    if (caseId) url.searchParams.set("case", caseId);
    else url.searchParams.delete("case");
    window.history.pushState({}, "", `${url.pathname}${url.search}${url.hash}`);
    setActiveCaseId(caseId);
    setWorkspace(null);
    setPageError(null);
    setLoading(Boolean(caseId));
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
      setActiveSection("AI Assessment");
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
    const target = document ?? selectedDocument ?? latestDocument;
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
                if (value === "medical_report" || value === "kyc_individual") {
                  setUploadDocumentType(value);
                }
              }}
            >
              <option value="medical_report">Medical report</option>
              <option value="kyc_individual">Individual KYC</option>
            </select>
          </label>
          <button type="button" className="primary-button" onClick={() => fileInput.current?.click()}>Add document</button>
          <button type="button" className="secondary-button" onClick={() => setReviewDrawerOpen(true)}>Request requirements</button>
          <button type="button" className="secondary-button" onClick={() => setDocumentsOpen(true)}>Manage documents <span className="button-count">{workspace.documents.length}</span></button>
          <button type="button" className="secondary-button" onClick={() => openSource()}>View source</button>
          <button type="button" className="secondary-button" onClick={() => setReviewDrawerOpen(true)}>
            HITL review <span className="button-count">{workspace.counts.pending}</span>
          </button>
          <button type="button" className="primary-button" onClick={() => setReviewDrawerOpen(true)}>Decision cockpit</button>
        </div>
      </section>

      <ProgressStrip document={latestDocument} />

      <div className="queue-tools-bar">
        <div className="queue-tools-inner">
          <label className="queue-search-input">
            <span className="visually-hidden">Search underwriting cases</span>
            <input
              aria-label="Search underwriting cases"
              placeholder="Search case, proposal or city"
              value={sidebarSearch}
              onChange={(event) => setSidebarSearch(event.target.value)}
            />
          </label>
        </div>
      </div>

      <main className={`main-layout sidebar-open ${aiPanelOpen ? "" : "ai-collapsed"}`}>
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
        <aside id="underwriting-queue" className="case-sidebar" aria-label="Underwriting queue">
          <div className="case-sidebar-inner">
          <div className="queue-heading-row">
            <div className="queue-section-label">Queues</div>
          </div>
          <button type="button" className="queue-filter active"><span>☷</span> My underwriting queue</button>
          <button type="button" className="queue-filter"><span>◆</span> Medical review</button>
          <button type="button" className="queue-filter"><span>₹</span> Financial review</button>
          <button type="button" className="queue-filter"><span>◷</span> SLA watch</button>
          <div className="queue-section-label">Cases</div>
          <div className="sidebar-case-list">
            {caseItems.filter(({ case: item }) =>
              `${item.applicant_display_name} ${item.external_case_id} ${item.proposal_number}`.toLowerCase().includes(sidebarSearch.trim().toLowerCase()),
            ).map(({ case: item }) => (
              <button
                type="button"
                key={item.id}
                className={`sidebar-case-card ${item.external_case_id === workspace.case.external_case_id ? "active" : ""}`}
                onClick={() => navigateToCase(item.external_case_id)}
              >
                <strong>{item.applicant_display_name}</strong>
                <span>{item.external_case_id}</span>
              </button>
            ))}
          </div>
          </div>
        </aside>
        <section className="evidence-pane" aria-label={isKycDocument ? "KYC review" : "Medical evidence"}>
          <nav className="case-section-tabs" aria-label="Underwriting case sections">
            {caseSections.map((section) => (
              <button
                type="button"
                key={section}
                className={activeSection === section ? "active" : ""}
                aria-current={activeSection === section ? "page" : undefined}
                onClick={() => {
                  setActiveSection(section);
                  if (section === "Audit") void loadAuditHistory();
                }}
              >
                {section}
              </button>
            ))}
          </nav>
          <div className="evidence-scroll">
            {activeSection === "Overview" ? (
              <OverviewSection
                workspace={workspace}
                onOpenDocuments={() => setActiveSection("Documents")}
                onOpenAssessment={() => setActiveSection("AI Assessment")}
                onOpenReview={() => setReviewDrawerOpen(true)}
              />
            ) : null}
            {activeSection === "AI Assessment" ? (
              <>
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
                {isKycDocument ? (
                  <KycViews
                    activeView={activeKycView}
                    document={latestDocument}
                    fields={latestDocumentFields}
                    onCitation={openCitation}
                    onReview={(field) => { setReviewError(null); setReviewField(field); }}
                  />
                ) : (
                  <>
                    {activeView === "summary" ? <SummaryView fields={latestDocumentFields} analysis={latestRun?.ai_analysis ?? null} canGenerateSummary={canGenerateSummary} onGenerateSummary={() => { if (latestDocument) void handleRetry(latestDocument); }} onAiCitation={openAnalysisCitation} onCitation={openCitation} onReview={(field) => { setReviewError(null); setReviewField(field); }} /> : null}
                    {activeView === "vitals" ? <VitalsView fields={latestDocumentFields} analysis={latestRun?.ai_analysis ?? null} onAiCitation={openAnalysisCitation} onCitation={openCitation} onReview={(field) => { setReviewError(null); setReviewField(field); }} /> : null}
                    {activeView === "lab-reports" ? <LabReportsView results={latestRun?.ai_analysis?.lab_results ?? []} onCitation={openAnalysisCitation} /> : null}
                    {activeView === "knockout-checks" ? <KnockoutChecksView checks={latestRun?.ai_analysis?.knockout_checks ?? []} onCitation={openAnalysisCitation} /> : null}
                    {activeView === "additional-facts" ? <AdditionalFactsView facts={workspace.additional_facts.filter((fact) => fact.document_id === latestDocument?.id)} onCitation={openCitation} /> : null}
                    <p className="data-note">Extracted candidates require human review before use as case evidence. No underwriting or clinical decision is made here.</p>
                  </>
                )}
              </>
            ) : null}
            {activeSection === "Underwriting" ? (
              <UnderwritingSection
                sections={underwritingSections}
                activeSection={activeUnderwritingSection}
                onSelect={setActiveUnderwritingSection}
                isKycDocument={isKycDocument}
                document={latestDocument}
                fields={latestDocumentFields}
                caseInfo={{
                  applicant: workspace.case.applicant_display_name,
                  caseId: workspace.case.external_case_id,
                  proposal: workspace.case.proposal_number,
                }}
                onOpenAssessment={() => setActiveSection("AI Assessment")}
                onOpenReview={() => setReviewDrawerOpen(true)}
                onCitation={openCitation}
                onReview={(field) => { setReviewError(null); setReviewField(field); }}
              />
            ) : null}
            {activeSection === "Documents" ? (
              <DocumentsSection
                documents={workspace.documents}
                onUpload={() => fileInput.current?.click()}
                onOpenSource={openSource}
                onRetry={(document) => void handleRetry(document)}
              />
            ) : null}
            {activeSection === "Simulator" ? <SimulatorSection workspace={workspace} /> : null}
            {activeSection === "Decision" ? (
              <DecisionSection
                workspace={workspace}
                onReview={() => setReviewDrawerOpen(true)}
                onRequirements={() => setReviewDrawerOpen(true)}
                onOpenAssessment={() => setActiveSection("AI Assessment")}
              />
            ) : null}
            {activeSection === "Ask AI" ? (
              <AskAiSection
                onOpenAssessment={() => setActiveSection("AI Assessment")}
                onReview={() => setReviewDrawerOpen(true)}
              />
            ) : null}
            {activeSection === "Audit" ? (
              <AuditSection events={auditEvents} loading={auditLoading} error={auditError} />
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
      {documentsOpen ? <DocumentsDrawer documents={workspace.documents} onClose={() => setDocumentsOpen(false)} onView={(document) => { setDocumentsOpen(false); openSource(document); }} onRetry={(document) => void handleRetry(document)} /> : null}
    </div>
  );
}

function CasesHome({
  cases,
  loading,
  error,
  notice,
  onCreate,
  onOpen,
  onRefresh,
}: {
  cases: CaseListItem[];
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
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [queueFilter, setQueueFilter] = useState("all");
  // Time the case list last arrived from the API, shown as "Updated hh:mm".
  const refreshedAt = useMemo(() => (loading ? null : new Date()), [cases, loading]);

  const visibleCases = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return cases.filter(({ case: item }) => {
      const matchesSearch = !needle || [
        item.applicant_display_name,
        item.external_case_id,
        item.proposal_number,
        item.product_name,
        item.workflow_stage,
      ].some((value) => value.toLowerCase().includes(needle));
      const stage = item.workflow_stage.toLowerCase();
      const matchesQueue =
        queueFilter === "all"
        || (queueFilter === "medical" && stage.includes("medical"))
        || (queueFilter === "compliance" && stage.includes("compliance"))
        || (queueFilter === "sla" && stage.includes("sla"));
      return matchesSearch && matchesQueue;
    });
  }, [cases, queueFilter, search]);

  async function submitCase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      await onCreate(form);
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
      <main className="cases-page">
        <div className="cases-page-heading">
          <div>
            <h1>Operations dashboard</h1>
            <p>Prioritise work by queue, urgency and the next action needed.</p>
          </div>
          <div className="dashboard-search">
            <input
              aria-label="Search cases"
              placeholder="Search name, case, proposal or city"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
        </div>

        <nav className="dashboard-team-tabs" aria-label="Operations teams">
          <button type="button" className="active">NB & UW</button>
        </nav>

        <section className="dashboard-summary" aria-label="Queue summary">
          <div>
            <span>My cases by current stage</span>
            <strong>{cases.length}</strong>
            <small>open cases</small>
          </div>
          <div>
            <span>Pending evidence reviews</span>
            <strong>{cases.filter(({ case: item }) => item.workflow_stage === "human_review").length}</strong>
            <small>assigned to you</small>
          </div>
        </section>

        {!loading && !error ? <DashboardCharts cases={cases} refreshedAt={refreshedAt} /> : null}

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
                <label className="form-field">
                  Product
                  <input
                    required
                    maxLength={200}
                    value={form.product_name}
                    onChange={(event) => updateField("product_name", event.target.value)}
                  />
                </label>
              </div>
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

        <section className="case-list-section" aria-labelledby="case-list-title">
          <div className="case-list-heading">
            <div><h2 id="case-list-title">Cases</h2></div>
            {!loading && !error ? <span className="tag neutral">{visibleCases.length} open case{visibleCases.length === 1 ? "" : "s"}</span> : null}
          </div>
          <div className="dashboard-queue-filters" aria-label="Filter work queue">
            {[
              ["all", "All cases"],
              ["medical", "Medical review"],
              ["compliance", "Compliance review"],
              ["sla", "SLA at risk"],
            ].map(([id, label]) => (
              <button
                type="button"
                key={id}
                className={queueFilter === id ? "active" : ""}
                onClick={() => setQueueFilter(id)}
              >
                {label}
              </button>
            ))}
          </div>
          <button type="button" className="primary-button dashboard-create" onClick={() => { setFormOpen(true); setFormError(null); }}>
            Create new case
          </button>
          {loading ? <div className="case-list-loading" role="status"><div className="spinner" />Loading cases…</div> : null}
          {!loading && !error && visibleCases.length === 0 ? (
            <div className="empty-card case-empty">
              <div className="empty-icon">CASE</div>
              <h3>No cases yet</h3>
              <p>Create a case to upload medical or KYC documents and keep their evidence and activity together.</p>
            </div>
          ) : null}
          {!loading && !error && visibleCases.length > 0 ? (
            <div className="case-list">
              {visibleCases.map(({ case: item, document_count, last_activity_at }) => (
                <article className="case-card" key={item.id}>
                  <div className="case-card-main">
                    <span className="tag info">{item.workflow_stage.replaceAll("_", " ")}</span>
                    <h3>{item.applicant_display_name}</h3>
                    <p className="case-card-id">{item.external_case_id}</p>
                    <div className="case-card-details">
                      <span><strong>Proposal</strong>{item.proposal_number}</span>
                      <span><strong>Product</strong>{item.product_name}</span>
                      <span><strong>Documents</strong>{document_count}</span>
                      <span><strong>Last activity</strong>{new Date(last_activity_at).toLocaleString()}</span>
                    </div>
                  </div>
                  <button type="button" className="primary-button" onClick={() => onOpen(item.external_case_id)}>
                    Open case
                  </button>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      </main>
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
}: {
  workspace: Workspace;
  onOpenDocuments: () => void;
  onOpenAssessment: () => void;
  onOpenReview: () => void;
}) {
  const { case: caseInfo, documents, counts, fields } = workspace;
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
      <div className="overview-kpi-grid">
        <OverviewKpi label="AI recommendation" value="Not available" detail="No underwriting recommendation connected" />
        <OverviewKpi label="Financial cover exposure" value="Not supplied" detail="Cover amounts are not connected" />
        <OverviewKpi label="Premium impact" value="Not supplied" detail="Approved product rates are not connected" />
        <OverviewKpi label="Risk score" value="Not assessed" detail="No approved risk model connected" />
      </div>
      <div className="overview-profile-grid">
        <section className="card-section">
          <div className="section-heading"><h3>Applicant profile</h3></div>
          <OverviewRow label="Life assured" value={caseInfo.applicant_display_name} />
          <OverviewRow label="Age / gender" value="Not supplied" />
          <OverviewRow label="City" value="Not supplied" />
          <OverviewRow label="Occupation" value="Not supplied" />
          <OverviewRow label="Annual income" value="Not supplied" />
          <OverviewRow label="Channel" value="Not supplied" />
          <OverviewRow label="Case ID" value={caseInfo.external_case_id} />
          <OverviewRow label="Workflow stage" value={caseInfo.workflow_stage.replaceAll("_", " ")} />
          <OverviewRow label="SLA" value={caseInfo.sla_label || "Not supplied"} />
        </section>
        <section className="card-section">
          <div className="section-heading"><h3>Proposal & policy details</h3></div>
          <OverviewRow label="Product" value={caseInfo.product_name} />
          <OverviewRow label="Plan option" value="Not supplied" />
          <OverviewRow label="Proposal" value={caseInfo.proposal_number} />
          <OverviewRow label="Sum assured" value="Not supplied" />
          <OverviewRow label="Policy term / PPT" value="Not supplied" />
          <OverviewRow label="Base premium" value="Not supplied" />
          <OverviewRow label="Nominee" value="Not supplied" />
          <OverviewRow label="Uploaded documents" value={String(documents.length)} />
        </section>
      </div>
      <div className="overview-insights-grid">
        <section className="card-section">
          <div className="section-heading"><h3>Risk heatmap</h3></div>
          <div className="overview-heatmap">
            <OverviewHeatCell title="KYC" value={documents.some((doc) => doc.document_type === "kyc_individual") ? "Evidence available" : "Not supplied"} />
            <OverviewHeatCell title="AML" value="Not connected" />
            <OverviewHeatCell title="Medical" value={documents.some((doc) => doc.document_type === "medical_report") ? "Review evidence" : "Not supplied"} warning={documents.some((doc) => doc.document_type === "medical_report")} />
            <OverviewHeatCell title="Financial" value="Not connected" />
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
    if (activeSection === "Medical evidence") return field.ui_section !== "identity" && field.ui_section !== "contact";
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
              <strong>{isKycDocument && activeSection === "TSAR & compliance" ? "Identity evidence is not included in this document." : "No connected evidence for this section."}</strong>
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

function DocumentsSection({
  documents,
  onUpload,
  onOpenSource,
  onRetry,
}: {
  documents: DocumentSummary[];
  onUpload: () => void;
  onOpenSource: (document: DocumentSummary) => void;
  onRetry: (document: DocumentSummary) => void;
}) {
  return (
    <div className="workbench-section">
      <div className="section-intro">
        <div><span className="eyebrow">Case evidence</span><h2>Documents</h2><p>Uploaded files and their processing state.</p></div>
        <button type="button" className="primary-button" onClick={onUpload}>Add document</button>
      </div>
      {documents.length ? (
        <div className="document-list">
          {documents.map((document) => (
            <article className="document-item" key={document.id}>
              <div className="document-icon">PDF</div>
              <div className="document-details">
                <h3>{document.filename}</h3>
                <p>{document.document_type.replaceAll("_", " ")} · Version {document.version} · {document.page_count ?? "—"} pages</p>
                <span className={`status-badge status-${document.status}`}>{document.status.replaceAll("_", " ")}</span>
              </div>
              <div className="document-actions">
                <button type="button" className="secondary-button compact" onClick={() => onOpenSource(document)}>View source</button>
                {document.status === "failed" ? <button type="button" className="text-button" onClick={() => onRetry(document)}>Retry processing</button> : null}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="section-empty-state">
          <strong>No documents uploaded</strong>
          <p>Upload a medical report or individual KYC document to start source-linked evidence extraction.</p>
          <button type="button" className="primary-button" onClick={onUpload}>Add document</button>
        </div>
      )}
    </div>
  );
}

function SimulatorSection({ workspace }: { workspace: Workspace }) {
  return (
    <div className="workbench-section">
      <div className="section-intro"><div><span className="eyebrow">Illustrative only</span><h2>Underwriting simulator</h2><p>Review factors that would be needed for a case-level simulation.</p></div></div>
      <div className="overview-profile-grid">
        <section className="card-section">
          <div className="section-heading"><h3>Case inputs</h3></div>
          <OverviewRow label="Product" value={workspace.case.product_name} />
          <OverviewRow label="Source documents" value={String(workspace.documents.length)} />
          <OverviewRow label="Reviewed evidence fields" value={String(workspace.counts.accepted + workspace.counts.corrected)} />
          <OverviewRow label="Premium / sum assured" value="Not supplied" />
        </section>
        <section className="card-section">
          <div className="section-heading"><h3>Simulation status</h3><span className="tag warning">Unavailable</span></div>
          <p className="quiet-message">Approved product rates, coverage inputs, and underwriting rules are not connected. A premium or loading estimate cannot be calculated from the available case data.</p>
          <div className="callout amber">No simulated result is generated. Connect approved rates and product rules before using this section for a decision.</div>
        </section>
      </div>
    </div>
  );
}

function DecisionSection({
  workspace,
  onReview,
  onRequirements,
  onOpenAssessment,
}: {
  workspace: Workspace;
  onReview: () => void;
  onRequirements: () => void;
  onOpenAssessment: () => void;
}) {
  const pending = workspace.counts.pending;
  return (
    <div className="workbench-section">
      <div className="section-intro"><div><span className="eyebrow">Human-in-the-loop</span><h2>Decision</h2><p>Review readiness and outstanding evidence before any decision is made.</p></div><span className="tag warning">No decision recorded</span></div>
      <div className="overview-profile-grid">
        <section className="card-section">
          <div className="section-heading"><h3>Decision readiness</h3></div>
          <ul className="check-list overview-checklist">
            <li><span className={workspace.documents.length ? "complete-mark" : "pending-mark"}>{workspace.documents.length ? "✓" : "!"}</span><div><strong>Source documents</strong><small>{workspace.documents.length} uploaded</small></div></li>
            <li><span className={pending ? "pending-mark" : "complete-mark"}>{pending ? "!" : "✓"}</span><div><strong>Candidate field review</strong><small>{pending} pending review</small></div></li>
            <li><span className="pending-mark">!</span><div><strong>Underwriting authority and product rules</strong><small>Not connected to this workspace</small></div></li>
          </ul>
        </section>
        <section className="card-section">
          <div className="section-heading"><h3>Available actions</h3></div>
          <p className="quiet-message">The connected service supports evidence review, document management and audit. It does not record an underwriting disposition.</p>
          <div className="overview-action-list">
            <button type="button" className="secondary-button" onClick={onReview}>Review evidence{pending ? ` (${pending})` : ""}</button>
            <button type="button" className="secondary-button" onClick={onRequirements}>Request or manage evidence</button>
            <button type="button" className="secondary-button" onClick={onOpenAssessment}>Review AI assessment</button>
          </div>
        </section>
      </div>
      <div className="callout amber">No approval, decline, loading, or customer offer is recorded from this screen.</div>
    </div>
  );
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
