import { useEffect, useRef, useState } from "react";
import { formatValue } from "../format";
import type { EvidenceField, ReviewDecision, ReviewPayload } from "../types";

interface ReviewDialogProps {
  field: EvidenceField;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (payload: ReviewPayload) => Promise<void>;
  onViewSource: () => void;
}

export function ReviewDialog({
  field,
  busy,
  error,
  onClose,
  onSubmit,
  onViewSource,
}: ReviewDialogProps) {
  const [decision, setDecision] = useState<ReviewDecision>(
    field.review_state === "pending" || field.review_state === "not_reviewable"
      ? "accepted"
      : field.review_state,
  );
  const [correction, setCorrection] = useState(formatValue(field.effective_value));
  const [rationale, setRationale] = useState("");
  const titleRef = useRef<HTMLHeadingElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const busyRef = useRef(busy);
  const closeRef = useRef(onClose);
  busyRef.current = busy;
  closeRef.current = onClose;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    titleRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key === "Tab" && dialogRef.current) {
        const controls = Array.from(
          dialogRef.current.querySelectorAll<HTMLElement>(
            "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex='0']",
          ),
        );
        if (!controls.length) return;
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, []);

  const rationaleRequired = ["corrected", "rejected", "not_applicable"].includes(decision);
  const correctionRequired = decision === "corrected";
  const valid = (!rationaleRequired || rationale.trim().length > 0) &&
    (!correctionRequired || correction.trim().length > 0);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!valid || busy) return;
    await onSubmit({
      field_id: field.id,
      decision,
      expected_version: field.review_version,
      corrected_value: correctionRequired ? correction : undefined,
      rationale: rationale.trim() || undefined,
    });
  }

  return (
    <div className="drawer-backdrop review-dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onClose();
    }}>
      <section ref={dialogRef} className="drawer review-dialog" role="dialog" aria-modal="true" aria-labelledby="review-title">
        <div className="dialog-header">
          <div>
            <span className="eyebrow">Human evidence review</span>
            <h2 id="review-title" ref={titleRef} tabIndex={-1}>{field.label}</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} disabled={busy} aria-label="Close review">×</button>
        </div>
        <form onSubmit={submit}>
          <div className="dialog-body">
            <div className="candidate-box">
              <span>Candidate value</span>
              <strong>{formatValue(field.candidate_value)}{field.unit ? ` ${field.unit}` : ""}</strong>
              <button type="button" className="text-button" onClick={onViewSource} disabled={!field.citations.length}>
                {field.citations.length ? `View source on page ${field.citations[0].page}` : "No citation available"}
              </button>
            </div>
            {field.citations[0] ? <blockquote className="review-quote">{field.citations[0].excerpt}</blockquote> : null}
            <fieldset className="decision-options">
              <legend>Review decision</legend>
              {([
                ["accepted", "Accept", "Use the extracted value"],
                ["corrected", "Correct", "Record a verified replacement"],
                ["rejected", "Reject", "Do not use this candidate"],
                ["not_applicable", "Not applicable", "The field does not apply"],
              ] as const).map(([value, label, help]) => (
                <label className={decision === value ? "selected" : ""} key={value}>
                  <input
                    type="radio"
                    name="decision"
                    value={value}
                    checked={decision === value}
                    onChange={() => setDecision(value)}
                  />
                  <span><strong>{label}</strong><small>{help}</small></span>
                </label>
              ))}
            </fieldset>
            {correctionRequired ? (
              <label className="form-field">
                Corrected value
                <input
                  value={correction}
                  onChange={(event) => setCorrection(event.target.value)}
                  required
                  inputMode={field.data_type === "decimal" || field.data_type === "integer" ? "decimal" : "text"}
                />
                <small>Expected type: {field.data_type}{field.unit ? ` · ${field.unit}` : ""}</small>
              </label>
            ) : null}
            <label className="form-field">
              Rationale {rationaleRequired ? <span aria-hidden="true">*</span> : <span>(optional)</span>}
              <textarea
                value={rationale}
                onChange={(event) => setRationale(event.target.value)}
                required={rationaleRequired}
                maxLength={2000}
                rows={3}
                placeholder="Explain what you verified without copying unnecessary health information."
              />
            </label>
            {error ? <div className="form-error" role="alert">{error}</div> : null}
          </div>
          <div className="dialog-footer">
            <button type="button" className="secondary-button" onClick={onClose} disabled={busy}>Cancel</button>
            <button type="submit" className="primary-button" disabled={!valid || busy}>
              {busy ? "Saving…" : "Save review"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
