import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { DocumentSummary, Workspace } from "./types";

const workspace: Workspace = {
  case: {
    id: "case-internal",
    external_case_id: "Dummy-Dummy-29495",
    applicant_display_name: "Dummy - Dummy",
    proposal_number: "MMIL-PROP-00018492",
    product_name: "Mahindra Manulife Life Protect Plus",
    workflow_stage: "human_review",
    sla_label: "2d 04h left",
  },
  documents: [{
    id: "doc-1",
    version: 1,
    filename: "synthetic-report.pdf",
    media_type: "application/pdf",
    size_bytes: 1000,
    sha256: "a".repeat(64),
    document_type: "medical_report",
    schema_version: "1.0.0",
    status: "review_required",
    failure_code: null,
    page_count: 2,
    viewable: true,
    created_at: "2026-08-14T10:00:00Z",
    job_id: "job-1",
    attempts: 1,
  }],
  runs: [{
    id: "run-1",
    document_id: "doc-1",
    sequence: 1,
    status: "succeeded",
    document_type: "medical_report",
    schema_version: "1.0.0",
    configuration_checksum: `sha256:${"a".repeat(64)}`,
    extractor_version: "deterministic-regex-1.0.0",
    provider: "deterministic-local",
    model_version: "not-applicable",
    prompt_version: "medical-report-1.1.0",
    started_at: "2026-08-14T10:00:01Z",
    completed_at: "2026-08-14T10:00:02Z",
    latency_ms: 1000,
    ai_analysis: null,
  }],
  fields: [{
    id: "field-tobacco",
    document_id: "doc-1",
    run_id: "run-1",
    field_path: "lifestyle.tobacco",
    label: "Tobacco",
    ui_section: "summary",
    ui_group: "Lifestyle and history",
    source_literal: "Yes, 5 cigarettes/day",
    candidate_value: "Yes, 5 cigarettes/day",
    effective_value: "Yes, 5 cigarettes/day",
    data_type: "text",
    unit: null,
    extraction_status: "found",
    confidence: 0.98,
    validations: [],
    citations: [{
      document_id: "doc-1",
      document_version: 1,
      page: 1,
      excerpt: "Tobacco: Yes, 5 cigarettes/day",
      bbox: null,
    }],
    review_state: "pending",
    review_version: 0,
    latest_review: null,
  }],
  additional_facts: [],
  counts: {
    found: 1,
    uncertain: 0,
    not_found: 0,
    pending: 1,
    accepted: 0,
    corrected: 0,
    rejected: 0,
    not_applicable: 0,
  },
};

