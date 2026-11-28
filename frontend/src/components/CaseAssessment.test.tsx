import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AssessmentResult, CaseAssessmentView } from "../types";
import {
  AssessmentFindings,
  AssessmentKpis,
  ProposedPremiumPrompt,
  TermsComparison,
  useCaseAssessment,
} from "./CaseAssessment";

const citation = { document_id: "doc-m", document_version: 1, page: 1, excerpt: "BMI: 37.2 kg/m2" };

function result(overrides: Partial<AssessmentResult> = {}): AssessmentResult {
  return {
    engine_version: "case-assessment-1.0.0",
    inputs: {
      documents: [],
      processed_documents: 2,
      ai_analyses: 0,
      rule_set: { id: "demo", version: "1.0.0", is_demo: true, source: "demo" },
    },
    proposed_terms: {
      status: "captured",
      source: "case_product_selection",
      insurer: "Insurer One",
      product_name: "Term",
      currency: "INR",
      sum_assured: 10000000,
      premium: 14160,
      premium_status: "indicative",
      premium_frequency: "annual",
      policy_term: 20,
      premium_payment_term: 20,
    },
    applicant: [],
    medical_findings: [],
    financial: {
      evidence: [],
      exposure: {
        currency: "INR",
        proposed_sum_assured: 10000000,
        existing_cover: { status: "declared", amount: 2500000, reason: null, citations: [] },
        total_exposure: 12500000,
        annual_income: { status: "stated", amount: 400000, citations: [] },
        cover_to_income_multiple: 31.25,
        multiple_includes_existing_cover: true,
      },
    },
    rule_results: [
      {
        rule_id: "bmi_above_35",
        title: "BMI above 35",
        category: "medical",
        outcome: "refer",
        points: 25,
        rationale: "Demo rule",
        status: "triggered",
        reason: "Demo rule",
        evidence: [{ label: "BMI", value: 37.2, filename: "medical.pdf", citations: [citation] }],
      },
      {
        rule_id: "identity_mismatch",
        title: "Identity mismatch",
        category: "identity",
        outcome: "refer",
        points: 15,
        rationale: "x",
        status: "not_evaluable",
        reason: "No identity documents.",
        evidence: [],
      },
    ],
    hilt: { pending: 1, open_flags: 1 },
    issues: [{ category: "missing_evidence", severity: "info", message: "No Aadhaar or PAN document has been uploaded." }],
    recommendation: {
      status: "available",
      code: "refer_to_underwriter",
      label: "Refer to underwriter",
      reason: "BMI above 35",
      disclaimer: "Decision support only. It never approves or declines.",
      automatic_decision: false,
      pending_hilt_exceptions: 1,
      triggered_rule_ids: ["bmi_above_35"],
      rule_set: { id: "demo", version: "1.0.0", is_demo: true },
    },
    risk_score: {
      status: "assessed",
      score: 25,
      scale_min: 0,
      scale_max: 100,
      band: "Moderate",
      interpretation: "Some adverse demo rules triggered.",
      model: { id: "demo", version: "1.0.0", approved: false, is_demo: true },
    },
    recommended_terms: { status: "not_available", reason: "None configured." },
    revised_premium: { status: "not_available", amount: null, reason: "None configured." },
    disclaimer: "Decision support only.",
    ...overrides,
  };
}

