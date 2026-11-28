import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CaseListItem, DocumentSummary, ProposalItem, ProposalView } from "../types";
import { DashboardWorkload } from "./DashboardWorkload";
import { ProposalDetails, formatProposalValue } from "./ProposalDetails";
import { ProposalViewer } from "./ProposalViewer";

const doc: DocumentSummary = {
  id: "doc-p",
  version: 1,
  filename: "proposal-form.pdf",
  media_type: "application/pdf",
  size_bytes: 2048,
  sha256: "b".repeat(64),
  document_type: "proposal_form",
  schema_version: "1.0.0",
  status: "completed",
  failure_code: null,
  page_count: 3,
  viewable: true,
  created_at: "2026-11-20T10:00:00Z",
  job_id: "job",
  attempts: 1,
};

function item(overrides: Partial<ProposalItem>): ProposalItem {
  return {
    key: "x", label: "X", value: null, kind: "text", currency: "INR", source: null, highlight: false,
    note: null, citations: [], document_id: null, verified: null, evidence: [], ...overrides,
  };
}

const view: ProposalView = {
  case_id: "UW-1",
  proposal_number: "P-1",
  has_product_selection: true,
  catalogue: { is_demo: true, catalogue_id: "demo", catalogue_version: "1.0.0", note: null },
  proposal_document: doc,
  proposal_document_count: 1,
  sections: [
    { id: "basic", title: "Basic proposal information", items: [
      item({ key: "insurer", label: "Insurance company", value: "Insurer One", source: "product_selection" }),
      item({ key: "channel", label: "Application channel", value: null }),
    ] },
    { id: "coverage", title: "Coverage & premium details", items: [
      item({ key: "sum_assured", label: "Proposed sum assured", value: 10000000, kind: "money", source: "product_selection", highlight: true }),
      item({ key: "annual_premium", label: "Proposed annual premium", value: 14160, kind: "money", source: "product_selection", highlight: true, note: "Indicative catalogue premium, not an official insurer quote." }),
      item({ key: "policy_term", label: "Policy term", value: 20, kind: "years", source: "product_selection" }),
    ] },
    { id: "benefits", title: "Policy benefits", items: [
      item({ key: "death_benefit", label: "Death benefit", value: "Sum assured on death", source: "product_catalogue" }),
    ] },
    { id: "declarations", title: "Applicant declarations", items: [
      item({
        key: "annual_income", label: "Annual income", value: 1800000, kind: "money", source: "proposal_form",
        note: "Applicant declaration on the proposal form; not independently verified.",
        citations: [{ document_id: "doc-p", document_version: 1, page: 2, excerpt: "Annual Income: 1800000" }],
        evidence: [{ label: "Annual income", value: 1500000, currency: "INR", source: "document_evidence", verified: true, status: "Reviewed by underwriter", filename: "itr.pdf", citations: [] }],
      }),
    ] },
  ],
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("proposal details", () => {
  it("shows subsections, prominent values, sources and Not Available", async () => {
    const onCitation = vi.fn();
    const onOpenProposal = vi.fn();
    render(<ProposalDetails view={view} loading={false} error={null} onRetry={vi.fn()} onCitation={onCitation} onOpenProposal={onOpenProposal} />);
    for (const title of ["Basic proposal information", "Coverage & premium details", "Policy benefits", "Applicant declarations"]) {
      expect(screen.getByRole("region", { name: title })).toBeInTheDocument();
    }
    const coverage = screen.getByRole("region", { name: "Coverage & premium details" });
    expect(within(coverage).getByText("₹1,00,00,000.00")).toBeInTheDocument();
    expect(within(coverage).getByText("₹14,160.00")).toBeInTheDocument();
    expect(within(coverage).getByText("20 years")).toBeInTheDocument();
    const basic = screen.getByRole("region", { name: "Basic proposal information" });
    expect(within(basic).queryByText("Application channel")).not.toBeInTheDocument();

    const declarations = screen.getByRole("region", { name: "Applicant declarations" });
    expect(within(declarations).getByText("Verified evidence")).toBeInTheDocument();
    expect(within(declarations).getByText(/not independently verified/)).toBeInTheDocument();
    await userEvent.click(within(declarations).getByRole("button", { name: "Page 2 source" }));
    expect(onCitation).toHaveBeenCalledWith(expect.objectContaining({ page: 2, document_id: "doc-p" }));
    await userEvent.click(screen.getByRole("button", { name: "View proposal document" }));
    expect(onOpenProposal).toHaveBeenCalled();
    expect(screen.getByText(/Demo product catalogue/)).toBeInTheDocument();
  });

  it("formats values without inventing data", () => {
    expect(formatProposalValue({ value: null, kind: "money", currency: "INR" })).toBe("Not Available");
    expect(formatProposalValue({ value: { base: 1000, tax: 180, total: 1180 }, kind: "breakdown", currency: "INR" }))
      .toBe("Base ₹1,000.00 + tax ₹180.00 = ₹1,180.00");
  });

  it("hides the document button when there is no proposal document", () => {
    render(<ProposalDetails view={{ ...view, proposal_document: null }} loading={false} error={null} onRetry={vi.fn()} onCitation={vi.fn()} onOpenProposal={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "View proposal document" })).not.toBeInTheDocument();
  });
});

