from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]{1,99}$")
FIELD_PATH_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")

DataType = Literal["decimal", "integer", "text", "measurement_pair", "date", "boolean"]
UiSection = Literal[
    "summary",
    "vitals",
    "labs",
    "checks",
    "assessment",
    "additional",
    "identity",
    "contact",
    "bank_details",
    "supporting_documents",
    "consent",
]


class ClassificationDefinition(BaseModel):
    hints: list[str] = Field(default_factory=list, max_length=50)
    minimum_confidence: float = Field(default=0.8, ge=0, le=1)
    separation_margin: float = Field(default=0.1, ge=0, le=1)
    on_uncertain: Literal["require_type_selection", "fail"] = "require_type_selection"


class ConstraintDefinition(BaseModel):
    media_types: list[str] = Field(min_length=1)
    max_pages: int = Field(default=200, ge=1, le=2000)


class ExtractionDefinition(BaseModel):
    strategy: Literal[
        "deterministic_only",
        "llm_with_deterministic_validation",
        "llm_only_with_grounding_validation",
    ] = "llm_with_deterministic_validation"
    prompt_version: str
    capture_additional_facts: bool = True

    @field_validator("prompt_version")
    @classmethod
    def versioned_prompt(cls, value: str) -> str:
        if not value.strip() or not any(character.isdigit() for character in value):
            raise ValueError("prompt_version must be explicit and versioned")
        return value


class AdditionalFactDefinition(BaseModel):
    enabled: bool = True
    allowed_categories: list[str] = Field(default_factory=list, max_length=50)
    citations_required: bool = True
    max_items: int = Field(default=100, ge=0, le=200)

    @field_validator("allowed_categories")
    @classmethod
    def valid_categories(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("additional fact categories must be unique")
        for value in values:
            if not IDENTIFIER_RE.fullmatch(value):
                raise ValueError("additional fact categories must be lowercase identifiers")
        return values

    @model_validator(mode="after")
    def enabled_has_bounds(self) -> AdditionalFactDefinition:
        if self.enabled and (not self.allowed_categories or self.max_items < 1):
            raise ValueError("enabled additional facts require categories and a positive max_items")
        return self


class PatternDefinition(BaseModel):
    regex: str = Field(min_length=3, max_length=500)
    value_group: str = "value"

    @field_validator("regex")
    @classmethod
    def valid_regex(cls, value: str) -> str:
        try:
            compiled = re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regular expression: {exc}") from exc
        if "value" not in compiled.groupindex:
            raise ValueError("pattern must contain a named 'value' group")
        return value


class FieldDefinition(BaseModel):
    path: str
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=3, max_length=500)
    data_type: DataType
    ui_section: UiSection
    ui_group: str = Field(default="Other", min_length=1, max_length=100)
    unit: str | None = Field(default=None, max_length=50)
    required: bool = False
    citations_required: bool = True
    normalizers: list[str] = Field(default_factory=lambda: ["trim"], max_length=20)
    validators: list[str] = Field(default_factory=lambda: ["type"], max_length=20)
    patterns: list[PatternDefinition] = Field(default_factory=list, max_length=20)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        if not FIELD_PATH_RE.fullmatch(value):
            raise ValueError("field path must be a dotted lowercase identifier")
        return value

    @field_validator("normalizers", "validators")
    @classmethod
    def valid_named_steps(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("normalizer and validator IDs must be unique")
        for value in values:
            if not IDENTIFIER_RE.fullmatch(value):
                raise ValueError("normalizer and validator IDs must be lowercase identifiers")
        return values


class DocumentTypeDefinition(BaseModel):
    document_type: str
    schema_version: str
    display_name: str = Field(min_length=1, max_length=200)
    classification: ClassificationDefinition = Field(default_factory=ClassificationDefinition)
    constraints: ConstraintDefinition
    extraction: ExtractionDefinition
    fields: list[FieldDefinition] = Field(min_length=1, max_length=500)
    additional_facts: AdditionalFactDefinition = Field(
        default_factory=lambda: AdditionalFactDefinition(enabled=False)
    )

    @field_validator("document_type")
    @classmethod
    def valid_identifier(cls, value: str) -> str:
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError("document_type must be a lowercase identifier")
        return value

    @field_validator("schema_version")
    @classmethod
    def valid_semver(cls, value: str) -> str:
        if not SEMVER_RE.fullmatch(value):
            raise ValueError("schema_version must be semantic version format")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> DocumentTypeDefinition:
        paths = [field.path for field in self.fields]
        if len(paths) != len(set(paths)):
            raise ValueError("field paths must be unique")
        if self.extraction.strategy == "deterministic_only":
            missing = [field.path for field in self.fields if not field.patterns]
            if missing:
                raise ValueError("deterministic-only fields require extraction patterns")
        if not self.extraction.capture_additional_facts and self.additional_facts.enabled:
            raise ValueError("additional facts cannot be enabled when capture is disabled")
        return self

    @property
    def checksum(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


class DocumentTypeRegistry:
    def __init__(
        self,
        definition: DocumentTypeDefinition,
        definitions: dict[str, DocumentTypeDefinition] | None = None,
    ):
        self.definition = definition
        self._definitions = definitions or {definition.document_type: definition}

    @classmethod
    def load(cls, path: Path) -> DocumentTypeRegistry:
        with path.expanduser().open("r", encoding="utf-8") as stream:
            raw = json.load(stream)
        return cls(DocumentTypeDefinition.model_validate(raw))

    @classmethod
    def load_catalog(cls, path: Path) -> DocumentTypeRegistry:
        source = path.expanduser()
        directory = source if source.is_dir() else source.parent
        definitions = {
            definition.document_type: definition
            for schema_path in sorted(directory.glob("*.json"))
            for definition in [cls.load(schema_path).definition]
        }
        if source.is_file():
            default_type = cls.load(source).definition.document_type
        else:
            default_type = "medical_report"
        if default_type not in definitions:
            raise ValueError(f"default document type is not configured: {default_type}")
        return cls(definitions[default_type], definitions)

    def for_type(self, document_type: str) -> DocumentTypeRegistry:
        try:
            definition = self._definitions[document_type]
        except KeyError as exc:
            raise KeyError(document_type) from exc
        return DocumentTypeRegistry(definition, self._definitions)

    def field(self, path: str) -> FieldDefinition:
        for definition in self.definition.fields:
            if definition.path == path:
                return definition
        raise KeyError(path)
