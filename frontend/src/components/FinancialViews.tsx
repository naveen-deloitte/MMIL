import type { DocumentSummary, EvidenceField } from "../types";
import { EvidenceRow } from "./EvidenceViews";

interface FinancialViewsProps {
  document: DocumentSummary | null;
  fields: EvidenceField[];
  emptyMessage: string;
  onCitation: (field: EvidenceField, citationIndex?: number) => void;
  onReview: (field: EvidenceField) => void;
}

const SUMMARY_FIELDS = [
  "financial.annual_income",
  "financial.employer",
  "financial.assessment_year",
  "financial.existing_life_cover",
  "financial.existing_policy_count",
];

function isPresent(field: EvidenceField): boolean {
  return field.candidate_value !== null
    && field.candidate_value !== undefined
    && field.candidate_value !== ""
    && field.review_state !== "rejected";
}

function displayValue(field: EvidenceField): string {
  const value = field.effective_value;
  if (value === null || value === undefined || value === "") return "Not found";
  if (field.unit === "INR") {
    const amount = Number(value);
    if (!Number.isNaN(amount)) return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(amount);
  }
  return String(value);
}

/** Purpose-built review layout for financial documents (salary slip, ITR, Form 16, bank statement). */
export function FinancialViews({ document, fields, emptyMessage, onCitation, onReview }: FinancialViewsProps) {
  if (fields.length === 0) {
    return (
      <section className="card-section financial-view">
        <p className="data-note">{emptyMessage}</p>
      </section>
    );
  }

  const kind = fields.find((field) => field.field_path === "financial.document_kind");
  const kindLabel = kind && isPresent(kind) ? String(kind.effective_value) : "Financial document";
  const found = fields.filter(isPresent);
  const missing = fields.filter((field) => !isPresent(field));
  const pending = fields.filter((field) => field.review_state === "pending").length;

  const summary = SUMMARY_FIELDS
    .map((path) => fields.find((field) => field.field_path === path))
    .filter((field): field is EvidenceField => Boolean(field));

  const groups: Array<{ name: string; fields: EvidenceField[] }> = [];
  for (const field of found) {
    const name = field.ui_group || "Details";
    const group = groups.find((item) => item.name === name);
    if (group) group.fields.push(field);
    else groups.push({ name, fields: [field] });
  }

  return (
    <div className="financial-view" role="tabpanel" aria-label="Financial document review">
      <section className="kyc-hero">
        <div>
          <span className="eyebrow">Financial evidence · source-linked extraction</span>
          <h2>{kindLabel}</h2>
          <p>{document?.filename ?? "Financial document"}</p>
        </div>
        <div className="financial-hero-meta">
          <span className="tag neutral">{found.length} of {fields.length} found</span>
          {pending ? <span className="tag warning">{pending} to review</span> : null}
        </div>
      </section>

      <section className="financial-summary" aria-label="Financial summary">
        {summary.map((field) => (
          <article className={`financial-summary-card ${isPresent(field) ? "" : "missing"}`} key={field.id}>
            <span>{field.label}</span>
            <strong>{displayValue(field)}</strong>
          </article>
        ))}
      </section>

      {groups.map((group) => (
        <section className="card-section" key={group.name} aria-label={group.name}>
          <div className="section-heading">
            <h3>{group.name}</h3>
          </div>
          <div className="evidence-list">
            {group.fields.map((field) => (
              <EvidenceRow key={field.id} field={field} onCitation={onCitation} onReview={onReview} />
            ))}
          </div>
        </section>
      ))}

      {found.length === 0 ? (
        <section className="card-section">
          <p className="quiet-message">
            No financial details were detected. Values are matched only when labelled, for example "Annual Income: 1800000".
          </p>
        </section>
      ) : null}

      {missing.length ? (
        <p className="financial-missing">
          <strong>Not detected:</strong> {missing.map((field) => field.label).join(", ")}
        </p>
      ) : null}

      <p className="data-note">Extracted values are used in the case assessment once reviewed.</p>
    </div>
  );
}
