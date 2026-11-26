from __future__ import annotations

from pathlib import Path

import pytest

from idp.document_types import DocumentTypeRegistry
from idp.errors import ProcessingError
from idp.extraction.engine import SchemaExtractor, extract_additional_facts
from idp.extraction.text import PageText
from idp.services.processing import merge_provider_fields

ROOT = Path(__file__).resolve().parents[2]


def test_provider_can_fill_only_an_allowed_missing_field_with_exact_citation() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    pages = [
        PageText(
            page_number=1,
            text="BMI: 26.1 kg/m2\nSmoking status reported as No",
            width=100,
            height=100,
        )
    ]
    candidates = SchemaExtractor(registry.definition).extract(
        document_id="doc-1", document_version=1, pages=pages
    )
    tobacco = next(item for item in candidates if item.field_path == "lifestyle.tobacco")
    assert tobacco.normalized_value is None

    merged = merge_provider_fields(
        candidates=candidates,
        provider_fields=[
            {
                "field_path": "lifestyle.tobacco",
                "source_literal": "No",
                "page": 1,
                "excerpt": "Smoking status reported as No",
                "confidence": 0.8,
            }
        ],
        pages=pages,
        document_id="doc-1",
        document_version=1,
        registry=registry,
    )
    result = next(item for item in merged if item.field_path == "lifestyle.tobacco")
    assert result.normalized_value == "No"
    assert result.citations[0].excerpt == "Smoking status reported as No"


def test_primary_vitals_extract_explicit_blood_pressure_pulse_rr_and_temperature() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    page = PageText(
        page_number=1,
        text=(
            "Blood Pressure: 128/82 mmHg\n"
            "Pulse: 72 bpm\n"
            "Respiratory Rate: 16 breaths/min\n"
            "Temperature: 98.6°F"
        ),
        width=100,
        height=100,
    )

    candidates = SchemaExtractor(registry.definition).extract(
        document_id="doc-1",
        document_version=1,
        pages=[page],
    )

    by_path = {candidate.field_path: candidate for candidate in candidates}
    expected = {
        "observations.blood_pressure": ("128/82", "Blood Pressure: 128/82 mmHg"),
        "observations.pulse_bpm": ("72", "Pulse: 72 bpm"),
        "observations.respiratory_rate_bpm": (
            "16",
            "Respiratory Rate: 16 breaths/min",
        ),
        "observations.body_temperature": ("98.6°F", "Temperature: 98.6°F"),
    }
    for path, (literal, excerpt) in expected.items():
        assert by_path[path].source_literal == literal
        assert by_path[path].citations[0].excerpt == excerpt


def test_blood_pressure_extracts_when_value_is_on_line_after_label() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    page = PageText(
        page_number=1,
        text="Blood Pressure\n: 128/82 mmHg",
        width=100,
        height=100,
    )

    candidates = SchemaExtractor(registry.definition).extract(
        document_id="doc-1",
        document_version=1,
        pages=[page],
    )

    blood_pressure = next(
        item for item in candidates if item.field_path == "observations.blood_pressure"
    )
    assert blood_pressure.source_literal == "128/82"
    assert blood_pressure.citations[0].excerpt == "Blood Pressure\n: 128/82 mmHg"


def test_medical_schema_extracts_wrapped_bmi_and_unpunctuated_lab_rows() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    page = PageText(
        page_number=1,
        text=(
            "BMI\n: 26.1 kg/m2\n"
            "Fasting Blood Sugar 96 mg/dL - Reference range 70-110\n"
            "HbA1c 5.4 % Reference range 4.0-5.6"
        ),
        width=100,
        height=100,
    )

    candidates = SchemaExtractor(registry.definition).extract(
        document_id="doc-1",
        document_version=1,
        pages=[page],
    )

    by_path = {candidate.field_path: candidate for candidate in candidates}
    expected = {
        "observations.bmi": (26.1, "BMI\n: 26.1 kg/m2"),
        "labs.fasting_glucose": (96, "Fasting Blood Sugar 96 mg/dL"),
        "labs.hba1c": (5.4, "HbA1c 5.4 %"),
    }
    for path, (value, excerpt) in expected.items():
        assert by_path[path].normalized_value == value
        assert by_path[path].citations[0].excerpt == excerpt


def test_provider_value_overrides_regex_value_and_keeps_model_confidence_and_citation() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    pages = [
        PageText(
            page_number=1,
            text="BMI: 26.1 kg/m2\nUpdated BMI: 26.2 kg/m2",
            width=100,
            height=100,
        )
    ]
    candidates = SchemaExtractor(registry.definition).extract(
        document_id="doc-1", document_version=1, pages=pages
    )

    merged = merge_provider_fields(
        candidates=candidates,
        provider_fields=[
            {
                "field_path": "observations.bmi",
                "source_literal": "26.2",
                "page": 1,
                "excerpt": "Updated BMI: 26.2 kg/m2",
                "confidence": 0.87,
            }
        ],
        pages=pages,
        document_id="doc-1",
        document_version=1,
        registry=registry,
    )
    result = next(item for item in merged if item.field_path == "observations.bmi")

    assert result.normalized_value == 26.2
    assert result.confidence == 0.87
    assert result.citations[0].excerpt == "Updated BMI: 26.2 kg/m2"


def test_ai_extraction_starts_with_no_rule_based_values() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    candidates = SchemaExtractor(registry.definition).empty_candidates()

    bmi = next(item for item in candidates if item.field_path == "observations.bmi")

    assert bmi.normalized_value is None
    assert bmi.status == "not_found"
    assert bmi.confidence is None
    assert bmi.citations == []


def test_unsupported_additional_fact_type_is_preserved_as_text_with_warning() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    pages = [PageText(page_number=1, text="Reference range: 4-10", width=100, height=100)]

    facts = extract_additional_facts(
        raw_facts=[
            {
                "name": "Reference range",
                "category": "laboratory",
                "data_type": "range",
                "source_literal": "4-10",
                "page": 1,
                "excerpt": "Reference range: 4-10",
                "confidence": 0.9,
            }
        ],
        definition=registry.definition,
        primary_fields=SchemaExtractor(registry.definition).empty_candidates(),
        pages=pages,
        document_id="doc-1",
        document_version=1,
    )

    assert facts[0].normalized_value == "4-10"
    assert facts[0].data_type == "text"
    assert facts[0].validations == [
        {"code": "unsupported_type_preserved_as_text", "severity": "warning"}
    ]


def test_provider_field_with_unmatched_excerpt_is_rejected() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    pages = [PageText(page_number=1, text="No tobacco line", width=100, height=100)]
    candidates = SchemaExtractor(registry.definition).extract(
        document_id="doc-1", document_version=1, pages=pages
    )
    with pytest.raises(ProcessingError) as error:
        merge_provider_fields(
            candidates=candidates,
            provider_fields=[
                {
                    "field_path": "lifestyle.tobacco",
                    "source_literal": "No",
                    "page": 1,
                    "excerpt": "Tobacco: No",
                    "confidence": 0.8,
                }
            ],
            pages=pages,
            document_id="doc-1",
            document_version=1,
            registry=registry,
        )
    assert error.value.code == "provider_citation_invalid"
