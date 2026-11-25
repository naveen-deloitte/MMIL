from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from idp.document_types import DocumentTypeDefinition, FieldDefinition
from idp.errors import ProcessingError
from idp.extraction.text import PageText, TextBlock

EXTRACTOR_VERSION = "deterministic-regex-1.0.0"


@dataclass(frozen=True)
class Citation:
    document_id: str
    document_version: int
    page: int
    excerpt: str
    bbox: dict[str, float] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "document_version": self.document_version,
            "page": self.page,
            "excerpt": self.excerpt,
            "bbox": self.bbox,
        }


@dataclass(frozen=True)
class ExtractedCandidate:
    field_path: str
    label: str
    ui_section: str
    ui_group: str
    data_type: str
    unit: str | None
    source_literal: str | None
    normalized_value: Any | None
    status: str
    confidence: float | None
    citations: list[Citation] = field(default_factory=list)
    validations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class AdditionalFactCandidate:
    name: str
    category: str
    data_type: str
    unit: str | None
    source_literal: str
    normalized_value: Any
    status: str
    confidence: float
    citations: list[Citation]
    linked_field_path: str | None = None
    validations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _Match:
    page: PageText
    source_literal: str
    normalized_value: Any
    excerpt: str
    bbox: dict[str, float] | None


class SchemaExtractor:
    def __init__(self, definition: DocumentTypeDefinition):
        self.definition = definition

    def empty_candidates(self) -> list[ExtractedCandidate]:
        return [
            ExtractedCandidate(
                field_path=definition.path,
                label=definition.label,
                ui_section=definition.ui_section,
                ui_group=definition.ui_group,
                data_type=definition.data_type,
                unit=definition.unit,
                source_literal=None,
                normalized_value=None,
                status="not_found",
                confidence=None,
                citations=[],
                validations=(
                    [{"code": "required_field_missing", "severity": "error"}]
                    if definition.required
                    else []
                ),
            )
            for definition in self.definition.fields
        ]

    def extract(
        self, *, document_id: str, document_version: int, pages: list[PageText]
    ) -> list[ExtractedCandidate]:
        candidates = [
            self._extract_field(
                definition,
                document_id=document_id,
                document_version=document_version,
                pages=pages,
            )
            for definition in self.definition.fields
        ]
        validate_grounding(candidates, pages, document_id, document_version)
        return candidates

    def _extract_field(
        self,
        definition: FieldDefinition,
        *,
        document_id: str,
        document_version: int,
        pages: list[PageText],
    ) -> ExtractedCandidate:
        matches: list[_Match] = []
        invalid_literals: list[str] = []
        for page in pages:
            for pattern in definition.patterns:
                compiled = re.compile(pattern.regex)
                for match in compiled.finditer(page.text):
                    literal = match.group(pattern.value_group).strip()
                    try:
                        normalized = normalize_value(definition.data_type, literal)
                    except ValueError:
                        invalid_literals.append(literal)
                        continue
                    excerpt = match.group(0).strip()
                    bbox = _find_bbox(page.blocks, literal, page.width, page.height)
                    matches.append(
                        _Match(
                            page=page,
                            source_literal=literal,
                            normalized_value=normalized,
                            excerpt=excerpt,
                            bbox=bbox,
                        )
                    )

        if not matches:
            validation = []
            if invalid_literals:
                validation.append({"code": "invalid_literal", "severity": "warning"})
            if definition.required:
                validation.append({"code": "required_field_missing", "severity": "error"})
            return ExtractedCandidate(
                field_path=definition.path,
                label=definition.label,
                ui_section=definition.ui_section,
                ui_group=definition.ui_group,
                data_type=definition.data_type,
                unit=definition.unit,
                source_literal=None,
                normalized_value=None,
                status="uncertain" if invalid_literals else "not_found",
                confidence=None,
                citations=[],
                validations=validation,
            )

        unique_values = {_stable_value(match.normalized_value) for match in matches}
        primary = matches[0]
        status = "found" if len(unique_values) == 1 else "uncertain"
        validations: list[dict[str, Any]] = []
        if len(unique_values) > 1:
            validations.append({"code": "multiple_distinct_values", "severity": "warning"})
        citations = [
            Citation(
                document_id=document_id,
                document_version=document_version,
                page=item.page.page_number,
                excerpt=item.excerpt,
                bbox=item.bbox,
            )
            for item in matches
        ]
        confidences = [
            item.page.confidence if item.page.confidence is not None else 0.8 for item in matches
        ]
        return ExtractedCandidate(
            field_path=definition.path,
            label=definition.label,
            ui_section=definition.ui_section,
            ui_group=definition.ui_group,
            data_type=definition.data_type,
            unit=definition.unit,
            source_literal=primary.source_literal,
            normalized_value=primary.normalized_value,
            status=status,
            confidence=min(0.99, sum(confidences) / len(confidences) * 0.98),
            citations=citations,
            validations=validations,
        )