function view(overrides: Partial<CaseAssessmentView> = {}): CaseAssessmentView {
  return {
    case_id: "UW-1",
    rules_configured: true,
    stale: false,
    latest: { version: 3, created_at: "2026-11-28T10:00:00Z", trigger: "document_processed", created_by: "system:worker", engine_version: "x", result: result() },
    versions: [
      { version: 3, created_at: "2026-11-28T10:00:00Z", trigger: "document_processed", created_by: "system:worker", recommendation: "refer_to_underwriter", risk_score: 25 },
      { version: 1, created_at: "2026-11-28T09:00:00Z", trigger: "case_created", created_by: "u", recommendation: "insufficient_evidence", risk_score: null },
    ],
    final_terms: { status: "not_recorded", reason: "No decision." },
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("case assessment", () => {
  it("fills the four overview cards from the assessment", () => {
    render(<AssessmentKpis view={view()} loading={false} error={null} />);
    expect(screen.getByText("Refer to underwriter")).toBeInTheDocument();
    expect(screen.getByText("₹1,25,00,000")).toBeInTheDocument();
    expect(screen.getByText(/Proposed ₹1,00,00,000 \+ existing ₹25,00,000/)).toBeInTheDocument();
    expect(screen.getByText("₹14,160")).toBeInTheDocument();
    expect(screen.getByText(/Proposed \(indicative\) per year\. Revised premium: Not Available/)).toBeInTheDocument();
    expect(screen.getByText("25 / 100")).toBeInTheDocument();
    expect(screen.getByText(/Moderate: .* Scale 0–100, higher is riskier/)).toBeInTheDocument();
    expect(screen.getByText("Not an approved model")).toBeInTheDocument();
    expect(screen.getByText("Demo rules")).toBeInTheDocument();
  });

  it("shows Not Available and Not Assessed instead of inventing values", () => {
    const empty = result({
      proposed_terms: { status: "not_available", source: "case_record" },
      financial: { evidence: [], exposure: { ...result().financial.exposure, proposed_sum_assured: null, existing_cover: { status: "not_available", amount: null, reason: "none", citations: [] }, total_exposure: null } },
      recommendation: { ...result().recommendation, status: "not_available", code: null, label: "Not available", reason: "No underwriting rule set is configured.", rule_set: undefined },
      risk_score: { status: "not_assessed", score: null, reason: "No risk assessment model is configured." },
    });
    render(<AssessmentKpis view={view({ latest: { ...view().latest!, result: empty } })} loading={false} error={null} />);
    expect(screen.getAllByText("Not Available")).toHaveLength(3);
    expect(screen.getByText("Not Assessed")).toBeInTheDocument();
    expect(screen.getByText("No risk assessment model is configured.")).toBeInTheDocument();
  });

  it("keeps proposed, assessed and final terms in separate columns", () => {
    render(
      <TermsComparison
        view={view({ final_terms: { status: "recorded", decision: "approve", approved_sum_assured: 9000000, applicable_premium: 15000 } })}
      />,
    );
    const premiumRow = screen.getByText("Premium").closest("tr") as HTMLElement;
    expect(within(premiumRow).getByText(/₹14,160 per year \(indicative\)/)).toBeInTheDocument();
    expect(within(premiumRow).getByText("Not Available")).toBeInTheDocument();
    expect(within(premiumRow).getByText("₹15,000")).toBeInTheDocument();
    const saRow = screen.getByText("Sum assured").closest("tr") as HTMLElement;
    expect(within(saRow).getByText("₹1,00,00,000")).toBeInTheDocument();
    expect(within(saRow).getByText("₹90,00,000")).toBeInTheDocument();
  });

  it("lists triggered rules with evidence and opens citations", async () => {
    const onCitation = vi.fn();
    render(
      <AssessmentFindings view={view({ stale: true })} loading={false} error={null} refreshing={false} canRefresh onRefresh={vi.fn()} onCitation={onCitation} />,
    );
    const section = screen.getByRole("region", { name: "AI underwriting assessment" });
    const rules = section.querySelector(".assessment-rule-list") as HTMLElement;
    expect(within(rules).getByText("BMI above 35")).toBeInTheDocument();
    expect(within(rules).getByText("Refer")).toBeInTheDocument();
    expect(within(rules).getByText("37.2")).toBeInTheDocument();
    expect(within(section).getByText(/never approves or declines/)).toBeInTheDocument();
    expect(within(section).getByText(/evidence changed after this version/)).toBeInTheDocument();
    expect(within(section).getByText("No Aadhaar or PAN document has been uploaded.")).toBeInTheDocument();
    expect(within(section).getByText("Assessment history (2 versions)")).toBeInTheDocument();
    await userEvent.click(within(section).getByRole("button", { name: "Page 1 source" }));
    expect(onCitation).toHaveBeenCalledWith(expect.objectContaining({ page: 1, excerpt: "BMI: 37.2 kg/m2" }));
  });

  it("asks only for missing applicant details and calculates the premium", async () => {
    const noPremium = view({
      latest: {
        ...view().latest!,
        result: result({
          proposed_terms: {
            ...result().proposed_terms,
            product_id: "demo-health-secure",
            premium: null,
            premium_status: "not_available",
            rating_inputs: { age: null, gender: null, smoker: null },
          },
        }),
      },
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const body = url.endsWith("/requote")
        ? { ...noPremium.latest }
        : { product_id: "demo-health-secure", pricing_available: true, rating_factors: ["age"] };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const onUpdated = vi.fn();
    render(<ProposedPremiumPrompt caseId="UW-1" view={noPremium} onUpdated={onUpdated} />);
    const button = await screen.findByRole("button", { name: "Calculate premium" });
    expect(button).toBeDisabled();
    expect(screen.queryByLabelText("Applicant gender")).not.toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Applicant age"), "30");
    await userEvent.click(button);
    await waitFor(() => expect(onUpdated).toHaveBeenCalled());
    const post = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/product/requote"));
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ age: 30 });
  });

  it("shows no prompt when a proposed premium exists", () => {
    const { container } = render(<ProposedPremiumPrompt caseId="UW-1" view={view()} onUpdated={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("loads the assessment and refreshes it on demand", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify(view({ latest: { ...view().latest!, version: init?.method === "POST" ? 4 : 3 } })), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    function Harness() {
      const state = useCaseAssessment("UW-1", "k");
      return (
        <AssessmentFindings
          view={state.view}
          loading={state.loading}
          error={state.error}
          refreshing={state.refreshing}
          canRefresh
          onRefresh={() => void state.refresh()}
          onCitation={vi.fn()}
        />
      );
    }
    render(<Harness />);
    expect(await screen.findByText(/Version 3/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Refresh assessment" }));
    await waitFor(() => expect(screen.getByText(/Version 4/)).toBeInTheDocument());
    expect(String(fetchMock.mock.calls[1][0])).toContain("/api/v1/cases/UW-1/assessment/refresh");
  });
});