beforeEach(() => window.history.replaceState({}, "", "/?case=Dummy-Dummy-29495"));
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("focused workbench", () => {
  it("lists cases and opens the selected case workspace with its history controls", async () => {
    window.history.replaceState({}, "", "/");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/cases") {
        return new Response(JSON.stringify([{
          case: workspace.case,
          document_count: 1,
          last_activity_at: "2026-08-14T10:00:02Z",
        }]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify(workspace), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Cases" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open case" }));

    expect(await screen.findByRole("heading", { name: /Dummy - Dummy/ })).toBeInTheDocument();
    expect(window.location.search).toContain("case=Dummy-Dummy-29495");
    expect(screen.getByRole("button", { name: "Audit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage documents 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "AI Assessment" }));
    expect(screen.getByRole("button", { name: /AI Summary/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Vitals" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Lab Reports" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Knockout Checks" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "AI Extraction Summary" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Configured Checks" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lab Results" })).not.toBeInTheDocument();
  });

  it("creates a case and opens its dedicated workspace", async () => {
    window.history.replaceState({}, "", "/");
    const newCase = {
      ...workspace.case,
      id: "new-case-internal",
      external_case_id: "UW-2027-001234",
      applicant_display_name: "Synthetic Applicant",
      proposal_number: "PROP-001234",
      product_name: "Life Protect Plus",
    };
    const newWorkspace: Workspace = {
      ...workspace,
      case: newCase,
      documents: [],
      runs: [],
      fields: [],
      additional_facts: [],
      counts: {
        found: 0,
        uncertain: 0,
        not_found: 0,
        pending: 0,
        accepted: 0,
        corrected: 0,
        rejected: 0,
        not_applicable: 0,
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/v1/cases" && init?.method === "POST") {
        return new Response(JSON.stringify(newCase), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (String(input) === "/api/v1/cases") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(newWorkspace), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Create new case" }));
    await user.type(screen.getByLabelText("Case ID"), "UW-2027-001234");
    await user.type(screen.getByLabelText("Applicant name"), "Synthetic Applicant");
    await user.type(screen.getByLabelText("Proposal number"), "PROP-001234");
    await user.type(screen.getByLabelText("Product"), "Life Protect Plus");
    await user.click(screen.getByRole("button", { name: "Create case" }));

    expect(await screen.findByRole("heading", { name: /Synthetic Applicant/ })).toBeInTheDocument();
    expect(window.location.search).toContain("case=UW-2027-001234");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/cases",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("loads the one medical page and opens citation source beside evidence", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: /Dummy - Dummy/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "AI Assessment" }));
    expect(screen.getByText(/Dummy-Dummy-29495/)).toBeInTheDocument();
    expect(screen.queryByText("Run simulation")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Page 1 source" }));

    const sourceDrawer = await screen.findByRole("dialog", { name: "synthetic-report.pdf" });
    expect(
      within(sourceDrawer)
        .getByText("Tobacco: Yes, 5 cigarettes/day"),
    ).toBeInTheDocument();
    const pdfFrame = screen.getByTitle(/Source PDF.*page 1/);
    expect(pdfFrame).toHaveAttribute("src", expect.stringContaining("#page=1"));
    expect(pdfFrame).not.toHaveAttribute("sandbox");
    await waitFor(() => expect(screen.getByText(/Opened Tobacco source on page 1/)).toBeInTheDocument());
  });

  it("shows a grounded empty state and does not invent medical values", async () => {
    const emptyWorkspace: Workspace = {
      ...workspace,
      documents: [],
      runs: [],
      fields: [],
      counts: {
        found: 0,
        uncertain: 0,
        not_found: 0,
        pending: 0,
        accepted: 0,
        corrected: 0,
        rejected: 0,
        not_applicable: 0,
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(emptyWorkspace), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "AI Assessment" }));
    expect(await screen.findByRole("heading", { name: "AI Medical Assessment Summary" })).toBeInTheDocument();
    expect(screen.getByText("No additional summary fields were extracted from this report.")).toBeInTheDocument();
    expect(screen.queryByText("26.1")).not.toBeInTheDocument();
    const caseHeader = screen.getByRole("region", { name: /Dummy - Dummy/ });
    await user.click(within(caseHeader).getByRole("button", { name: "View source" }));
    expect(screen.getByText("Upload a document before opening the source viewer.")).toBeInTheDocument();
  });

  it("opens the HITL review queue in a drawer and omits the removed header labels", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspace), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: /Dummy - Dummy/ })).toBeInTheDocument();
    expect(screen.queryByText("Illustrative case data · no live systems")).not.toBeInTheDocument();
    expect(screen.queryByText(/Signed in as/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /HITL review/ }));

    const reviewDrawer = screen.getByRole("dialog", { name: "Evidence review" });
    expect(within(reviewDrawer).getByText("Critical · needs review")).toBeInTheDocument();
    expect(within(reviewDrawer).getByRole("heading", { name: /^Advisory notes/ })).toBeInTheDocument();
    expect(within(reviewDrawer).getByText("Tobacco")).toBeInTheDocument();
    await user.click(within(reviewDrawer).getByRole("button", { name: /Tobacco/ }));
    const fieldDrawer = await screen.findByRole("dialog", { name: "Tobacco" });
    expect(within(fieldDrawer).getByText("Candidate value")).toBeInTheDocument();
    await user.click(within(fieldDrawer).getByRole("button", { name: "Close review" }));
    expect(screen.queryByRole("dialog", { name: "Evidence review" })).not.toBeInTheDocument();
  });

  it("shows a loading state in the source drawer while the document is queued", async () => {
    const queuedWorkspace: Workspace = {
      ...workspace,
      documents: [{ ...workspace.documents[0], status: "scanning", viewable: false }],
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(queuedWorkspace), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "View source" }));
    const sourceDrawer = screen.getByRole("dialog", { name: "synthetic-report.pdf" });
    expect(within(sourceDrawer).getByRole("status")).toHaveTextContent("Preparing document preview");
    expect(within(sourceDrawer).getByText(/is scanning/)).toBeInTheDocument();
    expect(within(sourceDrawer).queryByTitle(/Source PDF/)).not.toBeInTheDocument();
  });

  it("shows a failure state instead of leaving the source viewer loading", async () => {
    const failedWorkspace: Workspace = {
      ...workspace,
      documents: [{
        ...workspace.documents[0],
        status: "failed",
        failure_code: "internal_processing_error",
        viewable: false,
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(failedWorkspace), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "View source" }));
    const sourceDrawer = screen.getByRole("dialog", { name: "synthetic-report.pdf" });
    expect(within(sourceDrawer).getByRole("alert")).toHaveTextContent("Document processing failed");
    expect(within(sourceDrawer).getByRole("alert")).toHaveTextContent("internal processing error");
  });

  it("uploads a selected file and opens its queued source drawer", async () => {
    const uploadedDocument: DocumentSummary = {
      ...workspace.documents[0],
      id: "doc-uploaded",
      filename: "synthetic-upload.pdf",
      status: "uploaded",
      viewable: false,
      job_id: "job-uploaded",
    };
    const updatedWorkspace = {
      ...workspace,
      documents: [uploadedDocument, ...workspace.documents],
    };
    let uploaded = false;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        uploaded = true;
        return new Response(JSON.stringify({ document: uploadedDocument, replayed: false }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(uploaded ? updatedWorkspace : workspace), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<App />);

    await screen.findByRole("heading", { name: /Dummy - Dummy/ });
    const input = container.querySelector<HTMLInputElement>("#document-upload");
    if (!input) throw new Error("Document upload input was not rendered");
    const file = new File(["synthetic test document"], "synthetic-upload.pdf", {
      type: "application/pdf",
    });
    fireEvent.change(input, { target: { files: [file] } });

    const sourceDrawer = await screen.findByRole("dialog", { name: file.name });
    expect(within(sourceDrawer).getByRole("status")).toHaveTextContent("Preparing document preview");
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/cases/Dummy-Dummy-29495/documents",
      expect.objectContaining({
        method: "POST",
        body: expect.any(FormData),
      }),
    ));
    expect(await screen.findByText("synthetic-upload.pdf uploaded. Processing is queued.")).toBeInTheDocument();
  });

  it("uploads KYC with its selected type and opens the local review assistant", async () => {
    const kycDocument: DocumentSummary = {
      ...workspace.documents[0],
      id: "doc-kyc",
      filename: "filled-kyc.pdf",
      document_type: "kyc_individual",
      status: "review_required",
    };
    const kycField = {
      ...workspace.fields[0],
      id: "field-kyc-surname",
      document_id: kycDocument.id,
      run_id: "run-kyc",
      field_path: "identity.surname",
      label: "Surname",
      ui_section: "identity" as const,
      ui_group: "Personal information",
      source_literal: "Sample",
      candidate_value: "Sample",
      effective_value: "Sample",
      citations: [{
        document_id: kycDocument.id,
        document_version: 1,
        page: 1,
        excerpt: "Surname: Sample",
        bbox: null,
      }],
    };
    const kycWorkspace: Workspace = {
      ...workspace,
      documents: [kycDocument],
      runs: [{
        ...workspace.runs[0],
        id: "run-kyc",
        document_id: kycDocument.id,
        document_type: "kyc_individual",
      }],
      fields: [kycField],
      additional_facts: [],
    };
    let uploadedType: string | null = null;
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        uploadedType = (init.body as FormData).get("document_type") as string;
        return new Response(JSON.stringify({ document: kycDocument, replayed: false }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify(uploadedType ? kycWorkspace : workspace), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { container } = render(<App />);

    await screen.findByRole("heading", { name: /Dummy - Dummy/ });
    await user.selectOptions(screen.getByLabelText("Document type"), "kyc_individual");
    const input = container.querySelector<HTMLInputElement>("#document-upload");
    if (!input) throw new Error("Document upload input was not rendered");
    fireEvent.change(input, {
      target: {
        files: [new File(["synthetic KYC form"], "filled-kyc.pdf", { type: "application/pdf" })],
      },
    });

    expect(await screen.findByRole("button", { name: "AI Assistant" })).toBeInTheDocument();
    expect(screen.getByText("KYC profile overview")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close source document" }));
    await user.click(screen.getByRole("button", { name: "AI Assistant" }));
    expect(screen.getByText("Evidence-grounded KYC summary")).toBeInTheDocument();
    expect(screen.getByText(/not sent to an external AI provider/i)).toBeInTheDocument();
    expect(uploadedType).toBe("kyc_individual");
  });

  it("shows AI-selected facts with confidence and a cited source excerpt", async () => {
    const workspaceWithFact: Workspace = {
      ...workspace,
      additional_facts: [{
        id: "fact-1",
        document_id: "doc-1",
        run_id: "run-1",
        name: "Additional medical note",
        category: "note",
        source_literal: "Medication reported",
        value: "Medication reported",
        data_type: "text",
        unit: null,
        extraction_status: "found",
        confidence: 0.91,
        validations: [],
        citations: [{
          document_id: "doc-1",
          document_version: 1,
          page: 2,
          excerpt: "Medication: Example medicine",
          bbox: null,
        }],
        linked_field_path: null,
      }],
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(workspaceWithFact), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    })));
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "AI Assessment" }));
    await user.click(screen.getByRole("button", { name: "AI Selected Facts" }));

    expect(screen.getByText("Additional medical note")).toBeInTheDocument();
    expect(screen.getByText("91% confidence")).toBeInTheDocument();
    expect(screen.getByText("Medication: Example medicine")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Page 2 source" })).toBeInTheDocument();
  });

  it("provides the full underwriting section navigation and reference overview cards", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/cases") {
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/audit")) {
        return new Response(JSON.stringify({ items: [], next_offset: null }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify(workspace), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Case overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Risk heatmap" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Data completeness" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Next best actions" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Underwriting queue" })).toBeInTheDocument();

    for (const section of ["Overview", "AI Assessment", "Underwriting", "Documents", "Simulator", "Decision", "Ask AI", "Audit"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${section}$`) })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("button", { name: /^Underwriting$/ }));
    expect(screen.getByRole("button", { name: "Financial review" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Documents$/ }));
    expect(screen.getByRole("heading", { name: /^Documents$/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Simulator$/ }));
    expect(screen.getByText(/Approved product rates, coverage inputs, and underwriting rules are not connected/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Decision$/ }));
    expect(screen.getByText("No decision recorded")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Ask AI$/ }));
    expect(screen.getByRole("heading", { name: "Case chat is not connected" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Audit$/ }));
    expect(await screen.findByText("No audit events are available.")).toBeInTheDocument();
  });
});
