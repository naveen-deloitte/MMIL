from __future__ import annotations

import pytest

from idp.errors import ProcessingError
from idp.extraction.deidentification import (
    redact_pages,
    restore_provider_analysis,
    restore_provider_citations,
)
from idp.extraction.text import PageText


def test_redacts_common_identifiers_and_preserves_medical_text_positions() -> None:
    page = PageText(
        page_number=1,
        text=(
            "Patient Name: Aarav Mehta\n"
            "Age: 42\n"
            "Age/Sex: 42 years / Male\n"
            "A 42-year-old patient\n"
            "DOB: 1982-03-04\n"
            "Phone: +1 (212) 555-0199\n"
            "Email: aarav@example.com\n"
            "MRN: MR-12345\n"
            "HbA1c: 8.2%"
        ),
        width=100,
        height=100,
    )

    redacted = redact_pages([page])[0]

    for identifier in ("Aarav", "Mehta", "42", "1982", "212", "555-0199", "aarav@", "MR-12345"):
        assert identifier not in redacted.text
    assert "HbA1c: 8.2%" in redacted.text
    assert len(redacted.text) == len(page.text)


def test_restores_original_citation_after_model_sees_redacted_text() -> None:
    page = PageText(
        page_number=1,
        text="Patient Name: Aarav Mehta\nHbA1c: 8.2%",
        width=100,
        height=100,
    )
    redacted = redact_pages([page])
    fields = [
        {
            "field_path": "labs.hba1c",
            "source_literal": "8.2",
            "page": 1,
            "excerpt": "HbA1c: 8.2%",
            "confidence": 0.9,
        }
    ]

    restored_fields, restored_facts = restore_provider_citations(
        fields, [], [page], redacted
    )

    assert restored_fields[0]["excerpt"] == "HbA1c: 8.2%"
    assert restored_fields[0]["source_literal"] == "8.2"
    assert restored_facts == []


def test_rejects_model_output_that_selects_a_redacted_value() -> None:
    page = PageText(page_number=1, text="Patient Name: Aarav Mehta", width=100, height=100)
    redacted = redact_pages([page])
    facts = [
        {
            "name": "patient",
            "category": "other",
            "data_type": "text",
            "source_literal": "XXXXX",
            "page": 1,
            "excerpt": redacted[0].text,
            "confidence": 0.9,
        }
    ]

    with pytest.raises(ProcessingError) as error:
        restore_provider_citations([], facts, [page], redacted)

    assert error.value.code == "provider_citation_invalid"


def test_restores_citations_for_ai_findings_labs_and_screening_evidence() -> None:
    page = PageText(
        page_number=1,
        text=(
            "Patient Name: Aarav Mehta\n"
            "HbA1c: 8.2%\n"
            "HIV: Non-reactive"
        ),
        width=100,
        height=100,
    )
    redacted = redact_pages([page])
    analysis = {
        "summary": {
            "text": "The report records HbA1c of 8.2%.",
            "citations": [{"page": 1, "excerpt": "HbA1c: 8.2%"}],
        },
        "key_medical_findings": [{
            "text": "HbA1c is recorded as 8.2%.",
            "citations": [{"page": 1, "excerpt": "HbA1c: 8.2%"}],
        }],
        "recommendations": [],
        "vitals_summary": None,
        "major_vital_factors": [],
        "lab_results": [{
            "category": "blood_sugar",
            "name": "HbA1c",
            "value": "8.2",
            "unit": "%",
            "reference_range": None,
            "reported_flag": None,
            "confidence": 0.9,
            "citations": [{"page": 1, "excerpt": "HbA1c: 8.2%"}],
        }],
        "knockout_checks": [{
            "factor": "HIV",
            "value": "Non-reactive",
            "confidence": 0.95,
            "citations": [{"page": 1, "excerpt": "HIV: Non-reactive"}],
        }],
    }

    restored, rejected = restore_provider_analysis(
        analysis,
        [page],
        redacted,
        document_id="doc-1",
        document_version=1,
    )

    assert rejected == 0
    assert restored["key_medical_findings"][0]["citations"][0]["excerpt"] == "HbA1c: 8.2%"
    assert restored["lab_results"][0]["value"] == "8.2"
    assert restored["lab_results"][0]["citations"][0]["document_id"] == "doc-1"
    assert restored["knockout_checks"][0]["citations"][0]["excerpt"] == "HIV: Non-reactive"


def test_invalid_ai_citation_does_not_discard_valid_analysis_sections() -> None:
    page = PageText(
        page_number=1,
        text="HbA1c: 8.2%\nHIV: Non-reactive",
        width=100,
        height=100,
    )
    redacted = redact_pages([page])
    analysis = {
        "summary": {
            "text": "The report records HbA1c of 8.2%.",
            "citations": [{"page": 1, "excerpt": "not in the source"}],
        },
        "key_medical_findings": [{
            "text": "HIV is non-reactive.",
            "citations": [{"page": 1, "excerpt": "HIV: Non-reactive"}],
        }],
        "recommendations": [],
        "vitals_summary": None,
        "major_vital_factors": [],
        "lab_results": [],
        "knockout_checks": [],
    }

    restored, rejected = restore_provider_analysis(
        analysis,
        [page],
        redacted,
        document_id="doc-1",
        document_version=1,
    )

    assert rejected == 1
    assert restored["summary"] is None
    assert restored["key_medical_findings"][0]["citations"][0]["excerpt"] == (
        "HIV: Non-reactive"
    )
