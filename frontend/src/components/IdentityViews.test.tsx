import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EvidenceField, IdentitySummary } from "../types";
import { IdentityVerificationView } from "./IdentityViews";

function field(overrides: Partial<EvidenceField>): EvidenceField {
  return {
    id: "f",
    document_id: "doc-a",
    run_id: "run-a",
    field_path: "identity.full_name",
    label: "Full name",
    ui_section: "identity",
    ui_group: "Aadhaar details",
    source_literal: "Rahul Sharma",
    candidate_value: "Rahul Sharma",
    effective_value: "Rahul Sharma",
    data_type: "text",
    unit: null,
    extraction_status: "found",
    confidence: 0.78,
    validations: [],
    citations: [{ document_id: "doc-a", document_version: 1, page: 1, excerpt: "Rahul Sharma", bbox: null }],
    review_state: "pending",
    review_version: 0,
    latest_review: null,
    ...overrides,
  };
}

function summary(overrides: Partial<IdentitySummary> = {}): IdentitySummary {
  return {
    case_id: "UW-1",
    fingerprint: "fp",
    kyc_present: true,
    documents: [
      {
        subject: "aadhaar",
        state: "extracted",
        document_id: "doc-a",
        filename: "aadhaar.pdf",
        document_status: "review_required",
        failure_code: null,
        action_required: null,
        extraction_confidence: 0.78,
        fields: [
          field({ id: "name" }),
          field({
            id: "num",
            field_path: "identity.aadhaar_number",
            label: "Aadhaar number",
            candidate_value: "XXXX XXXX 9012",
            effective_value: "XXXX XXXX 9012",
            source_literal: "XXXX XXXX 9012",
            review_state: "accepted",
          }),
        ],
      },
      {
        subject: "pan",
        state: "not_uploaded",
        document_id: null,
        filename: null,
        document_status: null,
        failure_code: null,
        action_required: null,
        extraction_confidence: null,
        fields: [],
      },
    ],
    stages: {
      document_uploaded: { aadhaar: "uploaded", pan: "not_uploaded" },
      information_extracted: { aadhaar: "extracted", pan: "not_uploaded" },
      format_validated: { aadhaar: "passed", pan: "not_available" },
      kyc_matched: "mismatch",
      authenticity_verified: { aadhaar: "not_configured", pan: "not_verified" },
      human_review_completed: "not_started",
    },
    match_status: "mismatch",
    matches: [
      {
        field: "full_name",
        label: "Full name",
        kyc_value: "Amit Verma",
        aadhaar_value: "Rahul Sharma",
        pan_value: null,
        match_status: "mismatch",
        confidence: 0,
        explanation: "The names contain different words.",
        pairs: [],
        not_applicable_sources: [],
        missing_sources: ["pan"],
      },
      {
        field: "gender",
        label: "Gender",
        kyc_value: "Male",
        aadhaar_value: "Male",
        pan_value: null,
        match_status: "match",
        confidence: 1,
        explanation: "Identical.",
        pairs: [],
        not_applicable_sources: ["pan"],
        missing_sources: [],
      },
    ],
    findings: [],
    verification: [
      { subject: "aadhaar", status: "not_configured", configured: false, provider: "not_configured", reason_code: "aadhaar_verification_not_configured", verified_at: null, consent_given: false },
      { subject: "pan", status: "not_verified", configured: false, provider: null, reason_code: null, verified_at: null, consent_given: null },
    ],
    review: { status: "not_started", decision: null, rationale: null, reviewer_subject: null, reviewed_at: null, resolved_fields: [] },
    issues: [
      { code: "cross_document_mismatch", category: "data_mismatch", severity: "error", message: "Full name: The names contain different words.", subject: null, field: "full_name" },
    ],
    ...overrides,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function renderView(props: Partial<Parameters<typeof IdentityVerificationView>[0]> = {}) {
  const handlers = {
    onCitation: vi.fn(),
    onReview: vi.fn(),
    onOpenDocument: vi.fn(),
    onChanged: vi.fn(),
  };
  render(<IdentityVerificationView caseId="UW-1" refreshKey="1" {...handlers} {...props} />);
  return handlers;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("identity verification view", () => {
  it("shows a loading state, then extraction results with masked identifiers", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(summary())));
    renderView();
    expect(screen.getByRole("status")).toHaveTextContent("Loading identity verification");
    expect(await screen.findByText("XXXX XXXX 9012")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "PAN details" })).toHaveTextContent("Not uploaded.");
  });

  it("never shows Verified when only extraction succeeded", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(summary())));
    renderView();
    await screen.findByText("XXXX XXXX 9012");
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not Verified · provider not configured").length).toBeGreaterThan(0);
  });

  it("shows Verified only for an official verification result", async () => {
    const verified = summary({
      verification: [
        { subject: "aadhaar", status: "not_configured", configured: false, provider: null, reason_code: null, verified_at: null, consent_given: null },
        { subject: "pan", status: "verified", configured: true, provider: "http", reason_code: null, verified_at: "2026-11-28T00:00:00Z", consent_given: true },
      ],
    });
    vi.stubGlobal("fetch", vi.fn(async () => json(verified)));
    renderView();
    expect((await screen.findAllByText("Verified")).length).toBeGreaterThan(0);
  });

  it("highlights mismatches with both values and opens the original document", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(summary())));
    const handlers = renderView();
    const table = await screen.findByRole("region", { name: "Cross-document comparison" });
    const row = within(table).getByText("Amit Verma").closest("tr") as HTMLElement;
    expect(row).toHaveClass("mismatch-row");
    expect(within(row).getByText("Rahul Sharma")).toBeInTheDocument();
    expect(within(row).getByText("Mismatch")).toBeInTheDocument();
    expect(within(row).getByText("The names contain different words.")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Open Aadhaar" }));
    expect(handlers.onOpenDocument).toHaveBeenCalledWith("doc-a");
    const gender = within(table).getByText("Gender").closest("tr") as HTMLElement;
    expect(within(gender).getByText("N/A")).toBeInTheDocument();
  });

  it("opens the existing field review for accept, correct or reject", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(summary())));
    const handlers = renderView();
    const card = await screen.findByRole("region", { name: "Aadhaar details" });
    await userEvent.click(within(card).getAllByRole("button", { name: "Review" })[0]);
    expect(handlers.onReview).toHaveBeenCalledWith(expect.objectContaining({ id: "name" }));
    await userEvent.click(within(card).getAllByRole("button", { name: "Page 1 source" })[0]);
    expect(handlers.onCitation).toHaveBeenCalled();
  });

  it("shows the actionable OCR error for a failed scan", async () => {
    const failed = summary();
    failed.documents[0] = {
      ...failed.documents[0],
      state: "failed",
      failure_code: "ocr_unavailable",
      action_required: "No OCR provider is configured. Set IDP_OCR_PROVIDER.",
      fields: [],
    };
    vi.stubGlobal("fetch", vi.fn(async () => json(failed)));
    renderView();
    const alert = await screen.findByText(/Processing failed \(ocr_unavailable\)/);
    expect(alert.closest("[role=alert]")).toHaveTextContent("IDP_OCR_PROVIDER");
  });

  it("shows an empty state when no identity documents are uploaded", async () => {
    const empty = summary({ matches: [], issues: [] });
    empty.documents = empty.documents.map((doc) => ({ ...doc, state: "not_uploaded", document_id: null, fields: [] }));
    vi.stubGlobal("fetch", vi.fn(async () => json(empty)));
    renderView();
    expect(await screen.findByText("No Aadhaar or PAN document uploaded")).toBeInTheDocument();
  });

  it("shows an error state with retry", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json({ title: "Error", status: 500, detail: "Server unavailable.", code: "internal_error" }, 500))
      .mockResolvedValueOnce(json(summary()));
    vi.stubGlobal("fetch", fetchMock);
    renderView();
    expect(await screen.findByText("Server unavailable.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("XXXX XXXX 9012")).toBeInTheDocument();
  });

  it("submits an identity review with resolved mismatches and rationale", async () => {
    const reviewed = summary({
      review: { status: "completed", decision: "confirmed", rationale: "ok", reviewer_subject: "r", reviewed_at: "2026-11-28T00:00:00Z", resolved_fields: ["full_name"] },
    });
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      json(init?.method === "POST" ? reviewed : summary()),
    );
    vi.stubGlobal("fetch", fetchMock);
    const handlers = renderView();
    await screen.findByText("XXXX XXXX 9012");
    const section = screen.getByRole("region", { name: "Identity review" });
    await userEvent.click(within(section).getByRole("checkbox", { name: "Full name" }));
    await userEvent.type(within(section).getByLabelText("Identity review rationale"), "Checked originals");
    await userEvent.click(within(section).getByRole("button", { name: "Record identity review" }));
    await waitFor(() => expect(handlers.onChanged).toHaveBeenCalled());
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(String(post?.[0])).toContain("/identity/review");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      decision: "confirmed",
      rationale: "Checked originals",
      resolved_fields: ["full_name"],
    });
  });

  it("sends consent with the verification request", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      json(init?.method === "POST" ? { reused_existing: [], summary: summary() } : summary()),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderView();
    await screen.findByText("XXXX XXXX 9012");
    await userEvent.click(screen.getByRole("checkbox", { name: /applicant has given consent/ }));
    await userEvent.click(screen.getByRole("button", { name: "Run verification check" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(true));
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body)).consent.given).toBe(true);
  });
});
