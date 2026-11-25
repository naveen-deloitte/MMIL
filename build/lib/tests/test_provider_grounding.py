from __future__ import annotations

from pathlib import Path

import pytest

from idp.document_types import DocumentTypeRegistry
from idp.errors import ProcessingError
from idp.extraction.engine import SchemaExtractor
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
                }
            ],
            pages=pages,
            document_id="doc-1",
            document_version=1,
            registry=registry,
        )
    assert error.value.code == "citation_invalid"
