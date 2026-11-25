from __future__ import annotations

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
class _Match:
    page: PageText
    source_literal: str
    normalized_value: Any
    excerpt: str
    bbox: dict[str, float] | None


class SchemaExtractor:
    def __init__(self, definition: DocumentTypeDefinition):
        self.definition = definition

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
    candidates: list[ExtractedCandidate],
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
