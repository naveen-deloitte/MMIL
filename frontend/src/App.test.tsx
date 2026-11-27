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
  case_review: {
    open_flags: 1,
    documents_analysed: 1,
    cross_document_conflicts: 0,
    resolved_flags: 0,
    processing_documents: 0,
    exceptions: [{
      id: "field:field-tobacco",
      kind: "field",
      category: "Review required",
      title: "Tobacco requires review",
      status: "pending",
      severity: "warning",
      field_ids: ["field-tobacco"],
      document_ids: ["doc-1"],
      message: "The extraction pipeline marked Tobacco for human review.",
    }],
  },
};

function workspaceResponse(input: RequestInfo | URL, value: Workspace): Response {
  const url = String(input);
  if (url.includes("/extractions/history")) {
    const encodedId = url.match(/\/documents\/([^/]+)\/extractions\/history/)?.[1];
    const documentId = encodedId ? decodeURIComponent(encodedId) : "";
    const document = value.documents.find((item) => item.id === documentId);
    return new Response(JSON.stringify({
      document,
      runs: value.runs
        .filter((run) => run.document_id === documentId)
        .map((run) => ({
          run,
          field_count: value.fields.filter((field) => field.run_id === run.id).length,
          pending_fields: value.fields.filter((field) => field.run_id === run.id && field.review_state === "pending").length,
          reviewed_fields: value.fields.filter((field) => field.run_id === run.id && field.latest_review !== null).length,
        })),
    }), { status: 200, headers: { "Content-Type": "application/json" } });
  }
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function stubWorkspaceFetch(value: Workspace = workspace) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => workspaceResponse(input, value)));
}

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
      return workspaceResponse(input, workspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Underwriting Workbench" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "My Cases" })).toBeInTheDocument();
    const workloadKpis = screen.getByRole("region", { name: "Underwriting workload summary" });
    expect(within(workloadKpis).getByRole("button", { name: /Under Review/ })).toHaveTextContent("1");
    expect(within(workloadKpis).getByRole("button", { name: /Awaiting Information/ })).toHaveTextContent("0");
    expect(within(screen.getByRole("table")).getByText("Under Review")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continue review Dummy-Dummy-29495" }));

    expect(await screen.findByRole("heading", { name: /Dummy - Dummy/ })).toBeInTheDocument();
    expect(window.location.search).toContain("case=Dummy-Dummy-29495");
    expect(screen.getByRole("button", { name: "Underwriting Assessment" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage documents 1" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Document Review" }));
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
      return workspaceResponse(input, newWorkspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByText("No cases in this workspace yet")).toBeInTheDocument();
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

  it("filters and clears the underwriting queue without changing case data", async () => {
    window.history.replaceState({}, "", "/");
    const secondCase = {
      ...workspace.case,
      id: "case-second",
      external_case_id: "UW-002",
      applicant_display_name: "Priya Example",
      proposal_number: "PROP-002",
      product_name: "Term Plan",
      workflow_stage: "awaiting_documents",
      sla_label: "1d left",
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
      { case: workspace.case, document_count: 0, last_activity_at: "2026-08-14T10:00:02Z" },
      { case: secondCase, document_count: 0, last_activity_at: "2026-08-14T10:00:02Z" },
    ]), { status: 200, headers: { "Content-Type": "application/json" } })));
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText("Priya Example");
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);

    await user.click(screen.getByRole("tab", { name: /Awaiting Information/ }));
    await user.type(screen.getByRole("textbox", { name: "Search applicant, case ID, or policy/application number" }), "UW-002");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(within(table).getByText("Priya Example")).toBeInTheDocument();
    expect(within(table).queryByText("Dummy - Dummy")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Filters/ }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by product type" }), "Term Plan");
    expect(within(table).getByText("Priya Example")).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Clear all filters" }));
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("Dummy - Dummy")).toBeInTheDocument();
  });

  it("uses exclusive workflow statuses for KPI filters and keeps resolved decision details accessible", async () => {
    window.history.replaceState({}, "", "/");
    const cases = [
      { ...workspace.case, id: "case-new", external_case_id: "UW-NEW", workflow_stage: "assigned" },
      { ...workspace.case, id: "case-review", external_case_id: "UW-REVIEW", workflow_stage: "human_review" },
      {
        ...workspace.case,
        id: "case-resolved",
        external_case_id: "UW-RESOLVED",
        workflow_stage: "resolved",
        final_decision: "Approved",
        decision_date: "2026-08-15T12:00:00Z",
        underwriter_subject: "underwriter@example.test",
        decision_rationale: "All required evidence reviewed.",
      },
      { ...workspace.case, id: "case-pending", external_case_id: "UW-PENDING", workflow_stage: "pending" },
      { ...workspace.case, id: "case-awaiting", external_case_id: "UW-AWAITING", workflow_stage: "awaiting_documents" },
      { ...workspace.case, id: "case-escalated", external_case_id: "UW-HILT", workflow_stage: "hilt_escalated" },
    ];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/cases") {
        return new Response(JSON.stringify(cases.map((item) => ({
          case: item,
          document_count: 0,
          last_activity_at: "2026-08-14T10:00:02Z",
        }))), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return workspaceResponse(input, workspace);
    }));
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText("UW-NEW");
    expect(screen.queryByRole("tab", { name: /HILT \/ Escalated/ })).not.toBeInTheDocument();
    const workloadKpis = screen.getByRole("region", { name: "Underwriting workload summary" });
    for (const label of ["New / Assigned", "Under Review", "Resolved", "Awaiting Information"]) {
      expect(within(workloadKpis).getByRole("button", { name: new RegExp(label) })).toHaveTextContent("1");
    }
    expect(within(workloadKpis).getByRole("button", { name: /Pending/ })).toHaveTextContent("2");
    expect(within(workloadKpis).getByText("6")).toBeInTheDocument();

    const table = screen.getByRole("table");
    const kpiCases = [
      ["New / Assigned", "UW-NEW"],
      ["Under Review", "UW-REVIEW"],
      ["Pending", "UW-PENDING"],
      ["Awaiting Information", "UW-AWAITING"],
      ["Resolved", "UW-RESOLVED"],
    ] as const;
    for (const [label, caseId] of kpiCases) {
      const card = within(workloadKpis).getByRole("button", { name: new RegExp(label) });
      await user.click(card);
      expect(within(table).getByText(caseId)).toBeInTheDocument();
      expect(within(table).getAllByRole("row")).toHaveLength(label === "Pending" ? 3 : 2);
      if (label === "Pending") expect(within(table).getByText("UW-HILT")).toBeInTheDocument();
      await user.click(card);
    }

    await user.click(within(workloadKpis).getByRole("button", { name: /Resolved/ }));
    expect(screen.getByText("UW-RESOLVED")).toBeInTheDocument();
    expect(within(table).queryByText("UW-AWAITING")).not.toBeInTheDocument();

    await user.click(screen.getByText("Decision details"));
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("underwriter@example.test")).toBeInTheDocument();
    expect(screen.getByText("All required evidence reviewed.")).toBeInTheDocument();
    await user.click(within(workloadKpis).getByRole("button", { name: /Pending/ }));
    expect(screen.getByText("UW-HILT")).toBeInTheDocument();
    expect(screen.queryByText("UW-RESOLVED")).not.toBeInTheDocument();
  });

  it("sorts and paginates filtered cases", async () => {
    window.history.replaceState({}, "", "/");
    const cases = Array.from({ length: 12 }, (_, index) => ({
      ...workspace.case,
      id: `case-${index}`,
      external_case_id: `UW-${String(index + 1).padStart(2, "0")}`,
      applicant_display_name: `Applicant ${String(12 - index).padStart(2, "0")}`,
      workflow_stage: "human_review",
    }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/cases") {
        return new Response(JSON.stringify(cases.map((item) => ({
          case: item,
          document_count: 0,
          last_activity_at: "2026-08-14T10:00:02Z",
        }))), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return workspaceResponse(input, workspace);
    }));
    const user = userEvent.setup();
    render(<App />);

    await screen.findByText("UW-01");
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(11);
    await user.click(screen.getByRole("button", { name: "Sort by Applicant Name" }));
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Applicant 01");
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("UW-02")).toBeInTheDocument();
  });

  it("keeps the case-list error and retry action visible when loading fails", async () => {
    window.history.replaceState({}, "", "/");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ detail: "Service unavailable" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("opens the isolated demo case and records a variance decision", async () => {
    window.history.replaceState({}, "", "/");
    const demoCase = {
      ...workspace.case,
      id: "demo-case-id",
      external_case_id: "MMIL-DEMO-001",
      applicant_display_name: "Ananya Sharma",
      proposal_number: "MMIL-DEMO-001",
      product_name: "Individual Life Insurance",
      workflow_stage: "underwriting_variance_review",
      sla_label: "Demo only — not an SLA",
      is_demo: true,
    };
    const demoWorkspace: Workspace = {
      ...workspace,
      case: demoCase,
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
    const variance = {
      id: "variance-1",
      category: "premium",
      title: "Premium Variance",
      applied_value: 50000,
      suggested_value: 60000,
      difference: 10000,
      currency: "INR",
      recommendation_source: "DEMO – Simulated Approved Pricing Recommendation",
      recommendation_rationale: "Simulated recommendation for the demo only.",
      status: "pending",
      current_decision: null,
      history: [],
    };
    const initialVarianceWorkspace = {
      case: demoCase,
      demo_mode: true,
      variances: [variance],
      pending_variances: 1,
      resolved_variances: 0,
      total_variances: 1,
      cases_requiring_decision: 1,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/cases") {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url === "/api/v1/cases/MMIL-DEMO-001/workspace") {
        return workspaceResponse(url, demoWorkspace);
      }
      if (url === "/api/v1/cases/MMIL-DEMO-001/underwriting-variances") {
        return new Response(JSON.stringify(initialVarianceWorkspace), { status: 200 });
      }
      if (url.endsWith("/decisions") && init?.method === "POST") {
        const payload = JSON.parse(String(init.body));
        const decision = {
          id: "decision-1",
          decision: payload.decision,
          selected_value: 60000,
          justification: payload.justification,
          reviewer_subject: "reviewer-demo",
          approval_status: "demo_only",
          reviewed_at: "2026-11-26T05:30:00Z",
        };
        return new Response(JSON.stringify({
          ...initialVarianceWorkspace,
          variances: [{ ...variance, status: "resolved", current_decision: decision, history: [decision] }],
          pending_variances: 0,
          resolved_variances: 1,
          cases_requiring_decision: 0,
        }), { status: 200 });
      }
      return workspaceResponse(input, demoWorkspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    const demoRow = await screen.findByRole("row", { name: /Ananya Sharma/ });
    expect(within(demoRow).getByText("Demo · simulated")).toBeInTheDocument();
    expect(within(demoRow).getByText("MMIL-DEMO-001")).toBeInTheDocument();
    const workloadKpis = screen.getByRole("region", { name: "Underwriting workload summary" });
    expect(within(workloadKpis).getAllByText("0")).toHaveLength(6);
    await user.click(within(demoRow).getByRole("button", {
      name: "Continue review MMIL-DEMO-001",
    }));
    expect(await screen.findByRole("heading", { name: "Ananya Sharma" })).toBeInTheDocument();
    expect(screen.getByText("DEMO · SIMULATED DATA")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Underwriting Variance Review" }));
    expect(await screen.findByRole("heading", { name: "Premium Variance" })).toBeInTheDocument();
    expect(screen.getByText("+₹10,000")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: /Accept suggested/ }));
    await user.type(screen.getByLabelText(/Decision justification/), "Accept for client demo.");
    await user.click(screen.getByRole("button", { name: "Submit decision" }));

    expect(await screen.findByText("Suggested value accepted")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/cases/MMIL-DEMO-001/underwriting-variances/variance-1/decisions",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.getByText(/does not change the original application/)).toBeInTheDocument();
  });

  it("loads the one medical page and opens citation source beside evidence", async () => {
    stubWorkspaceFetch();
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: /Dummy - Dummy/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Document Review" }));
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
    stubWorkspaceFetch(emptyWorkspace);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Document Review" }));
    expect(await screen.findByText("No documents uploaded")).toBeInTheDocument();
    expect(screen.queryByText("26.1")).not.toBeInTheDocument();
    const caseHeader = screen.getByRole("region", { name: /Dummy - Dummy/ });
    await user.click(within(caseHeader).getByRole("button", { name: "View source" }));
    expect(screen.getByText("Upload a document before opening the source viewer.")).toBeInTheDocument();
  });

  it("shows case-level HITL exceptions and opens the existing auditable review dialog", async () => {
    stubWorkspaceFetch();
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: /Dummy - Dummy/ })).toBeInTheDocument();
    expect(screen.queryByText("Illustrative case data · no live systems")).not.toBeInTheDocument();
    expect(screen.queryByText(/Signed in as/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "HITL Review" }));

    expect(screen.getByText("Tobacco requires review")).toBeInTheDocument();
    expect(screen.getByText("1 open flags")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review field" }));
    const fieldDrawer = await screen.findByRole("dialog", { name: "Tobacco" });
    expect(within(fieldDrawer).getByText("Candidate value")).toBeInTheDocument();
    await user.click(within(fieldDrawer).getByRole("button", { name: "Close review" }));
    expect(screen.queryByRole("dialog", { name: "Tobacco" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Request requirements" }));
    expect(screen.getByRole("dialog", { name: "Evidence review" })).toBeInTheDocument();
  });

  it("requires confirmation and permanently removes a document from the active case", async () => {
    const emptyWorkspace: Workspace = {
      ...workspace,
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
      case_review: {
        open_flags: 0,
        documents_analysed: 0,
        cross_document_conflicts: 0,
        resolved_flags: 0,
        processing_documents: 0,
        exceptions: [],
      },
    };
    let removed = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        removed = true;
        return new Response(JSON.stringify({ document_id: "doc-1", deleted: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return workspaceResponse(input, removed ? emptyWorkspace : workspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Remove document" }));
    const confirmation = screen.getByRole("alertdialog", { name: /Remove synthetic-report\.pdf/ });
    expect(within(confirmation).getByText(/permanently deletes the original file/i)).toBeInTheDocument();
    await user.click(within(confirmation).getByRole("button", { name: "Permanently remove" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/documents/doc-1",
      expect.objectContaining({ method: "DELETE" }),
    ));
    expect(await screen.findByText("No documents uploaded")).toBeInTheDocument();
    expect(screen.getByText(/synthetic-report\.pdf and its extracted evidence were permanently removed/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("shows a loading state in the source drawer while the document is queued", async () => {
    const queuedWorkspace: Workspace = {
      ...workspace,
      documents: [{ ...workspace.documents[0], status: "scanning", viewable: false }],
    };
    stubWorkspaceFetch(queuedWorkspace);
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
    stubWorkspaceFetch(failedWorkspace);
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        uploaded = true;
        return new Response(JSON.stringify({ document: uploadedDocument, replayed: false }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        });
      }
      return workspaceResponse(input, uploaded ? updatedWorkspace : workspace);
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
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "POST") {
        uploadedType = (init.body as FormData).get("document_type") as string;
        return new Response(JSON.stringify({ document: kycDocument, replayed: false }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        });
      }
      return workspaceResponse(input, uploadedType ? kycWorkspace : workspace);
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
    stubWorkspaceFetch(workspaceWithFact);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Document Review" }));
    await user.click(screen.getByRole("button", { name: "AI Selected Facts" }));

    expect(screen.getByText("Additional medical note")).toBeInTheDocument();
    expect(screen.getByText("91% confidence")).toBeInTheDocument();
    expect(screen.getByText("Medication: Example medicine")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Page 2 source" })).toBeInTheDocument();
  });

  it("provides the four case sections and nests underwriting tools in the assessment area", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/cases") {
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/audit")) {
        return new Response(JSON.stringify({ items: [], next_offset: null }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("/underwriting-decisions")) {
        return new Response(JSON.stringify({
          case: workspace.case,
          readiness: {
            source_documents_total: 1,
            source_documents_complete: false,
            evidence_reviews_pending: 1,
            evidence_review_complete: false,
            pending_critical_flags: 1,
            outstanding_information_requests: null,
            information_requests_tracked: false,
            underwriting_guidelines_available: false,
            authority_available: true,
            mandatory_prerequisites_met: false,
            underwriter_subject: "reviewer-demo",
            demo_case: false,
          },
          decisions: [],
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return workspaceResponse(input, workspace);
    }));
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Underwriting Assessment" }));
    expect(await screen.findByRole("heading", { name: "Case overview" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Risk heatmap" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Data completeness" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Next best actions" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Cases" })).not.toBeInTheDocument();
    expect(screen.queryByText("Queues", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "My underwriting queue" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "SLA watch" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Search underwriting cases" })).not.toBeInTheDocument();

    for (const section of ["Document Review", "HITL Review", "Case Evidence", "Underwriting Assessment"]) {
      expect(screen.getByRole("button", { name: new RegExp(`^${section}$`) })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("button", { name: /^Underwriting$/ }));
    expect(screen.getByRole("button", { name: "Financial review" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Simulator$/ }));
    expect(screen.getByText(/Approved product rates, coverage inputs, and underwriting rules are not connected/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Decision$/ }));
    expect(screen.getByText("No decision recorded")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Final underwriting decision" })).toBeInTheDocument();
    expect(screen.getByText("Outstanding information requests")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review and confirm decision" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: /^Ask AI$/ }));
    expect(screen.getByRole("heading", { name: "Case chat is not connected" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Audit$/ }));
    expect(await screen.findByText("No audit events are available.")).toBeInTheDocument();
  });

  it("keeps decisions to the supported outcomes and confirms the required details before recording", async () => {
    const readyWorkspace: Workspace = {
      ...workspace,
      documents: [{ ...workspace.documents[0], status: "completed" }],
      runs: [{
        ...workspace.runs[0],
        provider: "test-ai",
        ai_analysis: {
          summary: {
            text: "The source report records a relevant medical history.",
            citations: [{
              document_id: "doc-1",
              document_version: 1,
              page: 1,
              excerpt: "Relevant medical history",
              bbox: null,
            }],
          },
          key_medical_findings: [],
          recommendations: [],
          vitals_summary: null,
          major_vital_factors: [],
          lab_results: [],
          knockout_checks: [],
        },
      }],
      counts: { ...workspace.counts, pending: 0 },
      case_review: {
        ...workspace.case_review,
        open_flags: 0,
        exceptions: [],
      },
    };
    const readiness = {
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
    };
    const history = {
      case: readyWorkspace.case,
      readiness,
      decisions: [],
    };
    let submittedPayload: Record<string, unknown> | null = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/cases") {
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("/underwriting-decisions") && init?.method === "POST") {
        submittedPayload = JSON.parse(String(init.body)) as Record<string, unknown>;
        const decision = {
          id: "final-decision-1",
          decision: "approve",
          approved_sum_assured: "1000000.00",
          applicable_premium: "12000.00",
          decision_rationale: "Reviewed the available evidence.",
          additional_terms: "Standard terms.",
          decline_reason: null,
          postponement_reason: null,
          additional_requirements: null,
          expected_reassessment_date: null,
          referral_reason: null,
          target_authority: null,
          decision_notes: null,
          supporting_document_ids: [],
          authority_reference: "Delegated authority v3",
          guideline_reference: "Product guide v4",
          authority_attested: true,
          information_requests_acknowledged: true,
          underwriter_subject: "reviewer-demo",
          decided_at: "2026-11-28T00:00:00Z",
        };
        return new Response(JSON.stringify({
          ...history,
          case: { ...readyWorkspace.case, workflow_stage: "resolved" },
          decisions: [decision],
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("/underwriting-decisions")) {
        return new Response(JSON.stringify(history), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return workspaceResponse(input, readyWorkspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Underwriting Assessment" }));
    await user.click(screen.getByRole("button", { name: /^Decision$/ }));
    await screen.findByText("No decision recorded");
    expect(screen.queryByRole("radio", { name: "Refer / Escalate" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Product guideline reference")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Delegated authority reference")).not.toBeInTheDocument();
    expect(screen.queryByText("Attach supporting evidence (optional)")).not.toBeInTheDocument();
    const caseContext = screen.getByRole("group", { name: "Auto-filled case details" });
    expect(caseContext).toHaveTextContent("Dummy - Dummy");
    expect(caseContext).toHaveTextContent("reviewer-demo");
    expect(screen.getByRole("radio", { name: "Approve" })).not.toBeChecked();
    await user.click(screen.getByRole("radio", { name: "Approve" }));
    expect(screen.getByLabelText("Approved sum assured")).toHaveValue(null);
    expect(screen.getByLabelText("Applicable premium")).toHaveValue(null);
    await user.type(screen.getByLabelText("Approved sum assured"), "1000000");
    await user.type(screen.getByLabelText("Applicable premium"), "12000");
    const rationaleInput = screen.getByLabelText("Decision rationale");
    expect(rationaleInput).toHaveValue(
      "AI evidence summary (review and tailor to your decision):\nsynthetic-report.pdf: The source report records a relevant medical history. (Source p. 1)",
    );
    await user.clear(rationaleInput);
    await user.type(rationaleInput, "Reviewed the available evidence.");
    await user.click(screen.getByRole("button", { name: "Review and confirm decision" }));

    expect(screen.getByRole("heading", { name: "Confirm final decision" })).toBeInTheDocument();
    expect(screen.getAllByText("Dummy - Dummy")).toHaveLength(2);
    expect(screen.getByText("Reviewed the available evidence.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm and record decision" })).toBeDisabled();
    await user.click(screen.getByLabelText(/I have reviewed this summary and confirm/));
    await user.click(screen.getByRole("button", { name: "Confirm and record decision" }));

    expect(await screen.findByText("Final underwriting decision recorded and added to the case history.")).toBeInTheDocument();
    expect(submittedPayload).toMatchObject({
      decision: "approve",
      approved_sum_assured: "1000000",
      applicable_premium: "12000",
    });
    expect(submittedPayload).not.toHaveProperty("authority_reference");
    expect(submittedPayload).not.toHaveProperty("guideline_reference");
    expect(submittedPayload).not.toHaveProperty("supporting_document_ids");
    await user.click(screen.getByText("Decision history (1)"));
    expect(screen.getByText("Latest")).toBeInTheDocument();
  });

  it("allows reviewing completed decision fields but keeps recording locked when readiness is incomplete", async () => {
    const blockedReadiness = {
      source_documents_total: 1,
      source_documents_complete: true,
      evidence_reviews_pending: 1,
      evidence_review_complete: false,
      pending_critical_flags: 1,
      outstanding_information_requests: null,
      information_requests_tracked: false,
      underwriting_guidelines_available: false,
      authority_available: true,
      mandatory_prerequisites_met: false,
      underwriter_subject: "reviewer-demo",
      demo_case: false,
    };
    const history = { case: workspace.case, readiness: blockedReadiness, decisions: [] };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/v1/cases") {
        return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.endsWith("/underwriting-decisions")) {
        return new Response(JSON.stringify(history), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return workspaceResponse(input, workspace);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Underwriting Assessment" }));
    await user.click(screen.getByRole("button", { name: /^Decision$/ }));
    await screen.findByText("No decision recorded");
    await user.click(screen.getByRole("radio", { name: "Decline" }));
    await user.type(screen.getByLabelText("Reason for decline"), "Decision rationale based on reviewed evidence.");
    const reviewButton = screen.getByRole("button", { name: "Review and confirm decision" });
    expect(reviewButton).toBeEnabled();
    await user.click(reviewButton);

    expect(screen.getByText("Recording is locked until case readiness is complete.")).toBeInTheDocument();
    expect(screen.getByText("Review 1 pending evidence field(s).")).toBeInTheDocument();
    expect(screen.getByText("Resolve 1 critical finding(s).")).toBeInTheDocument();
    const recordButton = screen.getByRole("button", { name: "Confirm and record decision" });
    expect(recordButton).toBeDisabled();
    await user.click(screen.getByLabelText(/I have reviewed this summary and confirm/));
    expect(recordButton).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/underwriting-decisions"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("groups case evidence and explicitly marks backend-reported conflicts", async () => {
    const conflictingWorkspace: Workspace = {
      ...workspace,
      documents: [
        workspace.documents[0],
        { ...workspace.documents[0], id: "doc-2", filename: "second-report.pdf" },
      ],
      fields: [
        workspace.fields[0],
        {
          ...workspace.fields[0],
          id: "field-tobacco-2",
          document_id: "doc-2",
          candidate_value: "No",
          effective_value: "No",
          latest_review: null,
        },
      ],
      case_review: {
        ...workspace.case_review,
        open_flags: 2,
        cross_document_conflicts: 1,
        exceptions: [{
          id: "conflict:lifestyle.tobacco",
          kind: "cross_document_conflict",
          category: "Cross-document conflict",
          title: "Tobacco differs across documents",
          status: "pending",
          severity: "warning",
          field_ids: ["field-tobacco", "field-tobacco-2"],
          document_ids: ["doc-1", "doc-2"],
          message: "The source values differ.",
        }],
      },
    };
    stubWorkspaceFetch(conflictingWorkspace);
    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Case Evidence" }));
    expect(screen.getByText("Conflict · review sources")).toBeInTheDocument();
    expect(screen.getByText("Tobacco differs across documents")).toBeInTheDocument();
    expect(screen.getByText("second-report.pdf · text · pending")).toBeInTheDocument();
    expect(screen.getByText(/does not choose a source of truth/i)).toBeInTheDocument();
  });
});
