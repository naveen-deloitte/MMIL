from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from idp.config import Settings
from idp.document_types import DocumentTypeRegistry
from idp.errors import ProcessingError
from idp.extraction.providers import OpenAICompatibleProvider
from idp.extraction.text import PageText

ROOT = Path(__file__).resolve().parents[2]


def _provider() -> OpenAICompatibleProvider:
    settings = Settings(
        _env_file=None,
        extraction_provider="openai-compatible",
        allowed_providers="openai-compatible",
        external_provider_approved=True,
        model_endpoint="https://api.example.test/v1",
        model_id="test-model",
        model_api_key=SecretStr("test-secret"),
    )
    return OpenAICompatibleProvider(settings)


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(400, json={"error": "request rejected"}), "provider_request_rejected"),
        (
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "not-json"}}]},
            ),
            "provider_response_invalid_json",
        ),
        (
            httpx.Response(200, json={"choices": [{"message": {"content": "[]"}}]}),
            "provider_response_schema_invalid",
        ),
    ],
)
def test_provider_failures_are_classified_without_response_details(
    monkeypatch: pytest.MonkeyPatch,
    response: httpx.Response,
    expected_code: str,
) -> None:
    response.request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return response

    monkeypatch.setattr("idp.extraction.providers.httpx.Client", lambda **_kwargs: FakeClient())
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )

    with pytest.raises(ProcessingError) as error:
        _provider().extract(pages=[], definition=registry.definition)

    assert error.value.code == expected_code
    assert "request rejected" not in str(error.value)


def test_provider_parses_grounded_ai_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = {
        "summary": {
            "text": "The report records a finding.",
            "citations": [{"page": 1, "excerpt": "Finding: recorded"}],
        },
        "key_medical_findings": [],
        "recommendations": [],
        "vitals_summary": None,
        "major_vital_factors": [],
        "lab_results": [{
            "category": "hematology",
            "name": "Hemoglobin",
            "value": "13.2",
            "unit": "g/dL",
            "reference_range": "12.0-16.0",
            "reported_flag": None,
            "confidence": 0.94,
            "citations": [{"page": 1, "excerpt": "Hemoglobin: 13.2 g/dL"}],
        }],
        "knockout_checks": [{
            "factor": "HIV",
            "value": "Non-reactive",
            "confidence": 0.96,
            "citations": [{"page": 1, "excerpt": "HIV: Non-reactive"}],
        }],
    }
    response = httpx.Response(
        200,
        json={
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "fields": [],
                        "additional_facts": [],
                        "ai_analysis": analysis,
                    })
                }
            }]
        },
    )
    response.request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return response

    monkeypatch.setattr("idp.extraction.providers.httpx.Client", lambda **_kwargs: FakeClient())
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )

    result = _provider().extract(
        pages=[
            PageText(
                page_number=1,
                text="Finding: recorded\nHemoglobin: 13.2 g/dL\nHIV: Non-reactive",
                width=612,
                height=792,
            )
        ],
        definition=registry.definition,
    )

    assert result.ai_analysis == analysis
    assert result.ai_analysis_error is None


def test_invalid_ai_analysis_is_reported_without_discarding_valid_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = httpx.Response(
        200,
        json={
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "fields": [{
                            "field_path": "observations.bmi",
                            "source_literal": "26.1",
                            "page": 1,
                            "excerpt": "BMI: 26.1 kg/m2",
                            "confidence": 0.9,
                        }],
                        "additional_facts": [],
                        "ai_analysis": {
                            "summary": "missing citations",
                            "key_medical_findings": [{
                                "text": "BMI is recorded as 26.1 kg/m2.",
                                "citations": [{
                                    "page": 1,
                                    "excerpt": "BMI: 26.1 kg/m2",
                                }],
                            }],
                        },
                    })
                }
            }]
        },
    )
    response.request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return response

    monkeypatch.setattr("idp.extraction.providers.httpx.Client", lambda **_kwargs: FakeClient())
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )

    result = _provider().extract(pages=[], definition=registry.definition)

    assert result.fields[0]["field_path"] == "observations.bmi"
    assert result.ai_analysis is not None
    assert result.ai_analysis["summary"] is None
    assert result.ai_analysis["key_medical_findings"][0]["text"] == (
        "BMI is recorded as 26.1 kg/m2."
    )
    assert result.ai_analysis_error == "provider_ai_analysis_summary_invalid"


@pytest.mark.parametrize(
    ("initial_summary", "expected_error"),
    [
        (None, None),
        (
            {
                "text": "The report records HbA1c at 8.2%.",
                "citations": [{"page": 1, "excerpt": "citation not in source"}],
            },
            "provider_ai_analysis_summary_citation_invalid",
        ),
    ],
)
def test_missing_summary_uses_cited_summary_request_and_combines_usage(
    monkeypatch: pytest.MonkeyPatch,
    initial_summary: dict[str, object] | None,
    expected_error: str | None,
) -> None:
    page = PageText(
        page_number=1,
        text="HbA1c: 8.2%",
        width=100,
        height=100,
    )
    initial_analysis = {
        "summary": initial_summary,
        "key_medical_findings": [{
            "text": "HbA1c is recorded as 8.2%.",
            "citations": [{"page": 1, "excerpt": "HbA1c: 8.2%"}],
        }],
        "recommendations": [],
        "vitals_summary": None,
        "major_vital_factors": [],
        "lab_results": [],
        "knockout_checks": [],
    }

    def provider_response(content: dict[str, object], prompt_tokens: int, completion_tokens: int):
        response = httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            },
        )
        response.request = httpx.Request(
            "POST", "https://api.example.test/v1/chat/completions"
        )
        return response

    responses = [
        provider_response({
            "fields": [],
            "additional_facts": [],
            "ai_analysis": initial_analysis,
        }, 10, 20),
        provider_response({
            "summary": {
                "text": "The report records HbA1c at 8.2%.",
                "citations": [{"page": 1, "excerpt": "HbA1c: 8.2%"}],
            }
        }, 2, 3),
    ]

    class FakeClient:
        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, *_args: object, **_kwargs: object) -> httpx.Response:
            return responses.pop(0)

    monkeypatch.setattr("idp.extraction.providers.httpx.Client", lambda **_kwargs: FakeClient())
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )

    result = _provider().extract(pages=[page], definition=registry.definition)

    assert not responses
    assert result.ai_analysis is not None
    assert result.ai_analysis["summary"]["text"] == "The report records HbA1c at 8.2%."
    assert result.ai_analysis_error == expected_error
    assert result.input_tokens == 12
    assert result.output_tokens == 23
