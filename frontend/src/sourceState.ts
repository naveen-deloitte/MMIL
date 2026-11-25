import type { Citation, DocumentSummary } from "./types";

export interface SourceSelection {
  caseId: string;
  open: boolean;
  documentId: string | null;
  page: number;
  excerpt: string | null;
  fieldId: string | null;
}

export function initialSourceSelection(caseId: string): SourceSelection {
  return {
    caseId,
    open: false,
    documentId: null,
    page: 1,
    excerpt: null,
    fieldId: null,
  };
}

export function selectCitation(
  state: SourceSelection,
  caseId: string,
  fieldId: string,
  citation: Citation,
): SourceSelection {
  const base = state.caseId === caseId ? state : initialSourceSelection(caseId);
  return {
    ...base,
    open: true,
    documentId: citation.document_id,
    page: citation.page,
    excerpt: citation.excerpt,
    fieldId,
  };
}

export function selectDocument(
  state: SourceSelection,
  caseId: string,
  document: DocumentSummary,
): SourceSelection {
  const base = state.caseId === caseId ? state : initialSourceSelection(caseId);
  return {
    ...base,
    open: true,
    documentId: document.id,
    page: 1,
    excerpt: null,
    fieldId: null,
  };
}
