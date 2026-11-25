import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { EvidenceField } from "../types";
import { ReviewDialog } from "./ReviewDialog";

const field: EvidenceField = {
  id: "field-1",
  document_id: "doc-1",
  run_id: "run-1",
  field_path: "observations.bmi",
  label: "BMI",
  ui_section: "vitals",
  ui_group: "Body measurements",
  source_literal: "26.1",
  candidate_value: 26.1,
  effective_value: 26.1,
  data_type: "decimal",
  unit: "kg/m²",
  extraction_status: "found",
  confidence: 0.98,
  validations: [],
  citations: [
    {
      document_id: "doc-1",
      document_version: 1,
      page: 1,
      excerpt: "BMI: 26.1 kg/m2",
      bbox: null,
    },
  ],
  review_state: "pending",
  review_version: 3,
  latest_review: null,
};

describe("review dialog", () => {
  it("requires rationale and sends the expected version for a correction", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(
      <ReviewDialog
        field={field}
        busy={false}
        error={null}
        onClose={vi.fn()}
        onSubmit={onSubmit}
        onViewSource={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("radio", { name: /Correct/ }));
    const save = screen.getByRole("button", { name: "Save review" });
    expect(save).toBeDisabled();
    const correction = screen.getByRole("textbox", { name: /Corrected value/ });
    await user.clear(correction);
    await user.type(correction, "26.2");
    await user.type(screen.getByRole("textbox", { name: /Rationale/ }), "Verified source.");
    expect(save).toBeEnabled();
    await user.click(save);

    expect(onSubmit).toHaveBeenCalledWith({
      field_id: "field-1",
      decision: "corrected",
      expected_version: 3,
      corrected_value: "26.2",
      rationale: "Verified source.",
    });
  });
});
