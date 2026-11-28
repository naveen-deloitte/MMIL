import { useCallback, useEffect, useState } from "react";

import { ApiError, loadIdentitySummary, submitIdentityReview, verifyIdentity } from "../api";
import type {
  EvidenceField,
  IdentityDocument,
  IdentityMatch,
  IdentitySubject,
  IdentitySummary,
  IdentityVerification,
  MatchStatus,
  VerificationStatus,
} from "../types";
import { EvidenceRow } from "./EvidenceViews";

const MATCH_LABELS: Record<MatchStatus, string> = {
  match: "Match",
  normalized_match: "Match (normalized)",
  review_required: "Review Required",
  mismatch: "Mismatch",
  not_available: "Not Available",
  not_applicable: "N/A",
};

// Official authenticity verification. Only "verified" ever reads as verified.
const VERIFICATION_LABELS: Record<VerificationStatus, string> = {
  not_verified: "Not Verified",
  not_configured: "Not Verified · provider not configured",
  verified: "Verified",
  failed: "Verification Failed",
  consent_missing: "Not Verified · consent required",
  provider_error: "Not Verified · provider error",
};

const SUBJECT_LABELS: Record<IdentitySubject, string> = { aadhaar: "Aadhaar", pan: "PAN" };

export function MatchBadge({ status }: { status: MatchStatus }) {
  return <span className={`identity-badge match-${status}`}>{MATCH_LABELS[status]}</span>;
}

export function VerificationBadge({ status }: { status: VerificationStatus }) {
  return <span className={`identity-badge verification-${status}`}>{VERIFICATION_LABELS[status]}</span>;
}

function StateBadge({ value }: { value: string }) {
  return <span className={`identity-badge state-${value}`}>{value.replaceAll("_", " ")}</span>;
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail;
  return error instanceof Error ? error.message : "The operation could not be completed.";
}

interface IdentityProps {
  caseId: string;
  /** Changes whenever the workspace changes so this view reloads its data. */
  refreshKey: string;
  onCitation: (field: EvidenceField, citationIndex?: number) => void;
  onReview: (field: EvidenceField) => void;
  onOpenDocument: (documentId: string) => void;
  onChanged: () => void;
}

export function IdentityVerificationView({
  caseId,
  refreshKey,
  onCitation,
  onReview,
  onOpenDocument,
  onChanged,
}: IdentityProps) {
  const [summary, setSummary] = useState<IdentitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await loadIdentitySummary(caseId));
    } catch (failure) {
      setError(messageFor(failure));
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  if (loading && !summary) {
    return <p role="status" className="data-note">Loading identity verification…</p>;
  }
  if (error && !summary) {
    return (
      <div className="section-empty-state" role="alert">
        <strong>Identity verification is unavailable</strong>
        <p>{error}</p>
        <button type="button" className="secondary-button" onClick={() => void load()}>Try again</button>
      </div>
    );
  }
  if (!summary) return null;

  const nothingUploaded = summary.documents.every((doc) => doc.state === "not_uploaded");
  return (
    <div className="identity-view">
      {error ? <p role="alert" className="identity-error">{error}</p> : null}
      <IdentityOverview summary={summary} />
      {nothingUploaded ? (
        <div className="section-empty-state">
          <strong>No Aadhaar or PAN document uploaded</strong>
          <p>
            Choose "Aadhaar Card" or "PAN Card" in the Document type list, then add the document.
            Extraction, validation and KYC comparison start automatically.
          </p>
        </div>
      ) : null}
      {summary.documents.map((document) => (
        <IdentityDocumentCard
          key={document.subject}
          document={document}
          verification={summary.verification.find((item) => item.subject === document.subject)}
          onCitation={onCitation}
          onReview={onReview}
          onOpenDocument={onOpenDocument}
        />
      ))}
      <ComparisonTable summary={summary} onOpenDocument={onOpenDocument} />
      <OfficialVerification
        caseId={caseId}
        summary={summary}
        onUpdated={(next) => {
          setSummary(next);
          onChanged();
        }}
        onError={setError}
      />
      <HumanReview
        caseId={caseId}
        summary={summary}
        onUpdated={(next) => {
          setSummary(next);
          onChanged();
        }}
        onError={setError}
      />
    </div>
  );
}

