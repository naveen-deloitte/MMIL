import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  loadUnderwritingVariances,
  recordUnderwritingVarianceDecision,
  resetDemoUnderwritingVariance,
} from "../api";
import type {
  CaseSummary,
  UnderwritingVariance,
  UnderwritingVarianceDecisionInput,
  UnderwritingVarianceWorkspace,
  VarianceDecisionType,
} from "../types";

type DemoStage =
  | "Case Overview"
  | "Document Review"
  | "HITL Review"
  | "Case Evidence"
  | "Underwriting Assessment"
  | "Underwriting Variance Review";

const demoStages: DemoStage[] = [
  "Case Overview",
  "Document Review",
  "HITL Review",
  "Case Evidence",
  "Underwriting Assessment",
  "Underwriting Variance Review",
];

const simulatedDocuments = [
  {
    name: "KYC Document",
    file: "DEMO-kyc-document.pdf",
    details: "Simulated identity-document processing record. No source file is attached.",
  },
  {
    name: "Medical Report",
    file: "DEMO-medical-report.pdf",
    details: "Simulated medical-report processing record. No medical findings are generated.",
  },
  {
    name: "Supporting Financial Document",
    file: "DEMO-financial-document.pdf",
    details: "Simulated supporting-document processing record. No source file is attached.",
  },
];

interface VarianceDataState {
  data: UnderwritingVarianceWorkspace | null;
  loading: boolean;
  saving: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  decide: (varianceId: string, input: UnderwritingVarianceDecisionInput) => Promise<boolean>;
  reset: () => Promise<boolean>;
}

function useVarianceData(caseId: string): VarianceDataState {
  const [data, setData] = useState<UnderwritingVarianceWorkspace | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await loadUnderwritingVariances(caseId));
    } catch (loadError) {
      setError(messageFor(loadError));
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const decide = useCallback(async (
    varianceId: string,
    input: UnderwritingVarianceDecisionInput,
  ): Promise<boolean> => {
    setSaving(true);
    setError(null);
    try {
      setData(await recordUnderwritingVarianceDecision(caseId, varianceId, input));
      return true;
    } catch (saveError) {
      setError(messageFor(saveError));
      return false;
    } finally {
      setSaving(false);
    }
  }, [caseId]);

  const reset = useCallback(async (): Promise<boolean> => {
    setSaving(true);
    setError(null);
    try {
      setData(await resetDemoUnderwritingVariance(caseId));
      return true;
    } catch (resetError) {
      setError(messageFor(resetError));
      return false;
    } finally {
      setSaving(false);
    }
  }, [caseId]);

  return { data, loading, saving, error, refresh, decide, reset };
}

export function UnderwritingVarianceReview({ caseId }: { caseId: string }) {
  const state = useVarianceData(caseId);
  return (
    <VarianceReviewPanel
      caseId={caseId}
      {...state}
    />
  );
}

