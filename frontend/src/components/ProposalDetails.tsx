import { useCallback, useEffect, useState } from "react";

import { ApiError, loadProposal } from "../api";
import type { Citation, ProposalEvidence, ProposalItem, ProposalSource, ProposalView } from "../types";

const NOT_AVAILABLE = "Not Available";

export const SOURCE_LABELS: Record<ProposalSource, string> = {
  proposal_form: "Proposal form",
  product_selection: "Product selection",
  product_catalogue: "Product catalogue",
  document_evidence: "Document evidence",
  ai_assessment: "AI assessment",
  underwriter_decision: "Underwriter decision",
  case_record: "Case record",
};

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail;
  return error instanceof Error ? error.message : "The operation could not be completed.";
}

function money(amount: unknown, currency: string | null | undefined): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  if (amount === null || amount === undefined || Number.isNaN(value)) return NOT_AVAILABLE;
  try {
    return new Intl.NumberFormat("en-IN", { style: "currency", currency: currency || "INR", maximumFractionDigits: 2 }).format(value);
  } catch {
    return value.toLocaleString("en-IN");
  }
}

export function formatProposalValue(item: Pick<ProposalItem, "value" | "kind" | "currency">): string {
  const { value, kind, currency } = item;
  if (value === null || value === undefined || value === "") return NOT_AVAILABLE;
  if (kind === "money") return money(value, currency);
  if (kind === "years") return `${String(value)} years`;
  if (kind === "date") {
    const date = new Date(`${String(value)}T00:00:00`);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  }
  if (kind === "breakdown" && typeof value === "object") {
    const parts = value as { base?: number | null; tax?: number | null; total?: number | null };
    const tax = parts.tax !== null && parts.tax !== undefined ? ` + tax ${money(parts.tax, currency)}` : "";
    return `Base ${money(parts.base, currency)}${tax} = ${money(parts.total, currency)}`;
  }
  return String(value);
}

function evidenceValue(entry: ProposalEvidence): string {
  if (entry.value === null || entry.value === undefined) return NOT_AVAILABLE;
  if (typeof entry.value === "number" && (entry.currency || entry.unit === "INR")) return money(entry.value, entry.currency ?? "INR");
  return `${String(entry.value)}${entry.unit && entry.unit !== "INR" ? ` ${entry.unit}` : ""}`;
}

/** Routine sources are not labelled; only evidence, assessment and decision values carry a chip. */
const QUIET_SOURCES = new Set<ProposalSource>(["proposal_form", "product_selection", "product_catalogue", "case_record"]);

function hasValue(item: ProposalItem): boolean {
  return !(item.value === null || item.value === undefined || item.value === "") || item.evidence.length > 0;
}

function SourceChip({ source, verified }: { source: ProposalSource | null; verified?: boolean | null }) {
  if (!source || QUIET_SOURCES.has(source)) return null;
  const label = source === "document_evidence" ? (verified ? "Verified evidence" : "Document evidence") : SOURCE_LABELS[source];
  return <span className={`proposal-source source-${source}${verified ? " verified" : ""}`}>{label}</span>;
}

/** Loads the proposal view and reloads it whenever ``refreshKey`` changes. */
export function useProposal(caseId: string, refreshKey: string) {
  const [view, setView] = useState<ProposalView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await loadProposal(caseId);
      if (!next || !Array.isArray(next.sections)) throw new Error("The proposal response was not in the expected format.");
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
  return { view, error, loading, reload: load };
}

