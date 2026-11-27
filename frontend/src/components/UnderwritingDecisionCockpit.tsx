import { useCallback, useEffect, useMemo, useState } from "react";
import { loadUnderwritingDecisionHistory, submitUnderwritingDecision } from "../api";
import type {
  UnderwritingDecisionHistory,
  UnderwritingDecisionInput,
  UnderwritingDecisionReadiness,
  UnderwritingDecisionRecord,
  UnderwritingDecisionType,
  Workspace,
} from "../types";

interface UnderwritingDecisionCockpitProps {
  workspace: Workspace;
  onReview: () => void;
  onRequirements: () => void;
  onOpenAssessment: () => void;
  onDecisionRecorded: () => void;
}

interface DecisionForm {
  decision: Exclude<UnderwritingDecisionType, "refer"> | "";
  approved_sum_assured: string;
  applicable_premium: string;
  decision_rationale: string;
  additional_terms: string;
  decline_reason: string;
  postponement_reason: string;
  additional_requirements: string;
  expected_reassessment_date: string;
}

function initialForm(): DecisionForm {
  return {
    decision: "",
    approved_sum_assured: "",
    applicable_premium: "",
    decision_rationale: "",
    additional_terms: "",
    decline_reason: "",
    postponement_reason: "",
    additional_requirements: "",
    expected_reassessment_date: "",
  };
}

const DECISION_LABELS: Record<UnderwritingDecisionType, string> = {
  approve: "Approve",
  decline: "Decline",
  postpone: "Postpone",
  refer: "Refer / Escalate",
};

const DECISION_OPTIONS: Array<Exclude<UnderwritingDecisionType, "refer">> = [
  "approve",
  "decline",
  "postpone",
];

function decisionRationale(decision: DecisionForm["decision"], form: DecisionForm): string {
  if (!decision) return "";
  if (decision === "approve") return form.decision_rationale.trim();
  if (decision === "decline") return form.decline_reason.trim();
  return form.postponement_reason.trim();
}

function decisionConditions(decision: DecisionForm["decision"], form: DecisionForm): string {
  if (!decision) return "No conditions provided.";
  if (decision === "approve") return form.additional_terms.trim() || "No additional terms entered.";
  if (decision === "postpone") {
    return `${form.additional_requirements.trim()} · Reassess after ${form.expected_reassessment_date}`;
  }
  return "No additional conditions entered.";
}

function buildPayload(form: DecisionForm): UnderwritingDecisionInput {
  if (!form.decision) throw new Error("Select an underwriting decision first.");
  const payload: UnderwritingDecisionInput = {
    decision: form.decision,
  };
  if (form.decision === "approve") {
    payload.approved_sum_assured = form.approved_sum_assured;
    payload.applicable_premium = form.applicable_premium;
    payload.decision_rationale = form.decision_rationale.trim();
    payload.additional_terms = form.additional_terms.trim() || undefined;
  } else if (form.decision === "decline") {
    payload.decline_reason = form.decline_reason.trim();
  } else if (form.decision === "postpone") {
    payload.postponement_reason = form.postponement_reason.trim();
    payload.additional_requirements = form.additional_requirements.trim();
    payload.expected_reassessment_date = form.expected_reassessment_date;
  }
  return payload;
}

function rationaleForRecord(record: UnderwritingDecisionRecord): string {
  return record.decision_rationale;
}

function conditionsForRecord(record: UnderwritingDecisionRecord): string {
  if (record.decision === "approve") return record.additional_terms || "No additional terms recorded.";
  if (record.decision === "postpone") {
    return `${record.additional_requirements ?? "Requirements not provided"} · Reassess after ${record.expected_reassessment_date ?? "date not provided"}`;
  }
  if (record.decision === "refer") return `Referred to ${record.target_authority ?? "authority not provided"}`;
  return record.decision_notes || "No additional notes recorded.";
}

function formatAmount(value: string | number | null): string {
  if (value === null) return "Not applicable";
  const amount = Number(value);
  return Number.isFinite(amount)
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(amount)
    : String(value);
}

function aiEvidenceSummary(workspace: Workspace): string {
  const latestRuns = new Map<string, Workspace["runs"][number]>();
  for (const run of workspace.runs) {
    if (!run.ai_analysis?.summary?.text.trim()) continue;
    const current = latestRuns.get(run.document_id);
    if (!current || run.sequence > current.sequence) latestRuns.set(run.document_id, run);
  }

  return workspace.documents.flatMap((document) => {
    const summary = latestRuns.get(document.id)?.ai_analysis?.summary;
    if (!summary?.text.trim()) return [];
    const sources = [...new Set(summary.citations.map((citation) => `p. ${citation.page}`))];
    return [`${document.filename}: ${summary.text}${sources.length ? ` (Source ${sources.join(", ")})` : ""}`];
  }).join("\n\n");
}

