import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  loadCaseAssessment,
  loadProduct,
  refreshCaseAssessment,
  requoteCaseProduct,
} from "../api";
import type {
  AssessmentCitation,
  AssessmentEvidence,
  AssessmentResult,
  CaseAssessmentView,
  Citation,
  RatingInputs,
} from "../types";

export const NOT_AVAILABLE = "Not Available";
export const NOT_ASSESSED = "Not Assessed";

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail;
  return error instanceof Error ? error.message : "The operation could not be completed.";
}

export function formatMoney(amount: number | null | undefined, currency?: string | null): string {
  if (amount === null || amount === undefined) return NOT_AVAILABLE;
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: currency || "INR",
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${currency ?? ""} ${amount.toLocaleString("en-IN")}`.trim();
  }
}

const FREQUENCY: Record<string, string> = {
  single: "single premium",
  annual: "per year",
  half_yearly: "per half-year",
  quarterly: "per quarter",
  monthly: "per month",
};

export function frequencyLabel(value: string | null | undefined): string {
  return value ? FREQUENCY[value] ?? value.replaceAll("_", " ") : "";
}

function checked(view: CaseAssessmentView): CaseAssessmentView {
  if (!view || !Array.isArray(view.versions) || !view.final_terms) {
    throw new Error("The assessment response was not in the expected format.");
  }
  return view;
}

/** Loads the case assessment and reloads it whenever ``refreshKey`` changes. */
export function useCaseAssessment(caseId: string, refreshKey: string) {
  const [view, setView] = useState<CaseAssessmentView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let next = checked(await loadCaseAssessment(caseId));
      if (next.stale) {
        // Inputs or rules changed since the saved version: save a new version automatically.
        // Users without review permission keep seeing the saved version.
        try {
          next = checked(await refreshCaseAssessment(caseId));
        } catch {
          // Keep the saved version; the stale notice stays visible.
        }
      }
      setView(next);
    } catch (failure) {
      setError(messageFor(failure));
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  async function refresh() {
    setRefreshing(true);
    setError(null);
    try {
      setView(checked(await refreshCaseAssessment(caseId)));
    } catch (failure) {
      setError(messageFor(failure));
    } finally {
      setRefreshing(false);
    }
  }

  return { view, error, loading, refreshing, reload: load, refresh };
}

function toCitation(citation: AssessmentCitation): Citation {
  return { ...citation, bbox: null };
}

export function CitationLinks({
  citations,
  onCitation,
}: {
  citations: AssessmentCitation[];
  onCitation: (citation: Citation) => void;
}) {
  if (!citations.length) return null;
  return (
    <span className="assessment-citations">
      {citations.slice(0, 3).map((citation, index) => (
        <button
          key={`${citation.document_id}-${citation.page}-${index}`}
          type="button"
          className="text-button"
          title={citation.excerpt}
          onClick={() => onCitation(toCitation(citation))}
        >
          Page {citation.page} source
        </button>
      ))}
    </span>
  );
}

// ---------------------------------------------------------------- KPI cards

export function AssessmentKpis({
  view,
  loading,
  error,
}: {
  view: CaseAssessmentView | null;
  loading: boolean;
  error: string | null;
}) {
  const result = view?.latest?.result ?? null;
  if (!result) {
    const message = loading ? "Loading assessment…" : error ?? "No assessment has been generated yet.";
    return (
      <div className="overview-kpi-grid">
        <Kpi label="AI recommendation" value={NOT_AVAILABLE} detail={message} />
        <Kpi label="Financial cover exposure" value={NOT_AVAILABLE} detail={message} />
        <Kpi label="Premium impact" value={NOT_AVAILABLE} detail={message} />
        <Kpi label="Risk score" value={NOT_ASSESSED} detail={message} />
      </div>
    );
  }
  const { recommendation, risk_score: risk, financial, proposed_terms: proposed, revised_premium: revised } = result;
  const exposure = financial.exposure;
  const currency = exposure.currency ?? proposed.currency;
  const demo = Boolean(recommendation.rule_set?.is_demo);

  const exposureValue = exposure.total_exposure ?? exposure.proposed_sum_assured;
  const exposureDetail = exposure.proposed_sum_assured === null
    ? "Proposed sum assured was not captured with the case."
    : exposure.existing_cover.amount !== null
      ? `Proposed ${formatMoney(exposure.proposed_sum_assured, currency)} + existing ${formatMoney(exposure.existing_cover.amount, currency)}`
      : `Proposed cover only. Existing insurance: ${NOT_AVAILABLE}.`;

  const premiumValue = proposed.premium ?? null;
  // Say why the proposed premium is missing, not only that the revised one is.
  const proposedPart = premiumValue !== null
    ? `Proposed (indicative) ${frequencyLabel(proposed.premium_frequency)}.`
    : `No proposed premium: ${proposed.status === "not_available"
      ? "the case was created without a catalogue product."
      : proposed.premium_basis || "it was not calculated when the case was created."}`;
  const premiumDetail = revised.status === "not_available"
    ? `${proposedPart} Revised premium: ${NOT_AVAILABLE}.`
    : `${proposedPart} Revised premium ${formatMoney(revised.amount, currency)}.`;

  return (
    <div className="overview-kpi-grid">
      <Kpi
        label="AI recommendation"
        value={recommendation.status === "available" ? recommendation.label : NOT_AVAILABLE}
        detail={recommendation.reason}
        tone={recommendation.code === "refer_to_underwriter" ? "warning" : undefined}
        badge={demo ? "Demo rules" : undefined}
      />
      <Kpi
        label="Financial cover exposure"
        value={exposureValue === null ? NOT_AVAILABLE : formatMoney(exposureValue, currency)}
        detail={exposureDetail}
      />
      <Kpi
        label="Premium impact"
        value={premiumValue === null ? NOT_AVAILABLE : formatMoney(premiumValue, currency)}
        detail={premiumDetail}
      />
      <Kpi
        label="Risk score"
        value={risk.status === "assessed" && risk.score !== null ? `${risk.score} / ${risk.scale_max}` : NOT_ASSESSED}
        detail={risk.status === "assessed"
          ? `${risk.band}: ${risk.interpretation} Scale ${risk.scale_min}–${risk.scale_max}, higher is riskier.`
          : risk.reason ?? "No approved risk model is configured."}
        tone={risk.band === "High" ? "warning" : undefined}
        badge={risk.model && !risk.model.approved ? "Not an approved model" : undefined}
      />
    </div>
  );
}

function Kpi({
  label,
  value,
  detail,
  tone,
  badge,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "warning";
  badge?: string;
}) {
  return (
    <article className={`overview-kpi ${tone ?? ""}`}>
      <span>{label}{badge ? <em className="assessment-demo-badge">{badge}</em> : null}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

// ------------------------------------------------------------- terms panel

export function TermsComparison({ view }: { view: CaseAssessmentView }) {
  const result = view.latest?.result;
  const proposed = result?.proposed_terms;
  const final = view.final_terms;
  const currency = proposed?.currency ?? null;
  const rows: Array<[string, string, string, string]> = [
    [
      "Sum assured",
      proposed?.sum_assured != null ? formatMoney(proposed.sum_assured, currency) : NOT_AVAILABLE,
      result?.recommended_terms.status === "not_available" ? NOT_AVAILABLE : "See recommendation",
      final.status === "recorded" && final.approved_sum_assured != null ? formatMoney(final.approved_sum_assured, currency) : "Not recorded",
    ],
    [
      "Premium",
      proposed?.premium != null ? `${formatMoney(proposed.premium, currency)} ${frequencyLabel(proposed.premium_frequency)} (indicative)` : NOT_AVAILABLE,
      result?.revised_premium.amount != null ? formatMoney(result.revised_premium.amount, currency) : NOT_AVAILABLE,
      final.status === "recorded" && final.applicable_premium != null ? formatMoney(final.applicable_premium, currency) : "Not recorded",
    ],
    [
      "Risk",
      "—",
      result?.risk_score.status === "assessed" ? `${result.risk_score.score} / ${result.risk_score.scale_max} (${result.risk_score.band})` : NOT_ASSESSED,
      final.status === "recorded" ? (final.decision ?? "").replaceAll("_", " ") : "Not recorded",
    ],
  ];
  return (
    <section className="card-section" aria-label="Proposed, assessed and final terms">
      <div className="section-heading"><h3>Proposed, assessed and final terms</h3></div>
      <table className="identity-table">
        <thead>
          <tr><th>Item</th><th>Proposed (product selection)</th><th>Assessed / revised</th><th>Final (underwriter)</th></tr>
        </thead>
        <tbody>
          {rows.map(([label, a, b, c]) => (
            <tr key={label}><th scope="row">{label}</th><td>{a}</td><td>{b}</td><td>{c}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="analysis-disclaimer">
        Proposed terms are fixed at case creation and are never changed by the assessment. Only the
        underwriter's recorded decision sets final terms.
      </p>
    </section>
  );
}

// ---------------------------------------------------------- findings panel

const RULE_STATUS: Record<string, string> = {
  triggered: "Triggered",
  not_triggered: "Not triggered",
  not_evaluable: "Not evaluable",
};

function evidenceValue(item: AssessmentEvidence): string {
  if (item.value === null || item.value === undefined) return NOT_AVAILABLE;
  if (typeof item.value === "object") return JSON.stringify(item.value);
  return `${String(item.value)}${item.unit ? ` ${item.unit}` : ""}`;
}

export function AssessmentFindings({
  view,
  loading,
  error,
  refreshing,
  canRefresh,
  onRefresh,
  onCitation,
}: {
  view: CaseAssessmentView | null;
  loading: boolean;
  error: string | null;
  refreshing: boolean;
  canRefresh: boolean;
  onRefresh: () => void;
  onCitation: (citation: Citation) => void;
}) {
  if (loading && !view) return <p className="data-note" role="status">Loading assessment…</p>;
  if (error && !view) return <div className="form-error" role="alert">{error}</div>;
  if (!view) return null;
  const latest = view.latest;
  const result: AssessmentResult | undefined = latest?.result;
  const triggered = result?.rule_results.filter((rule) => rule.status === "triggered") ?? [];
  const others = result?.rule_results.filter((rule) => rule.status !== "triggered") ?? [];

  return (
    <section className="card-section assessment-findings" aria-label="AI underwriting assessment">
      <div className="section-heading">
        <h3>AI underwriting assessment</h3>
        <div className="identity-card-actions">
          {latest ? (
            <span className="muted">
              Version {latest.version} · {new Date(latest.created_at).toLocaleString()} · {latest.trigger.replaceAll("_", " ")}
            </span>
          ) : null}
          {canRefresh ? (
            <button type="button" className="secondary-button" disabled={refreshing} onClick={onRefresh}>
              {refreshing ? "Refreshing…" : "Refresh assessment"}
            </button>
          ) : null}
        </div>
      </div>
      {error ? <div className="form-error" role="alert">{error}</div> : null}
      {view.stale ? (
        <p className="identity-review-warning">The case evidence changed after this version. Refresh the assessment.</p>
      ) : null}
      {!result ? (
        <p className="quiet-message">No assessment has been generated yet.</p>
      ) : (
        <>
          {result.inputs.rule_set?.is_demo ? (
            <p className="product-demo-note">
              Demo underwriting rules and scoring model. They are illustrative only and are not the
              insurer's approved guidelines.
            </p>
          ) : null}
          <div className="assessment-recommendation">
            <strong>{result.recommendation.status === "available" ? result.recommendation.label : NOT_AVAILABLE}</strong>
            <span>{result.recommendation.reason}</span>
            <small className="product-quote-disclaimer">{result.recommendation.disclaimer}</small>
          </div>

          <h4>Triggered rules</h4>
          {triggered.length === 0 ? <p className="muted">No rule was triggered.</p> : null}
          <ul className="assessment-rule-list">
            {triggered.map((rule) => (
              <li key={rule.rule_id} className={`rule-${rule.outcome}`}>
                <div className="assessment-rule-heading">
                  <strong>{rule.title}</strong>
                  <span className={`identity-badge ${rule.outcome === "refer" ? "match-mismatch" : "match-review_required"}`}>
                    {rule.outcome === "refer" ? "Refer" : "Advisory"}
                  </span>
                </div>
                <small>{rule.reason}</small>
                <ul className="assessment-evidence">
                  {rule.evidence.map((item, index) => (
                    <li key={`${rule.rule_id}-${index}`}>
                      <span>{item.label}: <strong>{evidenceValue(item)}</strong></span>
                      {item.filename ? <span className="muted"> · {item.filename}</span> : null}
                      {item.source === "case_product_selection" ? <span className="muted"> · from the case product selection</span> : null}
                      {item.explanation ? <span className="muted"> · {item.explanation}</span> : null}
                      <CitationLinks citations={item.citations} onCitation={onCitation} />
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>

          {result.medical_findings.length ? (
            <>
              <h4>Medical evidence (AI analysis)</h4>
              <ul className="assessment-evidence">
                {result.medical_findings.slice(0, 12).map((finding, index) => (
                  <li key={`${finding.kind}-${index}`}>
                    <span>{finding.text}</span>
                    <CitationLinks citations={finding.citations} onCitation={onCitation} />
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {result.issues.length ? (
            <>
              <h4>Missing or inconsistent information</h4>
              <ul className="identity-issues">
                {result.issues.map((issue, index) => (
                  <li key={`${issue.category}-${index}`} className={`issue-${issue.severity}`}>{issue.message}</li>
                ))}
              </ul>
            </>
          ) : null}

          {others.length ? (
            <details className="assessment-other-rules">
              <summary>Other rules ({others.length})</summary>
              <ul>
                {others.map((rule) => (
                  <li key={rule.rule_id}>
                    <strong>{rule.title}</strong> · {RULE_STATUS[rule.status]} · <span className="muted">{rule.reason}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {view.versions.length > 1 ? (
            <details className="assessment-other-rules">
              <summary>Assessment history ({view.versions.length} versions)</summary>
              <ul>
                {view.versions.map((item) => (
                  <li key={item.version}>
                    v{item.version} · {new Date(item.created_at).toLocaleString()} · {item.trigger.replaceAll("_", " ")} ·{" "}
                    {(item.recommendation ?? "not available").replaceAll("_", " ")}
                    {item.risk_score !== null ? ` · score ${item.risk_score}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </>
      )}
    </section>
  );
}

