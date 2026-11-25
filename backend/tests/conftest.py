from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from idp.api.app import create_app
from idp.config import Settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        auth_mode="demo",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        object_root=tmp_path / "objects",
        document_type_path=ROOT / "config" / "document-types" / "medical-report.v1.json",
        extraction_provider="deterministic-local",
        allowed_providers="deterministic-local",
        ocr_provider="none",
        seed_demo_case=True,
        job_max_attempts=1,
        cors_origins="",
    )


@pytest.fixture
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def synthetic_pdf() -> bytes:
    return make_medical_pdf()


def make_medical_pdf(*, bmi: str = "26.1", note: str = "") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    lines = [
        "SYNTHETIC TEST MEDICAL EXAMINATION REPORT",
        "Report Date: 2026-08-14",
        "Height: 175 cm",
        "Weight: 80 kg",
        f"BMI: {bmi} kg/m2",
        "Blood Pressure: 128/82 mmHg",
        "Pulse: 72 bpm",
        "Resting ECG: Normal sinus rhythm",
        "TMT: Not required",
        "Tobacco: Yes, 5 cigarettes/day",
        "Alcohol: Occasional",
        "Conditions: None disclosed",
        "Family History: Father hypertension",
        note,
    ]
    y = 60
    for line in lines:
        if line:
            page.insert_text((50, y), line, fontsize=11)
            y += 24
    page = document.new_page()
    lines = [
        "SYNTHETIC TEST LABORATORY RESULTS",
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
    ]
    y = 60
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 24
    content = document.tobytes(garbage=4, deflate=True)
    document.close()
    return content
