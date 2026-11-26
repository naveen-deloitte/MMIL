import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { AiAnalysis, EvidenceField } from "../types";
import {
  EvidenceRow,
  KnockoutChecksView,
  LabReportsView,
  SummaryView,
  VitalsView,
} from "./EvidenceViews";

const field: EvidenceField = {
  id: "field-1",
  document_id: "doc-1",
  run_id: "run-1",
  field_path: "labs.hba1c",
  label: "HbA1c",
  ui_section: "labs",
  ui_group: "Blood sugar & diabetes",
  source_literal: "5.4",
  candidate_value: 5.4,
  effective_value: 5.4,
  data_type: "decimal",
  unit: "%",
  extraction_status: "found",
  confidence: 0.98,
  validations: [],
  citations: [{ document_id: "doc-1", document_version: 1, page: 2, excerpt: "HbA1c: 5.4 %", bbox: null }],
  review_state: "pending",
  review_version: 0,
  latest_review: null,
};

describe("medical evidence views", () => {
  it("shows value, confidence, review state, and citation action", () => {
    const onCitation = vi.fn();
    const onReview = vi.fn();
    render(<EvidenceRow field={field} onCitation={onCitation} onReview={onReview} />);

    expect(screen.getByText("HbA1c")).toBeInTheDocument();
    expect(screen.getByText("5.4", { selector: ".field-value" })).toBeInTheDocument();
    expect(screen.getByText("98% confidence")).toBeInTheDocument();
    expect(screen.getByText("HbA1c: 5.4 %")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review" }));
    expect(onReview).toHaveBeenCalledWith(field);
    fireEvent.click(screen.getByRole("button", { name: "Page 2 source" }));
    expect(onCitation).toHaveBeenCalledWith(field, 0);
  });

  it("shows report-grounded summary and follow-up with source links", () => {
    const analysis: AiAnalysis = {
      summary: {
        text: "The report records a normal ECG.",
        citations: [{ ...field.citations[0], excerpt: "Resting ECG: Normal sinus rhythm" }],
      },
      key_medical_findings: [{
        text: "The ECG records normal sinus rhythm.",
        citations: [{ ...field.citations[0], excerpt: "Resting ECG: Normal sinus rhythm" }],
      }],
      recommendations: [{
        text: "Discuss the report findings with a qualified clinician.",
        citations: [{ ...field.citations[0], excerpt: "Resting ECG: Normal sinus rhythm" }],
      }],
      vitals_summary: null,
      major_vital_factors: [],
      lab_results: [],
      knockout_checks: [],
    };
    const onAiCitation = vi.fn();
    render(
      <SummaryView
        fields={[]}
        analysis={analysis}
        onAiCitation={onAiCitation}
        canGenerateSummary={false}
        onGenerateSummary={vi.fn()}
        onCitation={vi.fn()}
        onReview={vi.fn()}
      />,
    );

    expect(screen.getByRole("tabpanel", { name: "AI Summary" })).toBeInTheDocument();
    expect(screen.getByText("The report records a normal ECG.")).toBeInTheDocument();
    expect(screen.getByText("The ECG records normal sinus rhythm.")).toBeInTheDocument();
    expect(screen.getByText("Recommended follow-up")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Page 2 source" })[0]);
    expect(onAiCitation).toHaveBeenCalledWith(analysis.summary?.citations[0]);
  });

  it("offers summary generation when an AI analysis has no summary", () => {
    const onGenerateSummary = vi.fn();
    render(
      <SummaryView
        fields={[]}
        analysis={null}
        onAiCitation={vi.fn()}
        canGenerateSummary
        onGenerateSummary={onGenerateSummary}
        onCitation={vi.fn()}
        onReview={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Generate AI summary" }));
    expect(onGenerateSummary).toHaveBeenCalledOnce();
  });

  it("explains local extraction has no AI summary and offers a rerun", () => {
    const onReprocessLocal = vi.fn();
    render(
      <SummaryView
        fields={[]}
        analysis={null}
        onAiCitation={vi.fn()}
        canGenerateSummary={false}
        canReprocessLocal
        isLocalRun
        onGenerateSummary={vi.fn()}
        onReprocessLocal={onReprocessLocal}
        onCitation={vi.fn()}
        onReview={vi.fn()}
      />,
    );

    expect(screen.getByText(/deterministic local extraction/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Re-run local extraction" }));
    expect(onReprocessLocal).toHaveBeenCalledOnce();
  });

  it("shows AI-identified major report factors under Vitals", () => {
    const analysis: AiAnalysis = {
      summary: null,
      key_medical_findings: [],
      recommendations: [],
      vitals_summary: {
        text: "The report lists blood pressure measurements.",
        citations: [field.citations[0]],
      },
      major_vital_factors: [{
        text: "HbA1c is recorded as 5.4%.",
        citations: [field.citations[0]],
      }],
      lab_results: [],
      knockout_checks: [],
    };
    render(
      <VitalsView
        fields={[]}
        analysis={analysis}
        onAiCitation={vi.fn()}
        onCitation={vi.fn()}
        onReview={vi.fn()}
      />,
    );

    expect(screen.getByRole("tabpanel", { name: "Vitals" })).toBeInTheDocument();
    expect(screen.getByText("AI report observations")).toBeInTheDocument();
    expect(screen.getByText("HbA1c is recorded as 5.4%.")).toBeInTheDocument();
    expect(screen.getAllByText("Not detected in this run")).toHaveLength(4);
    expect(screen.getByText(/Typical adult reference: 12–18 breaths\/min/)).toBeInTheDocument();
  });

  it("shows reported primary vital values with citations and adult reference context", () => {
    const makeVitalField = (overrides: Partial<EvidenceField>): EvidenceField => ({
      ...field,
      citations: [],
      ui_section: "vitals",
      ui_group: "Vitals",
      ...overrides,
    });
    const bloodPressure = makeVitalField({
      id: "field-bp",
      field_path: "observations.blood_pressure",
      label: "Blood pressure",
      candidate_value: { systolic: 120, diastolic: 80 },
      effective_value: { systolic: 120, diastolic: 80 },
      unit: "mmHg",
      citations: [{ ...field.citations[0], excerpt: "Blood Pressure: 120/80 mmHg" }],
    });
    const fields = [
      bloodPressure,
      makeVitalField({
        id: "field-pulse",
        field_path: "observations.pulse_bpm",
        label: "Pulse",
        candidate_value: 72,
        effective_value: 72,
        unit: "bpm",
      }),
      makeVitalField({
        id: "field-rr",
        field_path: "observations.respiratory_rate_bpm",
        label: "Respiratory rate",
        candidate_value: 16,
        effective_value: 16,
        unit: "breaths/min",
      }),
      makeVitalField({
        id: "field-temp",
        field_path: "observations.body_temperature",
        label: "Body temperature",
        candidate_value: "98.6°F",
        effective_value: "98.6°F",
        unit: null,
      }),
    ];
    const onCitation = vi.fn();
    render(
      <VitalsView
        fields={fields}
        analysis={null}
        onAiCitation={vi.fn()}
        onCitation={onCitation}
        onReview={vi.fn()}
      />,
    );

    expect(screen.getByText("120/80 mmHg")).toBeInTheDocument();
    expect(screen.getByText("72 bpm")).toBeInTheDocument();
    expect(screen.getByText("16 breaths/min")).toBeInTheDocument();
    expect(screen.getByText("98.6°F")).toBeInTheDocument();
    expect(screen.getByText(/Typical adult reference: 97\.7–99\.1°F/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Page 2 source" }));
    expect(onCitation).toHaveBeenCalledWith(bloodPressure, 0);
  });

  it("shows lab values and screening factors with source citations and a human-review disclaimer", () => {
    const onCitation = vi.fn();
    const lab = {
      category: "hematology",
      name: "Hemoglobin",
      value: "13.2",
      unit: "g/dL",
      reference_range: "12.0-16.0",
      reported_flag: null,
      confidence: 0.94,
      citations: [field.citations[0]],
    };
    const check = {
      factor: "HIV",
      value: "Non-reactive",
      confidence: 0.96,
      citations: [field.citations[0]],
    };
    const { rerender } = render(<LabReportsView results={[lab]} onCitation={onCitation} />);

    expect(screen.getByRole("tabpanel", { name: "Lab Reports" })).toBeInTheDocument();
    expect(screen.getByText("13.2 g/dL")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Page 2 source" }));
    expect(onCitation).toHaveBeenCalledWith(field.citations[0]);

    rerender(<KnockoutChecksView checks={[check]} onCitation={onCitation} />);
    expect(screen.getByRole("tabpanel", { name: "Knockout Checks" })).toBeInTheDocument();
    expect(screen.getByText("Reported value:")).toHaveTextContent("Non-reactive");
    expect(screen.getByText(/No decline, loading, eligibility, or coverage action/)).toBeInTheDocument();
  });
});
