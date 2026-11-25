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
    assert registry.definition.extraction.capture_additional_facts is True
    assert registry.definition.additional_facts.max_items == 100
    assert registry.definition.checksum.startswith("sha256:")
    assert len(registry.definition.checksum) == 71


def test_configuration_checksum_changes_with_contract_content() -> None:
    raw = json.loads(
        (ROOT / "config" / "document-types" / "medical-report.v1.json").read_text(
            encoding="utf-8"
        )
    )
    original = DocumentTypeDefinition.model_validate(raw)
    raw["fields"][0]["description"] += " Clarified."
    changed = DocumentTypeDefinition.model_validate(raw)
    assert changed.checksum != original.checksum


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