export function ProposalDetails({
  view,
  loading,
  error,
  onRetry,
  onCitation,
  onOpenProposal,
}: {
  view: ProposalView | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onCitation: (citation: Citation) => void;
  onOpenProposal: () => void;
}) {
  return (
    <section className="card-section proposal-details" aria-label="Proposal and policy details">
      <div className="section-heading proposal-heading">
        <h3>Proposal & policy details</h3>
        {view ? (
          view.proposal_document ? (
            <button type="button" className="secondary-button" onClick={onOpenProposal}>
              View proposal document
            </button>
          ) : null
        ) : null}
      </div>
      {loading && !view ? <p className="data-note" role="status">Loading proposal details…</p> : null}
      {error && !view ? (
        <div className="form-error" role="alert">
          {error} <button type="button" className="text-button" onClick={onRetry}>Try again</button>
        </div>
      ) : null}
      {view ? (
        <>
          {view.catalogue.note ? <p className="identity-review-warning">{view.catalogue.note}</p> : null}
          <div className="proposal-sections">
            {view.sections.map((section) => {
              const highlights = section.id === "coverage" ? section.items.filter((item) => item.highlight && hasValue(item)) : [];
              const rows = section.items.filter((item) => !(section.id === "coverage" && item.highlight) && hasValue(item));
              if (highlights.length + rows.length === 0) return null;
              return (
                <section key={section.id} className={`proposal-section proposal-section-${section.id}`} aria-label={section.title}>
                  <h4>{section.title}</h4>
                  {highlights.length ? (
                    <div className="proposal-highlights">
                      {highlights.map((item) => (
                        <ProposalHighlight key={item.key} item={item} onCitation={onCitation} />
                      ))}
                    </div>
                  ) : null}
                  {rows.length ? (
                    <dl className="proposal-grid">
                      {rows.map((item) => (
                        <ProposalRow key={item.key} item={item} onCitation={onCitation} />
                      ))}
                    </dl>
                  ) : null}
                </section>
              );
            })}
          </div>
          {view.catalogue.is_demo ? <p className="proposal-footnote">Demo catalogue: benefits, riders and rates are fictional.</p> : null}
        </>
      ) : null}
    </section>
  );
}

function Citations({ citations, onCitation }: { citations: ProposalItem["citations"]; onCitation: (c: Citation) => void }) {
  if (!citations.length) return null;
  const citation = citations[0];
  return (
    <button type="button" className="text-button proposal-cite" title={citation.excerpt} onClick={() => onCitation({ ...citation, bbox: null })}>
      Page {citation.page} source
    </button>
  );
}

function EvidenceList({ evidence, onCitation }: { evidence: ProposalEvidence[]; onCitation: (c: Citation) => void }) {
  if (!evidence.length) return null;
  return (
    <ul className="proposal-evidence">
      {evidence.map((entry, index) => (
        <li key={`${entry.label}-${index}`}>
          <SourceChip source={entry.source} verified={entry.verified} />
          <span>{entry.label}: <strong>{evidenceValue(entry)}</strong></span>
          {entry.status ? <span className="muted"> · {entry.status}</span> : null}
          {entry.filename ? <span className="muted"> · {entry.filename}</span> : null}
          <Citations citations={entry.citations} onCitation={onCitation} />
        </li>
      ))}
    </ul>
  );
}

function ProposalHighlight({ item, onCitation }: { item: ProposalItem; onCitation: (c: Citation) => void }) {
  const missing = item.value === null || item.value === undefined;
  return (
    <article className="proposal-highlight">
      <span>{item.label}</span>
      <strong className={missing ? "not-available" : ""}>{formatProposalValue(item)}</strong>
      <EvidenceList evidence={item.evidence} onCitation={onCitation} />
    </article>
  );
}

function ProposalRow({ item, onCitation }: { item: ProposalItem; onCitation: (c: Citation) => void }) {
  const missing = item.value === null || item.value === undefined || item.value === "";
  return (
    <div className="proposal-row">
      <dt>{item.label}</dt>
      <dd>
        <span className={missing ? "not-available" : "proposal-value"}>{formatProposalValue(item)}</span>
        <SourceChip source={item.source} verified={item.verified} />
        <Citations citations={item.citations} onCitation={onCitation} />
        {item.note ? <small className="proposal-note">{item.note}</small> : null}
        <EvidenceList evidence={item.evidence} onCitation={onCitation} />
      </dd>
    </div>
  );
}
