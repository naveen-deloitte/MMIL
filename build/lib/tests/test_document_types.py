from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from idp.document_types import DocumentTypeDefinition, DocumentTypeRegistry

ROOT = Path(__file__).resolve().parents[2]


def test_shipped_medical_schema_is_valid() -> None:
    registry = DocumentTypeRegistry.load(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )
    assert registry.definition.document_type == "medical_report"
    assert registry.definition.schema_version == "1.0.0"
    assert len(registry.definition.fields) >= 20
    assert len({field.path for field in registry.definition.fields}) == len(
        registry.definition.fields
    )


def test_schema_rejects_duplicate_paths() -> None:
    raw = json.loads(
        (ROOT / "config" / "document-types" / "medical-report.v1.json").read_text(encoding="utf-8")
    )
    raw["fields"].append(raw["fields"][0])
    with pytest.raises(ValidationError, match="unique"):
        DocumentTypeDefinition.model_validate(raw)


def test_schema_rejects_pattern_without_value_group() -> None:
    raw = json.loads(
        (ROOT / "config" / "document-types" / "medical-report.v1.json").read_text(encoding="utf-8")
    )
    raw["fields"][0]["patterns"][0]["regex"] = r"Report Date: .*"
    with pytest.raises(ValidationError, match="named 'value' group"):
        DocumentTypeDefinition.model_validate(raw)
