import { useEffect, useState } from "react";

import { ApiError, loadProposalDocument } from "../api";
import type { ProposalDocumentResponse } from "../types";
import { initialSourceSelection, selectDocument, type SourceSelection } from "../sourceState";
import { DrawerShell } from "./Drawers";
import { ProposalDetails, useProposal } from "./ProposalDetails";
import { SourceViewer } from "./SourceViewer";

function messageFor(error: unknown): string {
  if (error instanceof ApiError) return error.problem.detail;
  return error instanceof Error ? error.message : "The proposal document could not be loaded.";
}

/**
 * Opens the original proposal form uploaded to ``caseId`` in the existing source viewer.
 * Only that case's proposal forms are listed; access and auditing are enforced by the API.
 */
export function ProposalViewer({ caseId, onClose }: { caseId: string; onClose: () => void }) {
  const [response, setResponse] = useState<ProposalDocumentResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<SourceSelection>(() => initialSourceSelection(caseId));

  useEffect(() => {
    let active = true;
    setResponse(null);
    setError(null);
    loadProposalDocument(caseId)
      .then((result) => {
        if (!active) return;
        setResponse(result);
        if (result.original) setSelection((current) => selectDocument(current, caseId, result.original!));
      })
      .catch((failure) => { if (active) setError(messageFor(failure)); });
    return () => { active = false; };
  }, [caseId]);

  if (response?.available && response.original) {
    return (
      <SourceViewer
        documents={response.documents}
        selection={selection}
        eyebrow="Proposal document"
        context={`Proposal ${response.proposal_number} · ${response.applicant_display_name}`}
        onClose={onClose}
        onDocumentChange={(document) => setSelection((current) => selectDocument(current, caseId, document))}
        onPageChange={(page) => setSelection((current) => ({ ...current, page }))}
      />
    );
  }

  return (
    <DrawerShell
      title={response ? `Proposal ${response.proposal_number}` : `Case ${caseId}`}
      eyebrow="Proposal document"
      onClose={onClose}
      closeLabel="Close proposal document"
      drawerClassName="source-drawer"
      contentClassName="source-drawer-content"
    >
      <div className="document-canvas">
        {error ? (
          <div className="source-empty source-failed" role="alert">
            <strong>Proposal document could not be opened</strong>
            <p>{error}</p>
          </div>
        ) : !response ? (
          <div className="source-empty source-loading" role="status">
            <span className="spinner" aria-hidden="true" />
            <strong>Loading proposal document…</strong>
          </div>
        ) : (
          <div className="proposal-viewer-fallback">
            <div className="identity-review-warning" role="status">
              Showing the proposal details captured when the case was created.
            </div>
            <SavedProposalDetails caseId={caseId} />
          </div>
        )}
      </div>
    </DrawerShell>
  );
}

/** Proposal details saved with the case; loaded only when no proposal document exists. */
function SavedProposalDetails({ caseId }: { caseId: string }) {
  const proposal = useProposal(caseId, "fallback");
  return (
    <ProposalDetails
      view={proposal.view}
      loading={proposal.loading}
      error={proposal.error}
      onRetry={() => void proposal.reload()}
      onCitation={() => undefined}
      onOpenProposal={() => undefined}
    />
  );
}
