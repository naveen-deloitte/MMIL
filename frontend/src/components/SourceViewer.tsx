import { useEffect, useMemo, useState } from "react";
import { documentContentUrl } from "../api";
import { formatBytes } from "../format";
import type { DocumentSummary } from "../types";
import type { SourceSelection } from "../sourceState";
import { DrawerShell } from "./Drawers";

interface SourceViewerProps {
  documents: DocumentSummary[];
  selection: SourceSelection;
  onClose: () => void;
  onDocumentChange: (document: DocumentSummary) => void;
  onPageChange: (page: number) => void;
}

const processingStatuses = new Set(["uploaded", "scanning", "ocr", "extracting"]);

export function SourceViewer({
  documents,
  selection,
  onClose,
  onDocumentChange,
  onPageChange,
}: SourceViewerProps) {
  const selected = useMemo(
    () => documents.find((document) => document.id === selection.documentId) ?? documents[0],
    [documents, selection.documentId],
  );
  const [zoom, setZoom] = useState(1);
  useEffect(() => setZoom(1), [selected?.id]);

  const canPreview = selected?.viewable ?? false;
  const contentUrl = selected ? documentContentUrl(selected.id, selection.page) : "";
  const pageCount = selected?.page_count ?? 1;
  const page = Math.min(pageCount, Math.max(1, selection.page));
  const loading = selected !== undefined && !canPreview && processingStatuses.has(selected.status);

  return (
    <DrawerShell
      title={selected?.filename ?? "No document selected"}
      eyebrow="Source document"
      subtitle={selected ? `Version ${selected.version} · ${formatBytes(selected.size_bytes)}` : undefined}
      onClose={onClose}
      closeLabel="Close source document"
      drawerClassName="source-drawer"
      contentClassName="source-drawer-content"
    >
      {!selected ? (
        <div className="source-empty"><p>Upload a document to view it beside the evidence.</p></div>
      ) : (
        <>
          <div className="source-toolbar">
            <label>
              <span>Document</span>
              <select
                value={selected.id}
                onChange={(event) => {
                  const document = documents.find((item) => item.id === event.target.value);
                  if (document) onDocumentChange(document);
                }}
              >
                {documents.map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.filename} · v{document.version}
                  </option>
                ))}
              </select>
            </label>
            <div className="page-controls" aria-label="Document page controls">
              <button
                type="button"
                className="icon-button"
                onClick={() => onPageChange(page - 1)}
                disabled={page <= 1}
                aria-label="Previous page"
              >
                ‹
              </button>
              <span>Page {page} of {pageCount}</span>
              <button
                type="button"
                className="icon-button"
                onClick={() => onPageChange(page + 1)}
                disabled={page >= pageCount}
                aria-label="Next page"
              >
                ›
              </button>
            </div>
            {selected.media_type === "image/jpeg" || selected.media_type === "image/png" ? (
              <div className="zoom-controls" aria-label="Image zoom controls">
                <button type="button" className="icon-button" onClick={() => setZoom((value) => Math.max(0.5, value - 0.25))} aria-label="Zoom out">−</button>
                <span>{Math.round(zoom * 100)}%</span>
                <button type="button" className="icon-button" onClick={() => setZoom((value) => Math.min(3, value + 0.25))} aria-label="Zoom in">+</button>
              </div>
            ) : null}
          </div>
          {selection.excerpt ? (
            <div className="citation-excerpt" role="note">
              <strong>Cited excerpt · page {selection.page}</strong>
              <blockquote>{selection.excerpt}</blockquote>
            </div>
          ) : null}
          <div className="document-canvas">
            {!canPreview ? (
              <div className={`source-empty ${loading ? "source-loading" : "source-failed"}`} role={loading ? "status" : "alert"}>
                {loading ? <span className="spinner" aria-hidden="true" /> : null}
                <strong>{loading ? "Preparing document preview" : "Document preview unavailable"}</strong>
                <p>
                  {loading
                    ? `${selected.filename} is ${selected.status.replaceAll("_", " ")}. The preview will appear when the safety scan is complete.`
                    : selected.status === "failed"
                      ? `Document processing failed${selected.failure_code ? `: ${selected.failure_code.replaceAll("_", " ")}` : ""}. Retry processing from the document list.`
                      : "The original cannot be opened until it has passed the safety scan."}
                </p>
              </div>
            ) : selected.media_type === "application/pdf" ? (
              <iframe
                key={`${selected.id}-${page}`}
                src={contentUrl}
                title={`Source PDF: ${selected.filename}, page ${page}`}
              />
            ) : selected.media_type === "image/jpeg" || selected.media_type === "image/png" ? (
              <div className="image-stage">
                <img
                  src={contentUrl}
                  alt={`Uploaded source: ${selected.filename}`}
                  style={{ transform: `scale(${zoom})` }}
                />
              </div>
            ) : (
              <div className="source-empty">
                <p>This browser cannot preview the validated document format.</p>
                <a className="secondary-button" href={contentUrl} download={selected.filename}>Download authorized copy</a>
              </div>
            )}
          </div>
          <div className="source-footer">
            <span>SHA-256 {selected.sha256.slice(0, 12)}…</span>
            {canPreview
              ? <a href={contentUrl} download={selected.filename}>Download</a>
              : <span>{selected.status.replaceAll("_", " ")}</span>}
          </div>
        </>
      )}
    </DrawerShell>
  );
}