export function DemoCaseWorkspace({
  caseSummary,
  onBack,
}: {
  caseSummary: CaseSummary;
  onBack: () => void;
}) {
  const [stage, setStage] = useState<DemoStage>("Case Overview");
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null);
  const state = useVarianceData(caseSummary.external_case_id);

  return (
    <div className="application-shell demo-variance-shell">
      <header className="global-header">
        <div className="brand-lockup">
          <div className="logo">MMIL</div>
          <div><strong>Mahindra Manulife<br />Operations Workbench</strong></div>
        </div>
        <span className="demo-label">DEMO · SIMULATED DATA</span>
      </header>
      <main className="demo-workbench">
        <button type="button" className="back-button" onClick={onBack}>← Dashboard</button>
        <section className="demo-case-heading" aria-labelledby="demo-case-title">
          <div>
            <span className="eyebrow">CLIENT PRESENTATION CASE</span>
            <h1 id="demo-case-title">{caseSummary.applicant_display_name}</h1>
            <p>{caseSummary.external_case_id} <span aria-hidden="true">·</span> {caseSummary.product_name}</p>
          </div>
          <div className="demo-case-metadata">
            <span>Proposal <strong>{caseSummary.proposal_number}</strong></span>
            <span>Workflow <strong>{formatStage(caseSummary.workflow_stage)}</strong></span>
          </div>
        </section>
        <div className="notice amber demo-safety-notice" role="note">
          This is fictional demonstration data. It is not a real customer record, pricing calculation, insurance quote, or underwriting decision.
        </div>
        <nav className="demo-stage-tabs" aria-label="Demo case workflow stages">
          {demoStages.map((item) => (
            <button
              type="button"
              key={item}
              className={stage === item ? "active" : ""}
              aria-current={stage === item ? "page" : undefined}
              onClick={() => setStage(item)}
            >
              {item}
            </button>
          ))}
        </nav>
        {stage === "Case Overview" ? (
          <DemoOverview data={state.data} loading={state.loading} />
        ) : null}
        {stage === "Document Review" ? (
          <section className="demo-stage-content" aria-labelledby="demo-documents-title">
            <StageHeading title="Document Review" subtitle="Simulated processing states for presentation only." />
            <div className="demo-document-grid">
              {simulatedDocuments.map((document) => (
                <article className="demo-document-card" key={document.name}>
                  <div className="demo-document-icon" aria-hidden="true">PDF</div>
                  <div>
                    <h3>{document.name}</h3>
                    <p>{document.file}</p>
                    <span className="tag success">DEMO · Processed</span>
                  </div>
                  <button
                    type="button"
                    className="text-button"
                    aria-expanded={selectedDocument === document.name}
                    onClick={() => setSelectedDocument(
                      selectedDocument === document.name ? null : document.name,
                    )}
                  >
                    {selectedDocument === document.name ? "Hide details" : "Inspect"}
                  </button>
                  {selectedDocument === document.name ? (
                    <p className="demo-document-details">{document.details}</p>
                  ) : null}
                </article>
              ))}
            </div>
            <p className="demo-disclaimer">No actual document files or extracted medical findings are included in this demo.</p>
          </section>
        ) : null}
        {stage === "HITL Review" ? (
          <section className="demo-stage-content">
            <StageHeading title="Document HITL Review" subtitle="Document-level review remains separate from underwriting variances." />
            <div className="demo-count-grid">
              <DemoCount title="Open flags" value="0" />
              <DemoCount title="Resolved flags" value="0" />
              <DemoCount title="Cross-document conflicts" value="0" />
              <DemoCount title="Documents analysed" value="3" />
            </div>
            <p className="notice blue">All configured demo document validation checks have passed. No pending document-level HITL exceptions.</p>
            <p className="demo-disclaimer">These are simulated demo states, not results from document processing.</p>
          </section>
        ) : null}
        {stage === "Case Evidence" ? <DemoEvidence /> : null}
        {stage === "Underwriting Assessment" ? <DemoAssessment /> : null}
        {stage === "Underwriting Variance Review" ? (
          <VarianceReviewPanel
            caseId={caseSummary.external_case_id}
            {...state}
          />
        ) : null}
      </main>
    </div>
  );
}

function DemoOverview({
  data,
  loading,
}: {
  data: UnderwritingVarianceWorkspace | null;
  loading: boolean;
}) {
  const premium = data?.variances.find((item) => item.category === "premium");
  return (
    <section className="demo-stage-content">
      <StageHeading title="Case Overview" subtitle="Application details and simulated work status." />
      <div className="demo-count-grid demo-overview-grid">
        <DemoCount title="Case ID" value="MMIL-DEMO-001" />
        <DemoCount title="Applied sum assured" value="₹50,00,000" />
        <DemoCount title="Applied premium" value={loading ? "Loading…" : premium ? money(premium.applied_value, premium.currency) : "Unavailable"} />
        <DemoCount title="Documents" value="3 · simulated" />
      </div>
      <section className="card-section demo-overview-status">
        <StageHeading title="Workflow status" subtitle="Illustrative workflow state only." />
        <div className="demo-status-row"><span className="tag success">DEMO · Documents processed</span><span className="tag success">DEMO · 0 HITL flags</span><span className="tag warning">DEMO · Variance decision pending</span></div>
        <p className="demo-disclaimer">The demo does not approve, decline, or price an actual insurance application.</p>
      </section>
    </section>
  );
}

