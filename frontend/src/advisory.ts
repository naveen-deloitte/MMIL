import type { EvidenceField } from "./types";

/** Short reviewer-facing labels for advisory codes produced by the backend review policy. */
const ADVISORY_LABELS: Record<string, string> = {
  name_variation: "Name written differently",
  medium_confidence: "Moderate read confidence",
  recommended_field_missing: "Expected field not found",
  required_field_missing: "Required field not found",
  signature_date_old: "Signed over a year ago",
  report_date_old: "Report older than six months",
  date_in_future: "Date is in the future",
};

export interface AdvisoryNote {
  key: string;
  field: EvidenceField;
  code: string;
  label: string;
  message: string;
  priority: "high" | "normal";
}

/**
 * Non-blocking notes: issues not critical enough for HITL that the reviewer should still see.
 * Fields already pending in HITL are excluded, so nothing is listed twice.
 */
export function advisoryNotes(fields: EvidenceField[]): AdvisoryNote[] {
  const notes: AdvisoryNote[] = [];
  for (const field of fields) {
    if (field.review_state === "pending") continue;
    for (const finding of field.validations) {
      const isAdvisory = finding.severity === "advisory" || finding.code === "required_field_missing";
      if (!isAdvisory) continue;
      notes.push({
        key: `${field.id}:${finding.code}`,
        field,
        code: finding.code,
        label: ADVISORY_LABELS[finding.code] ?? finding.code.replaceAll("_", " "),
        message: finding.message ?? "",
        priority: finding.code === "required_field_missing" ? "high" : "normal",
      });
    }
  }
  return notes.sort((a, b) => (a.priority === b.priority ? 0 : a.priority === "high" ? -1 : 1));
}

/** Accepted by the system (auto_accepted marker) and not later overridden by a person. */
export function isAutoAccepted(field: EvidenceField): boolean {
  return (
    field.review_state === "accepted"
    && !field.latest_review
    && field.validations.some((finding) => finding.code === "auto_accepted")
  );
}
