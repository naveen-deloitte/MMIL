import { describe, expect, it } from "vitest";
import { initialSourceSelection, selectCitation, selectDocument } from "./sourceState";
import type { Citation, DocumentSummary } from "./types";

const document: DocumentSummary = {
  id: "doc-1",
  version: 2,
  filename: "report.pdf",
  media_type: "application/pdf",
  size_bytes: 100,
  sha256: "a".repeat(64),
  document_type: "medical_report",
  schema_version: "1.0.0",
  status: "review_required",
  failure_code: null,
  page_count: 3,
  viewable: true,
  created_at: "2026-01-01T00:00:00Z",
  job_id: "job-1",
  attempts: 1,
};

const citation: Citation = {
  document_id: "doc-1",
  document_version: 2,
  page: 3,
  excerpt: "HbA1c: 5.4 %",
  bbox: null,
};

describe("source selection", () => {
  it("maps a citation to its exact immutable document, page, and excerpt", () => {
    const selected = selectCitation(initialSourceSelection("case-1"), "case-1", "field-1", citation);
    expect(selected).toEqual({
      caseId: "case-1",
      open: true,
      documentId: "doc-1",
      page: 3,
      excerpt: "HbA1c: 5.4 %",
      fieldId: "field-1",
    });
  });

  it("does not carry source state across cases", () => {
    const oldState = selectCitation(initialSourceSelection("case-1"), "case-1", "field-1", citation);
    const next = selectDocument(oldState, "case-2", document);
    expect(next.caseId).toBe("case-2");
    expect(next.documentId).toBe("doc-1");
    expect(next.page).toBe(1);
    expect(next.excerpt).toBeNull();
    expect(next.fieldId).toBeNull();
  });
});
