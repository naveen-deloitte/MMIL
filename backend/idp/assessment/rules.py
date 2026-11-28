"""Configurable underwriting rules and an optional points-based risk scoring model.

Rules are loaded from ``IDP_UNDERWRITING_RULES_PATH``. Nothing is assumed when the path is
missing: there are then no rules, no recommendation and no risk score.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_RE = r"^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$"
Operator = Literal["gt", "gte", "lt", "lte", "eq", "matches", "count_gte"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuleSource(_Strict):
    type: Literal["field", "lab_flags", "proposal", "cover_to_income", "identity_match"]
    field_path: str | None = None
    component: Literal["systolic", "diastolic"] | None = None
    key: Literal["sum_assured", "policy_term", "premium_payment_term"] | None = None
    flags: list[str] | None = None

    @model_validator(mode="after")
    def check(self) -> RuleSource:
        if self.type == "field" and not self.field_path:
            raise ValueError("field rules need field_path")
        if self.type == "proposal" and not self.key:
            raise ValueError("proposal rules need key")
        if self.type == "lab_flags" and not self.flags:
            raise ValueError("lab_flags rules need flags")
        return self


class Rule(_Strict):
    rule_id: str = Field(pattern=ID_RE)
    title: str = Field(min_length=3, max_length=200)
    category: Literal["medical", "lifestyle", "financial", "identity", "other"]
    source: RuleSource
    operator: Operator
    value: float | int | str
    outcome: Literal["refer", "advisory"]
    points: int = Field(default=0, ge=0, le=1000)
    rationale: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def check_value(self) -> Rule:
        if self.operator == "matches":
            if not isinstance(self.value, str):
                raise ValueError("matches needs a regex string")
            re.compile(self.value)
        elif self.operator != "eq" and isinstance(self.value, str):
            raise ValueError(f"{self.operator} needs a number")
        return self


class Band(_Strict):
    max: int
    label: str = Field(min_length=1, max_length=50)
    interpretation: str = Field(min_length=3, max_length=300)


class RiskScoring(_Strict):
    model_id: str = Field(pattern=ID_RE)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    approved: bool
    method: str = Field(min_length=3, max_length=300)
    scale_min: int = 0
    scale_max: int = Field(gt=0)
    bands: list[Band] = Field(min_length=1)

    @field_validator("bands")
    @classmethod
    def ordered(cls, bands: list[Band]) -> list[Band]:
        if [b.max for b in bands] != sorted(b.max for b in bands):
            raise ValueError("bands must be in ascending order of max")
        return bands


class RuleSet(_Strict):
    rule_set_id: str = Field(pattern=ID_RE)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    is_demo: bool
    source: str = Field(min_length=3, max_length=300)
    rules: list[Rule] = Field(default_factory=list)
    risk_scoring: RiskScoring | None = None

    @model_validator(mode="after")
    def unique(self) -> RuleSet:
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule_id values must be unique")
        return self

    @property
    def checksum(self) -> str:
        raw = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def load_rule_set(path: Path | None) -> RuleSet | None:
    """Load the single rule set from a file, or the only ``*.json`` file in a directory."""
    if path is None:
        return None
    source = path.expanduser()
    if not source.exists():
        return None
    files = sorted(source.glob("*.json")) if source.is_dir() else [source]
    if not files:
        return None
    if len(files) > 1:
        raise ValueError("underwriting rules directory must contain exactly one rule set")
    with files[0].open("r", encoding="utf-8") as stream:
        return RuleSet.model_validate(json.load(stream))


def compare(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "matches":
        return re.search(str(expected), str(actual), re.IGNORECASE) is not None
    if operator == "eq":
        return str(actual).casefold() == str(expected).casefold()
    number = float(actual)
    target = float(expected)
    return {
        "gt": number > target,
        "gte": number >= target,
        "lt": number < target,
        "lte": number <= target,
        "count_gte": number >= target,
    }[operator]


def score_band(scoring: RiskScoring, score: int) -> Band:
    for band in scoring.bands:
        if score <= band.max:
            return band
    return scoring.bands[-1]