const caseItem = (id: string, stage: string): CaseListItem => ({
  case: {
    id: `internal-${id}`, external_case_id: id, applicant_display_name: `Applicant ${id}`, proposal_number: `P-${id}`,
    product_name: "Demo Term Shield", workflow_stage: stage, sla_label: "Not set",
  },
  document_count: 1,
  last_activity_at: "2026-11-28T10:00:00Z",
});

describe("My Cases View Proposal", () => {
  it("places View Proposal beside Continue review and keeps the existing action", async () => {
    const onOpen = vi.fn();
    const onViewProposal = vi.fn();
    render(
      <DashboardWorkload
        cases={[caseItem("UW-A", "human_review"), caseItem("UW-B", "resolved")]}
        demoCase={null}
        demoCaseError={null}
        onOpen={onOpen}
        onCreateCase={vi.fn()}
        onViewProposal={onViewProposal}
      />,
    );
    const continueButton = screen.getByRole("button", { name: "Continue review UW-A" });
    const proposalButton = screen.getByRole("button", { name: "View proposal UW-A" });
    expect(continueButton.parentElement).toBe(proposalButton.parentElement);
    expect(continueButton.parentElement).toHaveClass("queue-action-buttons");
    expect(proposalButton.querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("button", { name: "View proposal UW-B" })).toBeInTheDocument();
    await userEvent.click(proposalButton);
    expect(onViewProposal).toHaveBeenCalledWith("UW-A");
    expect(onOpen).not.toHaveBeenCalled();
    await userEvent.click(continueButton);
    expect(onOpen).toHaveBeenCalledWith("UW-A");
  });
});

function stubProposalDocument(body: unknown) {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL) =>
    new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("proposal viewer", () => {
  it("opens that case's original proposal with its proposal number", async () => {
    const fetchMock = stubProposalDocument({
      case_id: "UW-A", proposal_number: "P-UW-A", applicant_display_name: "Applicant A",
      available: true, message: null, original: doc, documents: [doc],
    });
    render(<ProposalViewer caseId="UW-A" onClose={vi.fn()} />);
    expect(await screen.findByTitle(/Source PDF: proposal-form.pdf, page 1/)).toBeInTheDocument();
    expect(screen.getByText(/Proposal P-UW-A · Applicant A/)).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute("href", expect.stringContaining("/documents/doc-p/content"));
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/v1/cases/UW-A/proposal/document");
  });

  it("shows the case's saved proposal details when no proposal document was uploaded", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).endsWith("/proposal/document")
        ? { case_id: "UW-B", proposal_number: "P-UW-B", applicant_display_name: "B", available: false, message: "x", original: null, documents: [] }
        : { ...view, case_id: "UW-B", proposal_document: null };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    render(<ProposalViewer caseId="UW-B" onClose={vi.fn()} />);
    expect(await screen.findByText(/Showing the proposal details captured when the case was created/)).toBeInTheDocument();
    expect(await screen.findByText("Insurer One")).toBeInTheDocument();
    expect(screen.getByText("₹1,00,00,000.00")).toBeInTheDocument();
    expect(screen.queryByTitle(/Source PDF/)).not.toBeInTheDocument();
  });
});
