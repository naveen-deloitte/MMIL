"""Generate the synthetic PDF used by local demos and automated tests."""

from __future__ import annotations

from pathlib import Path

import pymupdf


LINES_PAGE_1 = [
    "SYNTHETIC DEMO - NOT A REAL PERSON OR MEDICAL RECORD",
    "MEDICAL EXAMINATION REPORT",
    "Applicant reference: DEMO-AARAV-001",
    "Report Date: 2026-08-14",
    "Height: 175 cm",
    "Weight: 80 kg",
    "BMI: 26.1 kg/m2",
    "Blood Pressure: 128/82 mmHg",
    "Pulse: 72 bpm",
    "Resting ECG: Normal sinus rhythm",
    "TMT: Not required",
    "Tobacco: Yes, 5 cigarettes/day",
    "Alcohol: Occasional",
    "Conditions: None disclosed",
    "Family History: Father hypertension",
]

LINES_PAGE_2 = [
    "SYNTHETIC DEMO - LABORATORY RESULTS",
    "Fasting Blood Sugar: 96 mg/dL",
    "HbA1c: 5.4 %",
    "Total Cholesterol: 198 mg/dL",
    "LDL Cholesterol: 118 mg/dL",
    "HDL Cholesterol: 52 mg/dL",
    "Triglycerides: 142 mg/dL",
    "SGOT (AST): 28 U/L",
    "SGPT (ALT): 32 U/L",
    "Serum Creatinine: 0.9 mg/dL",
    "eGFR: 98 mL/min/1.73m2",
    "HIV (ELISA): Negative",
    "HBsAg: Negative",
    "End of synthetic report",
]


def generate(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    for lines in (LINES_PAGE_1, LINES_PAGE_2):
        page = document.new_page(width=595, height=842)
        y = 72
        for index, line in enumerate(lines):
            size = 13 if index < 2 else 11
            font = "hebo" if index < 2 else "helv"
            page.insert_text((56, y), line, fontsize=size, fontname=font, color=(0.1, 0.1, 0.1))
            y += 32 if index < 2 else 26
        page.insert_text(
            (56, 805),
            f"Synthetic page {page.number + 1}",
            fontsize=9,
            color=(0.4, 0.4, 0.4),
        )
    metadata = {
        "title": "Synthetic medical report for IDP testing",
        "author": "Generated test fixture",
        "subject": "Contains no real personal or health information",
    }
    document.set_metadata(metadata)
    document.save(output, garbage=4, deflate=True)
    document.close()
    return output


if __name__ == "__main__":
    target = Path(__file__).with_name("synthetic-medical-report.pdf")
    print(generate(target))