// ------------------------------------------------- calculate missing premium

const FACTOR_LABELS: Record<string, string> = {
  age: "Applicant age",
  gender: "Applicant gender",
  smoker: "Smoking status",
};

/**
 * Shown when the case has a catalogue product but no proposed premium. Asks only for the
 * applicant details the product's pricing needs and that were not recorded at case creation.
 */
export function ProposedPremiumPrompt({
  caseId,
  view,
  onUpdated,
}: {
  caseId: string;
  view: CaseAssessmentView | null;
  onUpdated: () => void;
}) {
  const proposed = view?.latest?.result.proposed_terms;
  const productId = proposed?.status === "captured" && proposed.premium == null ? proposed.product_id : null;
  const [missing, setMissing] = useState<string[] | null>(null);
  const [pricingAvailable, setPricingAvailable] = useState(true);
  const [rating, setRating] = useState<RatingInputs>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!productId) return;
    let cancelled = false;
    loadProduct(productId)
      .then((product) => {
        if (cancelled) return;
        const recorded = proposed?.rating_inputs ?? {};
        setPricingAvailable(product.pricing_available);
        setMissing(
          product.rating_factors.filter(
            (factor) => factor !== "policy_term" && recorded[factor as keyof typeof recorded] == null,
          ),
        );
      })
      .catch((failure) => { if (!cancelled) setError(messageFor(failure)); });
    return () => { cancelled = true; };
  }, [productId, proposed?.rating_inputs]);

  if (!productId) return null;
  if (!pricingAvailable) return null;

  const complete = (missing ?? []).every((factor) => rating[factor as keyof RatingInputs] !== undefined);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await requoteCaseProduct(caseId, rating);
      onUpdated();
    } catch (failure) {
      setError(messageFor(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card-section proposed-premium-prompt" aria-label="Calculate proposed premium">
      <div className="section-heading"><h3>Calculate the proposed premium</h3></div>
      <p className="muted">
        This case was saved without a premium. Add the missing applicant details to calculate the
        indicative premium for the selected product. The selected cover and terms do not change, and
        the earlier values stay in the case history.
      </p>
      {missing === null && !error ? <p className="data-note" role="status">Loading product pricing…</p> : null}
      {missing && missing.length ? (
        <div className="product-rating-inputs">
          {missing.includes("age") ? (
            <label>
              {FACTOR_LABELS.age}
              <input
                type="number"
                min={0}
                max={120}
                aria-label="Applicant age"
                value={rating.age ?? ""}
                onChange={(event) => setRating((current) => ({
                  ...current,
                  age: event.target.value === "" ? undefined : Number(event.target.value),
                }))}
              />
            </label>
          ) : null}
          {missing.includes("gender") ? (
            <label>
              {FACTOR_LABELS.gender}
              <select
                aria-label="Applicant gender"
                value={rating.gender ?? ""}
                onChange={(event) => setRating((current) => ({
                  ...current,
                  gender: (event.target.value || undefined) as RatingInputs["gender"],
                }))}
              >
                <option value="">Select</option>
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
              </select>
            </label>
          ) : null}
          {missing.includes("smoker") ? (
            <label>
              {FACTOR_LABELS.smoker}
              <select
                aria-label="Smoking status"
                value={rating.smoker === undefined ? "" : String(rating.smoker)}
                onChange={(event) => setRating((current) => ({
                  ...current,
                  smoker: event.target.value === "" ? undefined : event.target.value === "true",
                }))}
              >
                <option value="">Select</option>
                <option value="false">Non-smoker</option>
                <option value="true">Smoker</option>
              </select>
            </label>
          ) : null}
        </div>
      ) : null}
      {error ? <div className="form-error" role="alert">{error}</div> : null}
      {missing !== null ? (
        <button type="button" className="primary-button" disabled={busy || !complete} onClick={() => void submit()}>
          {busy ? "Calculating…" : "Calculate premium"}
        </button>
      ) : null}
    </section>
  );
}