function readinessBlockers(
  readiness: UnderwritingDecisionReadiness | undefined,
  loading: boolean,
): string[] {
  if (!readiness) {
    return [loading ? "Case readiness is still loading." : "Case readiness could not be verified."];
  }
  const blockers: string[] = [];
  if (!readiness.source_documents_complete) {
    blockers.push(readiness.source_documents_total
      ? "Finish processing all source documents."
      : "Upload and process at least one source document.");
  }
  if (!readiness.evidence_review_complete) {
    blockers.push(`Review ${readiness.evidence_reviews_pending} pending evidence field(s).`);
  }
  if (readiness.pending_critical_flags > 0) {
    blockers.push(`Resolve ${readiness.pending_critical_flags} critical finding(s).`);
  }
  if (!readiness.authority_available) {
    blockers.push("Your account is not authorized to record final decisions.");
  }
  if (readiness.demo_case) {
    blockers.push("Final decisions cannot be recorded for demo cases.");
  }
  return blockers.length ? blockers : ["Complete the case readiness requirements."];
}

function addAiRationaleDraft(form: DecisionForm, draft: string): DecisionForm {
  if (!draft) return form;
  if (form.decision === "approve" && !form.decision_rationale.trim()) {
    return { ...form, decision_rationale: draft };
  }
  if (form.decision === "decline" && !form.decline_reason.trim()) {
    return { ...form, decline_reason: draft };
  }
  if (form.decision === "postpone" && !form.postponement_reason.trim()) {
    return { ...form, postponement_reason: draft };
  }
  return form;
}