function DemoEvidence() {
  const rows = [
    ["Applicant", "Ananya Sharma", "DEMO application form"],
    ["Product", "Individual Life Insurance", "DEMO application form"],
    ["Applied sum assured", "₹50,00,000", "DEMO application form"],
    ["Applied premium", "₹50,000", "DEMO application form"],
  ];
  return (
    <section className="demo-stage-content">
      <StageHeading title="Case Evidence" subtitle="Simulated consolidated application values with demo-only source references." />
      <div className="queue-table-scroll">
        <table className="demo-evidence-table">
          <thead><tr><th>Evidence item</th><th>Value</th><th>Source</th></tr></thead>
          <tbody>{rows.map(([label, value, source]) => (
            <tr key={label}><th scope="row">{label}</th><td>{value}</td><td><span className="demo-label-small">DEMO</span> {source}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <p className="demo-disclaimer">No medical values or cross-document findings are fabricated for this presentation.</p>
    </section>
  );
}

function DemoAssessment() {
  return (
    <section className="demo-stage-content">
      <StageHeading title="Underwriting Assessment" subtitle="Assessment context before the final underwriting disposition." />
      <section className="card-section">
        <span className="demo-label-small">DEMO · SIMULATED RECOMMENDATION</span>
        <h3 className="demo-assessment-title">Premium recommendation available for review</h3>
        <p className="quiet-message">This demonstration supplies a simulated premium recommendation only. No medical risk calculation, eligibility assessment, loading, or final decision is performed.</p>
        <p className="quiet-message">Proceed to Underwriting Variance Review to inspect the applied-versus-suggested premium and record a demo outcome.</p>
      </section>
    </section>
  );
}

function VarianceReviewPanel({
  caseId,
  data,
  loading,
  saving,
  error,
  refresh,
  decide,
  reset,
}: {
  caseId: string;
} & VarianceDataState) {
  const [selectedVarianceId, setSelectedVarianceId] = useState<string | null>(null);
  const [decision, setDecision] = useState<VarianceDecisionType | "">("");
  const [customValue, setCustomValue] = useState("");
  const [justification, setJustification] = useState("");
  const [confirmReset, setConfirmReset] = useState(false);

  useEffect(() => {
    const firstId = data?.variances[0]?.id ?? null;
    if (!selectedVarianceId && firstId) setSelectedVarianceId(firstId);
  }, [data?.variances, selectedVarianceId]);

  const variance = data?.variances.find((item) => item.id === selectedVarianceId)
    ?? data?.variances[0]
    ?? null;
  const isDemo = Boolean(data?.demo_mode);
  const canDecide = variance?.status === "pending";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!variance || !decision || !justification.trim()) return;
    const input: UnderwritingVarianceDecisionInput = {
      decision,
      justification: justification.trim(),
    };
    if (decision === "custom_value") input.selected_value = Number(customValue);
    if (await decide(variance.id, input)) {
      setDecision("");
      setCustomValue("");
      setJustification("");
    }
  }

  async function confirmDemoReset() {
    if (await reset()) {
      setConfirmReset(false);
      setDecision("");
      setJustification("");
      setCustomValue("");
    }
  }

  if (loading && !data) {
    return <div className="dashboard-loading" role="status"><div className="spinner" />Loading variance recommendations…</div>;
  }
  if (!data && error) {
    return (
      <section className="demo-stage-content">
        <StageHeading title="Underwriting Variance Review" subtitle="Review differences between applied values and underwriting recommendations." />
        <div className="case-error" role="alert"><span>{error}</span><button type="button" className="text-button" onClick={() => void refresh()}>Try again</button></div>
      </section>
    );
  }
  if (!data) return null;

  return (
    <section className="variance-review-page" aria-labelledby="variance-review-title">
      <div className="variance-page-header">
        <div>
          {isDemo ? <span className="demo-label-small">DEMO · SIMULATED RECOMMENDATION</span> : null}
          <h2 id="variance-review-title">Underwriting Variance Review</h2>
          <p>Review differences between applicant-submitted values and underwriting recommendations.</p>
        </div>
        {isDemo ? (
          <div className="variance-header-actions">
            {confirmReset ? (
              <div className="demo-reset-confirm" role="group" aria-label="Confirm reset demo case">
                <span>Reset this demo and start again?</span>
                <button type="button" className="secondary-button" onClick={() => setConfirmReset(false)} disabled={saving}>Cancel</button>
                <button type="button" className="primary-button" onClick={() => void confirmDemoReset()} disabled={saving}>{saving ? "Resetting…" : "Confirm reset"}</button>
              </div>
            ) : (
              <button type="button" className="secondary-button" onClick={() => setConfirmReset(true)} disabled={saving}>Reset demo</button>
            )}
          </div>
        ) : null}
      </div>
      {isDemo ? (
        <p className="notice amber variance-demo-notice">
          Fictional demo data only. This simulated recommendation is not produced by a connected pricing engine and is not an insurance quote.
        </p>
      ) : null}
      <div className="variance-summary-grid" aria-label="Variance summary">
        <VarianceCount title="Pending variances" value={data.pending_variances} tone="pending" />
        <VarianceCount title="Resolved variances" value={data.resolved_variances} tone="resolved" />
        <VarianceCount title="Total variances" value={data.total_variances} tone="neutral" />
        <VarianceCount title="Cases requiring decision" value={data.cases_requiring_decision} tone="pending" />
      </div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {!variance ? (
        <div className="queue-empty-state">
          <h3>No recommendation data for this case</h3>
          <p>No pricing or risk recommendation is connected. No variance has been calculated.</p>
        </div>
      ) : (
        <>
          <div className="variance-main-grid">
            <nav className="variance-list" aria-label="Variance recommendations">
              <h3>Variances</h3>
              <button
                type="button"
                className={`variance-list-item ${variance.id === selectedVarianceId ? "selected" : ""}`}
                onClick={() => setSelectedVarianceId(variance.id)}
              >
                <span className={`variance-status-dot ${variance.status}`} aria-hidden="true" />
                <span><strong>{variance.title}</strong><small>{formatStage(variance.category)}</small></span>
                <span className={`variance-status ${variance.status}`}>{formatStage(variance.status)}</span>
              </button>
              {data.variances.length > 1 ? data.variances.slice(1).map((item) => (
                <button
                  type="button"
                  className={`variance-list-item ${item.id === selectedVarianceId ? "selected" : ""}`}
                  key={item.id}
                  onClick={() => setSelectedVarianceId(item.id)}
                >
                  <span className={`variance-status-dot ${item.status}`} aria-hidden="true" />
                  <span><strong>{item.title}</strong><small>{formatStage(item.category)}</small></span>
                  <span className={`variance-status ${item.status}`}>{formatStage(item.status)}</span>
                </button>
              )) : null}
            </nav>
            <article className="variance-detail">
              <div className="variance-detail-heading">
                <div><span className="eyebrow">{formatStage(variance.category)}</span><h3>{variance.title}</h3></div>
                <span className={`variance-status ${variance.status}`}>{variance.status === "pending" ? "Underwriter review required" : formatStage(variance.status)}</span>
              </div>
              <div className="variance-comparison">
                <VarianceValue label="Original applied value" value={money(variance.applied_value, variance.currency)} />
                <span className="variance-compare-arrow" aria-hidden="true">→</span>
                <VarianceValue label="Suggested value" value={money(variance.suggested_value, variance.currency)} />
                <VarianceValue label="Difference" value={signedMoney(variance.difference, variance.currency)} emphasis />
              </div>
              <dl className="variance-recommendation-meta">
                <div><dt>Recommendation source</dt><dd>{variance.recommendation_source}</dd></div>
                <div><dt>Recommendation rationale</dt><dd>{variance.recommendation_rationale}</dd></div>
              </dl>
              {canDecide ? (
                <form className="variance-decision-form" onSubmit={(event) => void submit(event)}>
                  <h4>Record underwriter decision</h4>
                  <fieldset disabled={saving}>
                    <legend className="visually-hidden">Choose a variance outcome</legend>
                    <label className="variance-decision-option">
                      <input type="radio" name="variance-decision" value="retain_original" checked={decision === "retain_original"} onChange={() => setDecision("retain_original")} />
                      <span><strong>Retain original</strong><small>Keep {money(variance.applied_value, variance.currency)}</small></span>
                    </label>
                    <label className="variance-decision-option">
                      <input type="radio" name="variance-decision" value="accept_suggested" checked={decision === "accept_suggested"} onChange={() => setDecision("accept_suggested")} />
                      <span><strong>Accept suggested</strong><small>Select {money(variance.suggested_value, variance.currency)}</small></span>
                    </label>
                    <label className="variance-decision-option">
                      <input type="radio" name="variance-decision" value="custom_value" checked={decision === "custom_value"} onChange={() => setDecision("custom_value")} />
                      <span><strong>Set a different value</strong><small>Enter a demo premium between ₹1 and ₹1,000,000,000.</small></span>
                    </label>
                    {decision === "custom_value" ? (
                      <label className="form-field variance-custom-value">
                        Custom premium (INR)
                        <input type="number" min="1" max="1000000000" step="1" required value={customValue} onChange={(event) => setCustomValue(event.target.value)} />
                      </label>
                    ) : null}
                    <label className="variance-decision-option">
                      <input type="radio" name="variance-decision" value="refer" checked={decision === "refer"} onChange={() => setDecision("refer")} />
                      <span><strong>Refer for further assessment</strong><small>No final premium is selected.</small></span>
                    </label>
                  </fieldset>
                  <label className="form-field variance-justification">
                    Decision justification <span aria-hidden="true">*</span>
                    <textarea required minLength={1} maxLength={2000} value={justification} onChange={(event) => setJustification(event.target.value)} placeholder="Explain why this outcome was selected." />
                  </label>
                  <button type="submit" className="primary-button" disabled={saving || !decision || !justification.trim() || (decision === "custom_value" && (!customValue || Number(customValue) < 1 || Number(customValue) > 1_000_000_000))}>
                    {saving ? "Saving decision…" : "Submit decision"}
                  </button>
                  <p className="demo-disclaimer">Demo decisions are not applied to customer records and do not have configured senior-approval rules.</p>
                </form>
              ) : (
                <DecisionResult variance={variance} />
              )}
              {variance.history.length ? <VarianceHistory history={variance.history} currency={variance.currency} /> : null}
            </article>
          </div>
        </>
      )}
    </section>
  );
}

function VarianceValue({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className={`variance-value ${emphasis ? "emphasis" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DecisionResult({ variance }: { variance: UnderwritingVariance }) {
  const decision = variance.current_decision;
  if (!decision) return null;
  return (
    <section className={`variance-decision-result ${variance.status}`} aria-label="Recorded decision">
      <span className="eyebrow">Recorded demo outcome</span>
      <h4>{decisionLabel(decision.decision)}</h4>
      {decision.selected_value !== null ? <p>Final selected value: <strong>{money(decision.selected_value, variance.currency)}</strong></p> : null}
      <p>Justification: {decision.justification}</p>
      <dl className="variance-recommendation-meta">
        <div><dt>Reviewer</dt><dd>{decision.reviewer_subject}</dd></div>
        <div><dt>Recorded at</dt><dd>{new Date(decision.reviewed_at).toLocaleString()}</dd></div>
        <div><dt>Approval state</dt><dd>{decision.approval_status === "demo_only" ? "Demo only · no approval workflow connected" : decision.approval_status}</dd></div>
      </dl>
      <p className="demo-disclaimer">This is a demo outcome only; it does not change the original application or a real underwriting decision.</p>
    </section>
  );
}

function VarianceHistory({
  history,
  currency,
}: {
  history: UnderwritingVariance["history"];
  currency: string;
}) {
  return (
    <section className="variance-history" aria-labelledby="variance-history-title">
      <h4 id="variance-history-title">Decision and reset history</h4>
      <ol>
        {history.map((event) => (
          <li key={event.id}>
            <strong>{decisionLabel(event.decision)}</strong>
            {event.selected_value !== null ? <span>{money(event.selected_value, currency)}</span> : null}
            <p>{event.justification}</p>
            <small>{event.reviewer_subject} · {new Date(event.reviewed_at).toLocaleString()}</small>
          </li>
        ))}
      </ol>
    </section>
  );
}

function StageHeading({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="section-intro">
      <div><h2>{title}</h2><p>{subtitle}</p></div>
      <span className="demo-label-small">DEMO</span>
    </div>
  );
}

function DemoCount({ title, value }: { title: string; value: string }) {
  return <article className="demo-count-card"><span>{title}</span><strong>{value}</strong></article>;
}

function VarianceCount({
  title,
  value,
  tone,
}: {
  title: string;
  value: number;
  tone: "pending" | "resolved" | "neutral";
}) {
  return (
    <article className={`variance-count-card ${tone}`}>
      <span>{title}</span>
      <strong>{value}</strong>
    </article>
  );
}

function money(value: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

function signedMoney(value: number, currency: string): string {
  const formatted = money(Math.abs(value), currency);
  return value > 0 ? `+${formatted}` : value < 0 ? `−${formatted}` : formatted;
}

function formatStage(value: string): string {
  return value.replaceAll("_", " ");
}

function decisionLabel(decision: string): string {
  const labels: Record<string, string> = {
    retain_original: "Original value retained",
    accept_suggested: "Suggested value accepted",
    custom_value: "Custom value selected",
    refer: "Referred for further assessment",
    reset: "Demo reset",
  };
  return labels[decision] ?? formatStage(decision);
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.problem.detail}${error.problem.correlation_id ? ` Reference ${error.problem.correlation_id}.` : ""}`;
  }
  return "The variance operation could not be completed.";
}
