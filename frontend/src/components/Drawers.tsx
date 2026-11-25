import { useEffect, useRef } from "react";

import { formatBytes, formatTimestamp } from "../format";
import type { AuditEvent, DocumentSummary } from "../types";

export interface DrawerShellProps {
  title: string;
  eyebrow: string;
  subtitle?: string;
  onClose: () => void;
  closeLabel?: string;
  drawerClassName?: string;
  contentClassName?: string;
  children: React.ReactNode;
}

export function DrawerShell({
  title,
  eyebrow,
  subtitle,
  onClose,
  closeLabel,
  drawerClassName = "",
  contentClassName = "",
  children,
}: DrawerShellProps) {
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    drawerRef.current?.querySelector<HTMLElement>("button")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !drawerRef.current) return;
      const controls = Array.from(
        drawerRef.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex='0']",
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
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus();
    };
  }, []);

  return (
    <div className="drawer-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <aside
        ref={drawerRef}
        className={`drawer ${drawerClassName}`.trim()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="drawer-title"
      >
        <div className="dialog-header">
          <div>
            <span className="eyebrow">{eyebrow}</span>
            <h2 id="drawer-title">{title}</h2>
            {subtitle ? <p className="drawer-subtitle">{subtitle}</p> : null}
          </div>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            aria-label={closeLabel ?? `Close ${title}`}
          >
            ×
          </button>
        </div>
        <div className={`drawer-content ${contentClassName}`.trim()}>{children}</div>
      </aside>
    </div>
  );
}

export function DocumentsDrawer({
  documents,
  onClose,
  onView,
  onRetry,
}: {
  documents: DocumentSummary[];
  onClose: () => void;
  onView: (document: DocumentSummary) => void;
  onRetry: (document: DocumentSummary) => void;
}) {
  return (
    <DrawerShell title="Case documents" eyebrow="Immutable source versions" onClose={onClose}>
      {!documents.length ? <p className="quiet-message">No documents have been uploaded.</p> : (
        <div className="document-list">
          {documents.map((document) => (
            <article className="document-item" key={document.id}>
              <div className="document-icon" aria-hidden="true">{document.media_type === "application/pdf" ? "PDF" : "IMG"}</div>
              <div className="document-details">
                <h3>{document.filename}</h3>
                <p>Version {document.version} · {formatBytes(document.size_bytes)} · {document.page_count ?? "?"} page(s)</p>
                <p>Schema {document.schema_version} · uploaded {formatTimestamp(document.created_at)}</p>
                <span className={`status-badge status-${document.status}`}>{document.status.replaceAll("_", " ")}</span>
                {document.failure_code ? <span className="safe-error">{document.failure_code.replaceAll("_", " ")}</span> : null}
              </div>
              <div className="document-actions">
                <button type="button" className="secondary-button compact" onClick={() => onView(document)} disabled={!document.viewable}>View source</button>
                {document.status === "failed" ? <button type="button" className="text-button" onClick={() => onRetry(document)}>Retry</button> : null}
              </div>
            </article>
          ))}
        </div>
      )}
    </DrawerShell>
  );
}

export function AuditDrawer({
  events,
  loading,
  error,
  onClose,
}: {
  events: AuditEvent[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <DrawerShell title="Case audit history" eyebrow="Read-only event metadata" onClose={onClose}>
      <div className="notice blue">Audit entries exclude document text, extracted values, corrections, and review rationale.</div>
      {loading ? <p role="status">Loading audit history…</p> : null}
      {error ? <p role="alert" className="form-error">{error}</p> : null}
      {!loading && !events.length ? <p className="quiet-message">No audit events are available.</p> : null}
      <ol className="audit-list">
        {events.map((event) => (
          <li key={event.id}>
            <span className={`audit-dot ${event.outcome === "success" ? "success" : "warning"}`} aria-hidden="true" />
            <div>
              <h3>{event.action.replaceAll(".", " · ").replaceAll("_", " ")}</h3>
              <p>{event.actor_subject} · {formatTimestamp(event.occurred_at)}</p>
              <small>Outcome: {event.outcome.replaceAll("_", " ")} · Correlation {event.correlation_id}</small>
            </div>
          </li>
        ))}
      </ol>
    </DrawerShell>
  );
}