export function UnderwritingDecisionCockpit({
  workspace,
  onReview,
  onRequirements,
  onOpenAssessment,
  onDecisionRecorded,
}: UnderwritingDecisionCockpitProps) {
  const caseId = workspace.case.external_case_id;
  const [history, setHistory] = useState<UnderwritingDecisionHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<DecisionForm>(initialForm);
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");

  const refreshHistory = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      setHistory(await loadUnderwritingDecisionHistory(caseId));
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load decision history.");
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(null);
    setHistory(null);
    void loadUnderwritingDecisionHistory(caseId)
      .then((result) => {
        if (active) setHistory(result);
      })
      .catch((error: unknown) => {
        if (active) setLoadError(error instanceof Error ? error.message : "Could not load decision history.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [caseId]);

  const readiness = history?.readiness;
  const aiSummary = useMemo(() => aiEvidenceSummary(workspace), [workspace]);
  const aiRationaleDraft = `AI evidence summary (review and tailor to your decision):\n${aiSummary}`.slice(0, 3900);
  useEffect(() => {
    if (!form.decision || !aiSummary) return;
    setForm((current) => addAiRationaleDraft(current, aiRationaleDraft));
  }, [aiRationaleDraft, aiSummary, form.decision]);
  const rationale = decisionRationale(form.decision, form);
  const hasDecisionDetails = useMemo(() => {
    if (!form.decision) return false;
    if (form.decision === "approve") {
      return Number(form.approved_sum_assured) > 0
        && Number(form.applicable_premium) > 0
        && Boolean(form.decision_rationale.trim());
    }
    if (form.decision === "decline") return Boolean(form.decline_reason.trim());
    return Boolean(form.postponement_reason.trim())
      && Boolean(form.additional_requirements.trim())
      && Boolean(form.expected_reassessment_date);
  }, [form]);
  const canReviewSubmission = Boolean(
    readiness?.mandatory_prerequisites_met
      && !readiness.demo_case
      && hasDecisionDetails,
  );
  const blockers = useMemo(
    () => readinessBlockers(readiness, loading),
    [readiness, loading],
  );
  const readinessLabel = !readiness?.mandatory_prerequisites_met
    ? "Not ready for final decision"
    : canReviewSubmission
      ? "Ready for confirmation"
      : "Decision details required";
  const rationaleLabel = form.decision === "decline"
    ? "Reason for decline"
    : form.decision === "postpone"
      ? "Reason for postponement"
      : "Decision rationale";

  function updateRationale(value: string) {
    setForm((current) => {
      if (current.decision === "approve") return { ...current, decision_rationale: value };
      if (current.decision === "decline") return { ...current, decline_reason: value };
      return { ...current, postponement_reason: value };
    });
  }

  function selectDecision(value: DecisionForm["decision"]) {
    setForm((current) => addAiRationaleDraft({ ...current, decision: value }, aiRationaleDraft));
  }

  async function submitDecision() {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const updated = await submitUnderwritingDecision(caseId, buildPayload(form));
      setHistory(updated);
      setConfirming(false);
      setConfirmed(false);
      setForm(initialForm());
      setNotice("Final underwriting decision recorded and added to the case history.");
      onDecisionRecorded();
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Could not record this decision.");
    } finally {
      setSubmitting(false);
    }
  }

  const latestDecision = history?.decisions[0];
  return (
    <div className="workbench-section decision-cockpit">
      <div className="section-intro">
        <div>
          <span className="eyebrow">Human-in-the-loop</span>
          <h2>Decision</h2>
          <p>Review readiness, record a human decision, and retain an immutable decision history.</p>
        </div>
        <span className={`tag ${latestDecision ? "success" : "warning"}`}>
          {latestDecision ? `Latest: ${DECISION_LABELS[latestDecision.decision]}` : "No decision recorded"}
        </span>
      </div>

      {notice ? <div className="notice blue" role="status">{notice}</div> : null}
      {loadError ? (
        <div className="form-error" role="alert">
          {loadError} <button type="button" className="text-button" onClick={() => void refreshHistory()}>Retry</button>
        </div>
      ) : null}

      <section className="card-section decision-readiness" aria-labelledby="decision-readiness-title">
        <div className="section-heading">
          <h3 id="decision-readiness-title">Decision readiness</h3>
          <span className={`tag ${canReviewSubmission ? "success" : "warning"}`}>
            {loading && !readiness ? "Checking readiness…" : readinessLabel}
          </span>
        </div>
        {loading ? <p role="status">Checking case readiness…</p> : null}
        {readiness ? (
          <>
            <ul className="check-list decision-readiness-list">
              <li>
                <span className={readiness.source_documents_complete ? "complete-mark" : "pending-mark"}>{readiness.source_documents_complete ? "✓" : "!"}</span>
                <div><strong>Source document completion</strong><small>{readiness.source_documents_total} document(s) · {readiness.source_documents_complete ? "complete" : "upload and process all required documents"}</small></div>
              </li>
              <li>
                <span className={readiness.evidence_review_complete ? "complete-mark" : "pending-mark"}>{readiness.evidence_review_complete ? "✓" : "!"}</span>
                <div><strong>Evidence review completion</strong><small>{readiness.evidence_reviews_pending} field(s) pending review</small></div>
              </li>
              <li>
                <span className={readiness.pending_critical_flags === 0 ? "complete-mark" : "pending-mark"}>{readiness.pending_critical_flags === 0 ? "✓" : "!"}</span>
                <div><strong>Pending critical flags</strong><small>{readiness.pending_critical_flags} critical flag(s)</small></div>
              </li>
              <li>
                <span className={readiness.information_requests_tracked ? "complete-mark" : "pending-mark"}>{readiness.information_requests_tracked ? "✓" : "!"}</span>
                <div><strong>Outstanding information requests</strong><small>{readiness.information_requests_tracked ? `${readiness.outstanding_information_requests ?? 0} open` : "Not tracked by the current service"}</small></div>
              </li>
              <li>
                <span className={readiness.underwriting_guidelines_available ? "complete-mark" : "pending-mark"}>{readiness.underwriting_guidelines_available ? "✓" : "!"}</span>
                <div><strong>Underwriting guideline availability</strong><small>                {readiness.underwriting_guidelines_available ? "Configured guideline available" : "Not connected"}</small></div>
              </li>
              <li>
                <span className={readiness.authority_available ? "complete-mark" : "pending-mark"}>{readiness.authority_available ? "✓" : "!"}</span>
                <div><strong>Decision authority</strong><small>{readiness.authority_available ? `Authorized role · ${readiness.underwriter_subject}` : "Current identity is not authorized to record decisions"}</small></div>
              </li>
            </ul>
            {readiness.demo_case ? <div className="callout amber">Final decisions are disabled for demonstration cases.</div> : null}
          </>
        ) : null}
      </section>

      <div className="overview-profile-grid decision-workspace-grid">
        <section className="card-section final-decision-panel" aria-labelledby="final-decision-title">
          <div className="section-heading"><h3 id="final-decision-title">Final underwriting decision</h3></div>
          <p className="quiet-message">AI findings are supporting evidence only. The authorized underwriter selects and confirms every disposition; approval does not issue a policy.</p>
          <div className="decision-case-context" role="group" aria-label="Auto-filled case details">
            <span><small>Applicant</small><strong>{workspace.case.applicant_display_name}</strong></span>
            <span><small>Case ID</small><strong>{workspace.case.external_case_id}</strong></span>
            <span><small>Product</small><strong>{workspace.case.product_name}</strong></span>
            <span><small>Underwriter</small><strong>{readiness?.underwriter_subject ?? (loading ? "Loading…" : "Unavailable")}</strong></span>
          </div>
          {confirming ? (
            <div className="decision-confirmation" aria-labelledby="decision-confirmation-title">
              <h4 id="decision-confirmation-title">Confirm final decision</h4>
              <dl className="decision-confirmation-summary">
                <dt>Applicant</dt><dd>{workspace.case.applicant_display_name}</dd>
                <dt>Case ID</dt><dd>{workspace.case.external_case_id}</dd>
                <dt>Selected decision</dt><dd>{form.decision ? DECISION_LABELS[form.decision] : "Not selected"}</dd>
                {form.decision === "approve" ? (
                  <>
                    <dt>Sum assured</dt><dd>{form.approved_sum_assured}</dd>
                    <dt>Premium</dt><dd>{form.applicable_premium}</dd>
                  </>
                ) : null}
                <dt>Decision rationale</dt><dd>{rationale}</dd>
                <dt>Supporting conditions</dt><dd>{decisionConditions(form.decision, form)}</dd>
                <dt>Underwriter</dt><dd>{readiness?.underwriter_subject ?? "Unavailable"}</dd>
              </dl>
              <label className="decision-attestation">
                <input type="checkbox" checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />
                <span>I have reviewed this summary and confirm that this is my final underwriting decision.</span>
              </label>
              {!readiness?.mandatory_prerequisites_met || readiness.demo_case ? (
                <div className="decision-prerequisite-alert" role="alert">
                  <strong>Recording is locked until case readiness is complete.</strong>
                  <ul>{blockers.map((blocker) => <li key={blocker}>{blocker}</li>)}</ul>
                  <button type="button" className="secondary-button" onClick={() => { setConfirming(false); onReview(); }}>
                    Open evidence review
                  </button>
                </div>
              ) : null}
              {submitError ? <p className="form-error" role="alert">{submitError}</p> : null}
              <div className="decision-form-actions">
                <button type="button" className="secondary-button" disabled={submitting} onClick={() => { setConfirming(false); setConfirmed(false); }}>Back to edit</button>
                <button type="button" className="primary-button" disabled={!canReviewSubmission || !confirmed || submitting} onClick={() => void submitDecision()}>
                  {submitting ? "Recording decision…" : "Confirm and record decision"}
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={(event) => { event.preventDefault(); setSubmitError(null); setConfirming(true); setConfirmed(false); }}>
              <fieldset className="decision-outcome-options" disabled={Boolean(readiness?.demo_case)}>
                <legend>Select outcome</legend>
                {DECISION_OPTIONS.map((value) => (
                  <label key={value} className={form.decision === value ? "selected" : ""}>
                    <input type="radio" name="final-decision" value={value} checked={form.decision === value} onChange={() => selectDecision(value)} />
                    <span>{DECISION_LABELS[value]}</span>
                  </label>
                ))}
              </fieldset>

              {form.decision === "approve" ? (
                <>
                  <div className="decision-form-grid">
                    <label>Approved sum assured<input type="number" min="0.01" step="0.01" required value={form.approved_sum_assured} onChange={(event) => setForm((current) => ({ ...current, approved_sum_assured: event.target.value }))} /></label>
                    <label>Applicable premium<input type="number" min="0.01" step="0.01" required value={form.applicable_premium} onChange={(event) => setForm((current) => ({ ...current, applicable_premium: event.target.value }))} /></label>
                    <label className="decision-field-wide">{rationaleLabel}<textarea className="decision-rationale-input" rows={2} required value={form.decision_rationale} onChange={(event) => updateRationale(event.target.value)} /></label>
                  </div>
                  <p className="decision-ai-note">Sum assured and premium are not available from connected product data, so enter verified values from the application or approved rate source.</p>
                  <details className="decision-optional-fields">
                    <summary>Additional terms (optional)</summary>
                    <label>Additional terms or conditions<textarea rows={2} value={form.additional_terms} onChange={(event) => setForm((current) => ({ ...current, additional_terms: event.target.value }))} /></label>
                  </details>
                </>
              ) : null}

              {form.decision === "decline" ? (
                <div className="decision-form-grid">
                  <label className="decision-field-wide">{rationaleLabel}<textarea className="decision-rationale-input" rows={2} required value={form.decline_reason} onChange={(event) => updateRationale(event.target.value)} /></label>
                </div>
              ) : null}

              {form.decision === "postpone" ? (
                <div className="decision-form-grid">
                  <label>{rationaleLabel}<textarea className="decision-rationale-input" rows={2} required value={form.postponement_reason} onChange={(event) => updateRationale(event.target.value)} /></label>
                  <label>Additional requirements<textarea rows={2} required value={form.additional_requirements} onChange={(event) => setForm((current) => ({ ...current, additional_requirements: event.target.value }))} /></label>
                  <label>Expected reassessment date<input type="date" required value={form.expected_reassessment_date} onChange={(event) => setForm((current) => ({ ...current, expected_reassessment_date: event.target.value }))} /></label>
                </div>
              ) : null}
              {form.decision ? (
                aiSummary
                  ? <p className="decision-ai-note">The rationale starts with source-cited AI evidence. Review and tailor it to the selected outcome before confirming.</p>
                  : <p className="decision-ai-note">No AI evidence summary is available for this case. Enter the rationale manually.</p>
              ) : null}
              {submitError ? <p className="form-error" role="alert">{submitError}</p> : null}
              <div className="decision-form-actions">
                <button type="submit" className="primary-button" disabled={!hasDecisionDetails || Boolean(readiness?.demo_case) || submitting}>
                  Review and confirm decision
                </button>
                {!hasDecisionDetails ? <small>Complete the required decision fields above.</small> : null}
                {hasDecisionDetails && !readiness?.mandatory_prerequisites_met ? <small>Review can continue, but recording is blocked until readiness is complete: {blockers.join(" ")}</small> : null}
              </div>
            </form>
          )}
        </section>

        <section className="card-section decision-history" aria-labelledby="decision-history-title">
          <details className="decision-history-details">
            <summary id="decision-history-title">Decision history ({history?.decisions.length ?? 0})</summary>
            {!history?.decisions.length ? <p className="quiet-message">No final underwriting decisions are recorded for this case.</p> : null}
            <ol className="decision-history-list">
              {history?.decisions.map((record, index) => (
                <li key={record.id}>
                  <div className="decision-history-heading">
                    <strong>{DECISION_LABELS[record.decision]}</strong>
                    <span>{index === 0 ? "Latest" : "Previous"}</span>
                  </div>
                  <p>{rationaleForRecord(record)}</p>
                  <dl>
                    {record.decision === "approve" ? (
                      <>
                        <dt>Approved sum assured</dt><dd>{formatAmount(record.approved_sum_assured)}</dd>
                        <dt>Applicable premium</dt><dd>{formatAmount(record.applicable_premium)}</dd>
                      </>
                    ) : null}
                    <dt>Conditions / next step</dt><dd>{conditionsForRecord(record)}</dd>
                    <dt>Decision maker</dt><dd>{record.underwriter_subject}</dd>
                    <dt>Timestamp</dt><dd>{new Date(record.decided_at).toLocaleString()}</dd>
                    {record.authority_reference || record.guideline_reference ? (
                      <><dt>Authority / guideline</dt><dd>{[record.authority_reference, record.guideline_reference].filter(Boolean).join(" · ")}</dd></>
                    ) : null}
                    {record.supporting_document_ids.length ? (
                      <>
                        <dt>Supporting evidence</dt>
                        <dd>{record.supporting_document_ids.map((id) => workspace.documents.find((document) => document.id === id)?.filename ?? id).join(", ")}</dd>
                      </>
                    ) : null}
                    {record.decision_notes ? <><dt>Notes</dt><dd>{record.decision_notes}</dd></> : null}
                  </dl>
                </li>
              ))}
            </ol>
          </details>
        </section>
      </div>

      <section className="card-section decision-navigation-actions">
        <div className="section-heading"><h3>Case review actions</h3></div>
        <div className="overview-action-list">
          <button type="button" className="secondary-button" onClick={onReview}>Review evidence{workspace.counts.pending ? ` (${workspace.counts.pending})` : ""}</button>
          <button type="button" className="secondary-button" onClick={onRequirements}>Request or manage evidence</button>
          <button type="button" className="secondary-button" onClick={onOpenAssessment}>Review AI assessment</button>
        </div>
      </section>
    </div>
  );
}