function IdentityOverview({ summary }: { summary: IdentitySummary }) {
  const { stages } = summary;
  return (
    <section className="card-section identity-overview" aria-label="Identity overview">
      <div className="section-heading"><h3>Identity overview</h3></div>
      <p className="data-note">
        Each step below is separate. Extraction, format validation and KYC matching never imply that
        a document is authentic. Only official verification does.
      </p>
      <table className="identity-table">
        <thead>
          <tr><th>Step</th><th>Aadhaar</th><th>PAN</th></tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row">Document uploaded</th>
            <td><StateBadge value={stages.document_uploaded.aadhaar} /></td>
            <td><StateBadge value={stages.document_uploaded.pan} /></td>
          </tr>
          <tr>
            <th scope="row">Information extracted</th>
            <td><StateBadge value={stages.information_extracted.aadhaar} /></td>
            <td><StateBadge value={stages.information_extracted.pan} /></td>
          </tr>
          <tr>
            <th scope="row">Data validation (format)</th>
            <td><StateBadge value={`validation_${stages.format_validated.aadhaar}`} /></td>
            <td><StateBadge value={`validation_${stages.format_validated.pan}`} /></td>
          </tr>
          <tr>
            <th scope="row">KYC matching</th>
            <td colSpan={2}><MatchBadge status={summary.match_status} /></td>
          </tr>
          <tr>
            <th scope="row">Official verification</th>
            {summary.verification.map((item) => (
              <td key={item.subject}><VerificationBadge status={item.status} /></td>
            ))}
          </tr>
          <tr>
            <th scope="row">Human review</th>
            <td colSpan={2}><StateBadge value={`review_${stages.human_review_completed}`} /></td>
          </tr>
        </tbody>
      </table>
      <h4>Outstanding issues</h4>
      {summary.issues.length === 0 ? (
        <p className="data-note">No outstanding issues.</p>
      ) : (
        <ul className="identity-issues">
          {summary.issues.map((issue, index) => (
            <li key={`${issue.code}-${issue.subject}-${issue.field}-${index}`} className={`issue-${issue.severity}`}>
              {issue.subject ? <strong>{SUBJECT_LABELS[issue.subject]}: </strong> : null}
              {issue.message}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function IdentityDocumentCard({
  document,
  verification,
  onCitation,
  onReview,
  onOpenDocument,
}: {
  document: IdentityDocument;
  verification: IdentityVerification | undefined;
  onCitation: IdentityProps["onCitation"];
  onReview: IdentityProps["onReview"];
  onOpenDocument: IdentityProps["onOpenDocument"];
}) {
  const title = document.subject === "aadhaar" ? "Aadhaar details" : "PAN details";
  const identityFields = document.fields.filter((field) => field.ui_section !== "additional");
  return (
    <section className="card-section" aria-label={title}>
      <div className="section-heading">
        <h3>{title}</h3>
        <div className="identity-card-actions">
          <StateBadge value={document.state} />
          {document.document_id ? (
            <button type="button" className="text-button" onClick={() => onOpenDocument(document.document_id as string)}>
              Open original
            </button>
          ) : null}
        </div>
      </div>
      {document.state === "not_uploaded" ? (
        <p className="data-note">Not uploaded.</p>
      ) : null}
      {document.state === "processing" ? <p role="status" className="data-note">Processing…</p> : null}
      {document.state === "failed" ? (
        <div role="alert" className="identity-error">
          <strong>Processing failed{document.failure_code ? ` (${document.failure_code})` : ""}.</strong>
          {document.action_required ? <p>{document.action_required}</p> : null}
        </div>
      ) : null}
      {document.state === "extracted" ? (
        <>
          <div className="field-meta">
            <span>
              Extraction confidence:{" "}
              {document.extraction_confidence === null ? "n/a" : `${Math.round(document.extraction_confidence * 100)}%`}
            </span>
            {verification ? <VerificationBadge status={verification.status} /> : null}
          </div>
          {identityFields.map((field) => (
            <EvidenceRow key={field.id} field={field} onCitation={onCitation} onReview={onReview} />
          ))}
          {document.fields
            .filter((field) => field.ui_section === "additional" && field.candidate_value !== null)
            .map((field) => (
              <EvidenceRow key={field.id} field={field} onCitation={onCitation} onReview={onReview} />
            ))}
        </>
      ) : null}
    </section>
  );
}

function ComparisonTable({
  summary,
  onOpenDocument,
}: {
  summary: IdentitySummary;
  onOpenDocument: IdentityProps["onOpenDocument"];
}) {
  const documentIds = Object.fromEntries(summary.documents.map((doc) => [doc.subject, doc.document_id]));
  const show = (value: string | null, row: IdentityMatch, source: string) => {
    if (row.not_applicable_sources.includes(source)) return <span className="muted">N/A</span>;
    return value ?? <span className="muted">Not available</span>;
  };
  return (
    <section className="card-section" aria-label="Cross-document comparison">
      <div className="section-heading"><h3>Cross-document comparison</h3></div>
      <p className="data-note">
        Values come from the extracted documents. Applicant KYC details are never changed here.
      </p>
      <table className="identity-table comparison-table">
        <thead>
          <tr><th>Field</th><th>KYC form</th><th>Aadhaar</th><th>PAN</th><th>Result</th></tr>
        </thead>
        <tbody>
          {summary.matches.map((row) => (
            <tr key={row.field} className={row.match_status === "mismatch" ? "mismatch-row" : ""}>
              <th scope="row">{row.label}</th>
              <td>{show(row.kyc_value, row, "kyc")}</td>
              <td>{show(row.aadhaar_value, row, "aadhaar")}</td>
              <td>{show(row.pan_value, row, "pan")}</td>
              <td>
                <MatchBadge status={row.match_status} />
                <div className="match-explanation">{row.explanation}</div>
                {row.match_status === "mismatch" || row.match_status === "review_required" ? (
                  <div className="identity-card-actions">
                    {(["aadhaar", "pan"] as const).map((subject) =>
                      documentIds[subject] && !row.not_applicable_sources.includes(subject) ? (
                        <button
                          key={subject}
                          type="button"
                          className="text-button"
                          onClick={() => onOpenDocument(documentIds[subject] as string)}
                        >
                          Open {SUBJECT_LABELS[subject]}
                        </button>
                      ) : null,
                    )}
                  </div>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function OfficialVerification({
  caseId,
  summary,
  onUpdated,
  onError,
}: {
  caseId: string;
  summary: IdentitySummary;
  onUpdated: (summary: IdentitySummary) => void;
  onError: (message: string | null) => void;
}) {
  const [consent, setConsent] = useState(false);
  const [panNumber, setPanNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const panConfigured = summary.verification.find((item) => item.subject === "pan")?.configured ?? false;

  async function run() {
    setBusy(true);
    onError(null);
    try {
      const result = await verifyIdentity(caseId, {
        subjects: ["aadhaar", "pan"],
        consent: { given: consent, purpose: "KYC identity verification" },
        ...(panNumber.trim() ? { pan_number: panNumber.trim() } : {}),
      });
      setPanNumber("");
      onUpdated(result.summary);
    } catch (failure) {
      onError(messageFor(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card-section" aria-label="Official verification">
      <div className="section-heading"><h3>Official verification</h3></div>
      <p className="data-note">
        Authenticity can only be confirmed through an authorized provider. A readable QR code, a valid
        format or a successful OCR read is not verification.
      </p>
      <ul className="verification-list">
        {summary.verification.map((item) => (
          <li key={item.subject}>
            <strong>{SUBJECT_LABELS[item.subject]}</strong> <VerificationBadge status={item.status} />
            {item.reason_code ? <span className="muted"> ({item.reason_code})</span> : null}
            {item.verified_at ? <span className="muted"> · {new Date(item.verified_at).toLocaleString()}</span> : null}
          </li>
        ))}
      </ul>
      <label className="identity-consent">
        <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
        The applicant has given consent for official identity verification.
      </label>
      {panConfigured ? (
        <label className="identity-pan-input">
          <span>PAN from the original document (used once, never stored)</span>
          <input
            type="password"
            autoComplete="off"
            value={panNumber}
            onChange={(event) => setPanNumber(event.target.value)}
          />
        </label>
      ) : null}
      <button type="button" className="secondary-button" disabled={busy} onClick={() => void run()}>
        {busy ? "Checking…" : "Run verification check"}
      </button>
    </section>
  );
}

function HumanReview({
  caseId,
  summary,
  onUpdated,
  onError,
}: {
  caseId: string;
  summary: IdentitySummary;
  onUpdated: (summary: IdentitySummary) => void;
  onError: (message: string | null) => void;
}) {
  const mismatched = summary.matches.filter((row) => row.match_status === "mismatch");
  const [decision, setDecision] = useState<"confirmed" | "rejected" | "follow_up_required">("confirmed");
  const [rationale, setRationale] = useState("");
  const [resolved, setResolved] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const canReview = summary.documents.some((doc) => doc.state === "extracted");

  async function submit() {
    setBusy(true);
    onError(null);
    try {
      onUpdated(
        await submitIdentityReview(caseId, {
          decision,
          rationale: rationale.trim() || undefined,
          resolved_fields: resolved,
        }),
      );
      setRationale("");
    } catch (failure) {
      onError(messageFor(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card-section" aria-label="Identity review">
      <div className="section-heading"><h3>Identity review</h3></div>
      <p>
        Status: <StateBadge value={`review_${summary.review.status}`} />
        {summary.review.decision ? <span className="muted"> · {summary.review.decision.replaceAll("_", " ")}</span> : null}
      </p>
      {summary.review.status === "stale" ? (
        <p className="data-note">The data changed after the last review. Review it again.</p>
      ) : null}
      <label>
        <span>Decision</span>
        <select aria-label="Identity decision" value={decision} onChange={(event) => setDecision(event.target.value as typeof decision)}>
          <option value="confirmed">Confirm identity</option>
          <option value="follow_up_required">Follow-up required</option>
          <option value="rejected">Reject</option>
        </select>
      </label>
      {mismatched.length ? (
        <fieldset>
          <legend>Mismatches resolved</legend>
          {mismatched.map((row) => (
            <label key={row.field}>
              <input
                type="checkbox"
                checked={resolved.includes(row.field)}
                onChange={(event) =>
                  setResolved((current) =>
                    event.target.checked ? [...current, row.field] : current.filter((item) => item !== row.field),
                  )
                }
              />
              {row.label}
            </label>
          ))}
        </fieldset>
      ) : null}
      <label>
        <span>Rationale</span>
        <textarea
          aria-label="Identity review rationale"
          value={rationale}
          maxLength={2000}
          onChange={(event) => setRationale(event.target.value)}
        />
      </label>
      <button type="button" className="primary-button" disabled={busy || !canReview} onClick={() => void submit()}>
        {busy ? "Saving…" : "Record identity review"}
      </button>
      <p className="data-note">
        This records your review only. Underwriting decisions remain with the authorized underwriter.
      </p>
    </section>
  );
}
