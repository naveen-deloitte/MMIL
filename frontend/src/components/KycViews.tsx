import type { EvidenceField, DocumentSummary } from "../types";
import { EvidenceRow } from "./EvidenceViews";

export type KycViewId =
  | "overview"
  | "ai-assistant"
  | "identity"
  | "contact"
  | "bank_details"
  | "supporting_documents"
  | "consent";

export const kycViews: Array<{ id: KycViewId; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "ai-assistant", label: "AI Assistant" },
  { id: "identity", label: "Personal information" },
  { id: "contact", label: "Address & contact" },
  { id: "bank_details", label: "Bank details" },
  { id: "supporting_documents", label: "Documents" },
  { id: "consent", label: "Consent & declaration" },
];

interface KycViewsProps {
  activeView: KycViewId;
  document: DocumentSummary | null;
  fields: EvidenceField[];
  onCitation: (field: EvidenceField, citationIndex?: number) => void;
  onReview: (field: EvidenceField) => void;
}

export function KycViews({
  activeView,
  document,
  fields,
  onCitation,
  onReview,
}: KycViewsProps) {
  if (activeView === "overview" || activeView === "ai-assistant") {
    return (
      <KycOverview
        assistant={activeView === "ai-assistant"}
        document={document}
        fields={fields}
        onCitation={onCitation}
        onReview={onReview}
      />
    );
  }

  const sectionFields = fields.filter((field) => field.ui_section === activeView);
  const title = kycViews.find((view) => view.id === activeView)?.label ?? "KYC details";
  return (
    <section className="card-section kyc-fields-view" role="tabpanel" aria-label={title}>
      <div className="section-heading">
        <div>
          <h3>{title}</h3>
          <p>Extracted values stay linked to their source page for verification.</p>
        </div>
        <span className="tag neutral">{sectionFields.filter(isPresent).length} found</span>
      </div>
      {sectionFields.length ? (
        <div className="evidence-list">
          {sectionFields.map((field) => (
            <EvidenceRow
              key={field.id}
              field={field}
              onCitation={onCitation}
              onReview={onReview}
            />
          ))}
        </div>
      ) : (
        <p className="quiet-message">No fields are configured for this section.</p>
      )}
    </section>
  );
}

function KycOverview({
  assistant,
  document,
  fields,
  onCitation,
  onReview,
}: Omit<KycViewsProps, "activeView"> & { assistant: boolean }) {
  const found = fields.filter(isPresent);
  const missing = fields.length - found.length;
  const groups = [
    { key: "identity", label: "Personal information" },
    { key: "contact", label: "Address & contact" },
    { key: "bank_details", label: "Bank details" },
    { key: "supporting_documents", label: "Supporting documents" },
    { key: "consent", label: "Consent & declaration" },
  ].map(({ key, label }) => {
    const sectionFields = fields.filter((field) => field.ui_section === key);
    return {
      label,
      count: sectionFields.filter(isPresent).length,
      total: sectionFields.length,
      fields: sectionFields,
    };
  });

  return (
    <div className="kyc-overview" role="tabpanel" aria-label={assistant ? "AI Assistant" : "KYC Overview"}>
      {assistant ? (
        <section className="kyc-assistant-banner">
          <div className="kyc-assistant-mark" aria-hidden="true">K</div>
          <div>
            <span className="eyebrow">Local review assistant</span>
            <h2>Evidence-grounded KYC summary</h2>
            <p>
              This overview uses local field matching. Identity and bank details are not sent to an
              external AI provider, and no verification or eligibility decision is made.
            </p>
          </div>
          <span className="tag success">Private by design</span>
        </section>
      ) : (
        <section className="kyc-hero">
          <div>
            <span className="eyebrow">Individual KYC · source-linked extraction</span>
            <h2>{document?.filename ?? "KYC form"}</h2>
            <p>Review extracted details against the original form before using them.</p>
          </div>
          <span className={`status-badge status-${document?.status ?? "uploaded"}`}>
            {document?.status?.replaceAll("_", " ") ?? "Awaiting upload"}
          </span>
        </section>
      )}

      <div className="kyc-metrics" aria-label="KYC extraction summary">
        <article className="kyc-metric-card">
          <span>Details detected</span>
          <strong>{found.length}<small> / {fields.length}</small></strong>
        </article>
        <article className="kyc-metric-card">
          <span>Need review</span>
          <strong>{fields.filter((field) => field.review_state === "pending").length}</strong>
        </article>
        <article className="kyc-metric-card">
          <span>Not detected</span>
          <strong>{missing}</strong>
        </article>
      </div>

      <section className="card-section">
        <div className="section-heading">
          <div>
            <h3>{assistant ? "Review briefing" : "KYC profile overview"}</h3>
            <p>
              {found.length} of {fields.length} configured details were found in this document.
              {" "}Missing details are shown as not detected, not inferred.
            </p>
          </div>
        </div>
        <div className="kyc-section-grid">
          {groups.map((group) => (
            <article className="kyc-section-card" key={group.label}>
              <div>
                <h4>{group.label}</h4>
                <span>{group.count} / {group.total} found</span>
              </div>
              <div className="kyc-section-meter" aria-hidden="true">
                <span style={{ width: `${group.total ? (group.count / group.total) * 100 : 0}%` }} />
              </div>
              {group.fields.filter(isPresent).slice(0, assistant ? 4 : 2).map((field) => (
                <EvidenceRow
                  key={field.id}
                  field={field}
                  onCitation={onCitation}
                  onReview={onReview}
                />
              ))}
              {!group.count ? <p className="quiet-message">No details detected in this section.</p> : null}
            </article>
          ))}
        </div>
      </section>

      <p className="data-note">
        All extracted details require human verification. This local review aid does not validate
        identity documents, confirm bank records, or make financial or eligibility decisions.
      </p>
    </div>
  );
}

function isPresent(field: EvidenceField): boolean {
  return field.candidate_value !== null
    && field.candidate_value !== undefined
    && field.review_state !== "rejected";
}
