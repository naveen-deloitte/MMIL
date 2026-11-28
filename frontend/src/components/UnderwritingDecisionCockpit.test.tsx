import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Workspace } from "../types";
import { UnderwritingDecisionCockpit } from "./UnderwritingDecisionCockpit";

function workspace(policy: Record<string, unknown> | null): Workspace {
  return {
    case: {
      id: "c1",
      external_case_id: "UW-1",
      applicant_display_name: "Applicant",
      proposal_number: "P-1",
      product_name: "Demo Term Shield",
      workflow_stage: "human_review",
      sla_label: "Not set",
      policy_details: policy,
    },
    documents: [],
    runs: [],
    fields: [],
    additional_facts: [],
    counts: { found: 0, uncertain: 0, not_found: 0, pending: 0, accepted: 0, corrected: 0, rejected: 0, not_applicable: 0 },
    case_review: { open_flags: 0, documents_analysed: 0, cross_document_conflicts: 0, resolved_flags: 0, processing_documents: 0, exceptions: [] },
  } as Workspace;
}

function stubHistory(value: Workspace) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    case: value.case,
    readiness: {
      source_documents_total: 1,
      source_documents_complete: true,
      evidence_reviews_pending: 0,
      evidence_review_complete: true,
      pending_critical_flags: 0,
      outstanding_information_requests: null,
      information_requests_tracked: false,
      underwriting_guidelines_available: false,
      authority_available: true,
      mandatory_prerequisites_met: true,
      underwriter_subject: "reviewer-demo",
      demo_case: false,
    },
    decisions: [],
  }), { status: 200, headers: { "Content-Type": "application/json" } })));
}

function renderCockpit(value: Workspace) {
  stubHistory(value);
  render(
    <UnderwritingDecisionCockpit
      workspace={value}
      onReview={vi.fn()}
      onRequirements={vi.fn()}
      onOpenAssessment={vi.fn()}
      onDecisionRecorded={vi.fn()}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("decision cockpit approve defaults", () => {
  it("pre-fills sum assured and premium from the proposed terms, editable", async () => {
    renderCockpit(workspace({ sum_assured: 5000000, indicative_quote: { status: "indicative", amount: 7080 } }));
    await userEvent.click(await screen.findByRole("radio", { name: "Approve" }));
    const sumAssured = screen.getByLabelText("Approved sum assured");
    const premium = screen.getByLabelText("Applicable premium");
    expect(sumAssured).toHaveValue(5000000);
    expect(premium).toHaveValue(7080);
    expect(screen.getByText(/Pre-filled from the proposed terms.*not an official insurer quote/)).toBeInTheDocument();
    await userEvent.clear(premium);
    await userEvent.type(premium, "9000");
    expect(premium).toHaveValue(9000);
    // Switching outcome and back keeps the underwriter's edit.
    await userEvent.click(screen.getByRole("radio", { name: "Decline" }));
    await userEvent.click(screen.getByRole("radio", { name: "Approve" }));
    expect(screen.getByLabelText("Applicable premium")).toHaveValue(9000);
  });

  it("leaves premium empty when no indicative premium was calculated", async () => {
    renderCockpit(workspace({ sum_assured: 500000, indicative_quote: { status: "not_available", amount: null } }));
    await userEvent.click(await screen.findByRole("radio", { name: "Approve" }));
    expect(screen.getByLabelText("Approved sum assured")).toHaveValue(500000);
    expect(screen.getByLabelText("Applicable premium")).toHaveValue(null);
    expect(screen.getByText(/No proposed premium is available/)).toBeInTheDocument();
  });

  it("keeps both empty for cases without a catalogue product", async () => {
    renderCockpit(workspace(null));
    await userEvent.click(await screen.findByRole("radio", { name: "Approve" }));
    expect(screen.getByLabelText("Approved sum assured")).toHaveValue(null);
    expect(screen.getByLabelText("Applicable premium")).toHaveValue(null);
    expect(screen.getByText(/not available from connected product data/)).toBeInTheDocument();
  });
});
