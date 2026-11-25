from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_-]{1,99}$")
FIELD_PATH_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


class ClassifierDefinition(BaseModel):
    hints: list[str] = Field(default_factory=list, max_length=50)


class ConstraintDefinition(BaseModel):
    media_types: list[str] = Field(min_length=1)
    max_pages: int = Field(default=200, ge=1, le=2000)


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
    data_type: Literal["decimal", "integer", "text", "measurement_pair", "date", "boolean"]
    ui_section: Literal["summary", "vitals", "labs", "checks", "assessment"]
    ui_group: str = Field(default="Other", min_length=1, max_length=100)
    unit: str | None = Field(default=None, max_length=50)
    required: bool = False
    citations_required: bool = True
    patterns: list[PatternDefinition] = Field(min_length=1, max_length=20)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value: str) -> str:
        if not FIELD_PATH_RE.fullmatch(value):
            raise ValueError("field path must be a dotted lowercase identifier")
        return value


class DocumentTypeDefinition(BaseModel):
    document_type: str
    schema_version: str
    display_name: str = Field(min_length=1, max_length=200)
    classifier: ClassifierDefinition = Field(default_factory=ClassifierDefinition)
    constraints: ConstraintDefinition
    fields: list[FieldDefinition] = Field(min_length=1, max_length=500)

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
    def unique_paths(self) -> DocumentTypeDefinition:
        paths = [field.path for field in self.fields]
        if len(paths) != len(set(paths)):
            raise ValueError("field paths must be unique")
        return self


class DocumentTypeRegistry:
    def __init__(self, definition: DocumentTypeDefinition):
        self.definition = definition

    @classmethod
    def load(cls, path: Path) -> DocumentTypeRegistry:
        with path.expanduser().open("r", encoding="utf-8") as stream:
            raw = json.load(stream)
        return cls(DocumentTypeDefinition.model_validate(raw))

    def field(self, path: str) -> FieldDefinition:
        for definition in self.definition.fields:
            if definition.path == path:
                return definition
        raise KeyError(path)