def extract_additional_facts(
    *,
    raw_facts: list[dict[str, Any]],
    definition: DocumentTypeDefinition,
    primary_fields: list[ExtractedCandidate],
    pages: list[PageText],
    document_id: str,
    document_version: int,
) -> list[AdditionalFactCandidate]:
    policy = definition.additional_facts
    if not raw_facts:
        return []
    if not policy.enabled or not definition.extraction.capture_additional_facts:
        raise ProcessingError("additional_facts_not_enabled", retryable=False)
    if len(raw_facts) > policy.max_items:
        raise ProcessingError("additional_fact_limit_exceeded", retryable=False)

    page_map = {page.page_number: page for page in pages}
    allowed_keys = {
        "name",
        "category",
        "data_type",
        "unit",
        "source_literal",
        "page",
        "excerpt",
        "confidence",
        "linked_field_path",
    }
    primary_paths = {field.field_path for field in primary_fields}
    primary_evidence = {
        (
            field.source_literal,
            citation.page,
            citation.excerpt,
        )
        for field in primary_fields
        if field.source_literal is not None
        for citation in field.citations
    }
    seen: set[tuple[str, str, int, str]] = set()
    facts: list[AdditionalFactCandidate] = []
    for item in raw_facts:
        if not isinstance(item, dict) or set(item) - allowed_keys:
            raise ProcessingError("invalid_additional_fact", retryable=False)
        name = item.get("name")
        category = item.get("category")
        data_type = item.get("data_type", "text")
        unit = item.get("unit")
        literal = item.get("source_literal")
        page_number = item.get("page")
        excerpt = item.get("excerpt")
        linked_path = item.get("linked_field_path")
        if (
            not isinstance(name, str)
            or not name.strip()
            or len(name) > 200
            or category not in policy.allowed_categories
            or not isinstance(data_type, str)
            or not isinstance(literal, str)
            or not literal.strip()
            or not isinstance(page_number, int)
            or not isinstance(excerpt, str)
            or page_number not in page_map
            or excerpt not in page_map[page_number].text
            or literal not in excerpt
            or (unit is not None and (not isinstance(unit, str) or len(unit) > 50))
            or (linked_path is not None and linked_path not in primary_paths)
        ):
            raise ProcessingError("invalid_additional_fact", retryable=False)
        validations: list[dict[str, Any]] = []
        if data_type not in {"decimal", "integer", "text", "measurement_pair", "date", "boolean"}:
            data_type = "text"
            validations.append(
                {"code": "unsupported_type_preserved_as_text", "severity": "warning"}
            )
        try:
            normalized = normalize_value(str(data_type), literal)
            confidence_raw = item.get("confidence")
            if (
                isinstance(confidence_raw, bool)
                or not isinstance(confidence_raw, (int, float))
                or not math.isfinite(confidence_raw)
                or not 0 <= confidence_raw <= 1
            ):
                raise ValueError("invalid confidence")
            confidence = float(confidence_raw)
        except (TypeError, ValueError) as exc:
            raise ProcessingError("invalid_additional_fact", retryable=False) from exc
        if (literal, page_number, excerpt) in primary_evidence:
            continue
        dedupe_key = (str(category), literal, page_number, excerpt)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        page = page_map[page_number]
        fact = AdditionalFactCandidate(
            name=name.strip(),
            category=str(category),
            data_type=str(data_type),
            unit=unit,
            source_literal=literal,
            normalized_value=normalized,
            status="found",
            confidence=confidence,
            citations=[
                Citation(
                    document_id=document_id,
                    document_version=document_version,
                    page=page_number,
                    excerpt=excerpt,
                    bbox=_find_bbox(page.blocks, literal, page.width, page.height),
                )
            ],
            linked_field_path=linked_path,
            validations=validations,
        )
        facts.append(fact)
    validate_grounding(facts, pages, document_id, document_version)
    return facts


def normalize_value(data_type: str, literal: str) -> Any:
    value = literal.strip()
    if data_type == "text":
        if not value:
            raise ValueError("empty text")
        return value
    if data_type == "decimal":
        return float(value.replace(",", ""))
    if data_type == "integer":
        return int(value.replace(",", ""))
    if data_type == "measurement_pair":
        left, separator, right = value.replace(" ", "").partition("/")
        if not separator:
            raise ValueError("expected pair")
        return {"systolic": int(left), "diastolic": int(right)}
    if data_type == "boolean":
        lowered = value.casefold()
        if lowered in {"yes", "true", "present", "positive"}:
            return True
        if lowered in {"no", "false", "absent", "negative"}:
            return False
        raise ValueError("invalid boolean")
    if data_type == "date":
        for date_format in ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, date_format).date().isoformat()
            except ValueError:
                continue
        raise ValueError("invalid date")
    raise ValueError("unsupported data type")


def validate_grounding(
    candidates: list[ExtractedCandidate] | list[AdditionalFactCandidate],
    pages: list[PageText],
    document_id: str,
    document_version: int,
) -> None:
    page_map = {page.page_number: page for page in pages}
    for candidate in candidates:
        if candidate.normalized_value is None:
            continue
        if not candidate.citations:
            raise ProcessingError("citation_missing", retryable=False)
        for citation in candidate.citations:
            page = page_map.get(citation.page)
            if (
                citation.document_id != document_id
                or citation.document_version != document_version
                or page is None
                or citation.excerpt not in page.text
            ):
                raise ProcessingError("citation_invalid", retryable=False)


def _find_bbox(
    blocks: list[TextBlock], literal: str, page_width: float, page_height: float
) -> dict[str, float] | None:
    literal_folded = literal.casefold()
    for block in blocks:
        if literal_folded in block.text.casefold():
            return {
                "x0": round(block.x0, 2),
                "y0": round(block.y0, 2),
                "x1": round(block.x1, 2),
                "y1": round(block.y1, 2),
                "page_width": round(page_width, 2),
                "page_height": round(page_height, 2),
            }
    return None


def _stable_value(value: Any) -> str:
    if isinstance(value, dict):
        return "|".join(f"{key}={value[key]}" for key in sorted(value))
    return repr(value)
