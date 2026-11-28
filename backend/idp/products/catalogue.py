"""Insurance product catalogue loaded from versioned JSON files.

Every product value shown in the UI comes from these files. Nothing is defaulted in code: a value
missing from the configuration is reported as unavailable. Catalogue files live in
``IDP_PRODUCT_CATALOGUE_PATH`` (a directory of ``*.json`` files or a single file).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PRODUCT_ID_RE = r"^[A-Za-z0-9][A-Za-z0-9._-]{1,99}$"
Frequency = Literal["single", "annual", "half_yearly", "quarterly", "monthly"]
Gender = Literal["male", "female", "other"]
FREQUENCY_LABELS: dict[str, str] = {
    "single": "Single premium",
    "annual": "Annual",
    "half_yearly": "Half-yearly",
    "quarterly": "Quarterly",
    "monthly": "Monthly",
}
POLICY_TERM_KEYWORD = "policy_term"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AmountRange(_Strict):
    """Either a fixed list of permitted amounts or a min/max range with an optional step."""

    currency: str = Field(min_length=3, max_length=3)
    options: list[int] | None = Field(default=None, min_length=1)
    min: int | None = Field(default=None, gt=0)
    max: int | None = Field(default=None, gt=0)
    step: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_shape(self) -> AmountRange:
        if self.options is None and (self.min is None or self.max is None):
            raise ValueError("sum_assured needs options, or both min and max")
        if self.options is not None and (self.min is not None or self.max is not None):
            raise ValueError("sum_assured cannot mix options with min/max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("sum_assured min is greater than max")
        if self.options is not None and any(value <= 0 for value in self.options):
            raise ValueError("sum_assured options must be positive")
        return self

    def permits(self, value: int) -> bool:
        if self.options is not None:
            return value in self.options
        assert self.min is not None and self.max is not None
        if not self.min <= value <= self.max:
            return False
        return self.step is None or (value - self.min) % self.step == 0


class TermRange(_Strict):
    """Permitted terms in years. ``options`` may include ``"policy_term"`` for regular pay."""

    options: list[int | Literal["policy_term"]] | None = Field(default=None, min_length=1)
    min: int | None = Field(default=None, gt=0, le=100)
    max: int | None = Field(default=None, gt=0, le=100)

    @model_validator(mode="after")
    def check_shape(self) -> TermRange:
        if self.options is None and (self.min is None or self.max is None):
            raise ValueError("terms need options, or both min and max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("term min is greater than max")
        return self

    def permits(self, value: int, *, policy_term: int | None = None) -> bool:
        if self.options is not None:
            return value in self.options or (
                POLICY_TERM_KEYWORD in self.options and policy_term is not None and value == policy_term
            )
        assert self.min is not None and self.max is not None
        return self.min <= value <= self.max


class RateRow(_Strict):
    """One configured rate. ``None`` on a criterion means the row applies to any value."""

    age_min: int = Field(ge=0, le=120)
    age_max: int = Field(ge=0, le=120)
    gender: Gender | None = None
    smoker: bool | None = None
    policy_term: int | None = Field(default=None, gt=0)
    rate: float = Field(gt=0)

    @model_validator(mode="after")
    def check_ages(self) -> RateRow:
        if self.age_min > self.age_max:
            raise ValueError("rate row age_min is greater than age_max")
        return self


class FixedPremium(_Strict):
    sum_assured: int = Field(gt=0)
    premium_frequency: Frequency
    policy_term: int | None = Field(default=None, gt=0)
    amount: float = Field(gt=0)


class PricingRules(_Strict):
    """How an indicative premium is derived. Results are never an official insurer quote."""

    method: Literal["rate_per_thousand_sum_assured", "fixed_premium_table"]
    basis_note: str = Field(min_length=3, max_length=500)
    rating_factors: list[Literal["age", "gender", "smoker", "policy_term"]] = Field(
        default_factory=list
    )
    rate_table: list[RateRow] | None = None
    frequency_factors: dict[Frequency, float] | None = None
    premiums: list[FixedPremium] | None = None
    tax_rate: float | None = Field(default=None, ge=0, le=1)
    rounding_decimals: int = Field(default=0, ge=0, le=2)

    @model_validator(mode="after")
    def check_method(self) -> PricingRules:
        if self.method == "rate_per_thousand_sum_assured":
            if not self.rate_table:
                raise ValueError("rate_per_thousand_sum_assured requires a rate_table")
            if not self.frequency_factors:
                raise ValueError("rate_per_thousand_sum_assured requires frequency_factors")
        if self.method == "fixed_premium_table" and not self.premiums:
            raise ValueError("fixed_premium_table requires premiums")
        return self


class RiderOption(_Strict):
    rider_id: str = Field(pattern=PRODUCT_ID_RE)
    name: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    sum_assured: AmountRange | None = None


class Product(_Strict):
    product_id: str = Field(pattern=PRODUCT_ID_RE)
    product_name: str = Field(min_length=2, max_length=200)
    insurer: str = Field(min_length=2, max_length=200)
    insurance_type: str | None = Field(default=None, max_length=100)
    plan_name: str | None = Field(default=None, max_length=200)
    uin: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=1000)
    status: Literal["active", "withdrawn"] = "active"
    entry_age_min: int | None = Field(default=None, ge=0, le=120)
    entry_age_max: int | None = Field(default=None, ge=0, le=120)
    sum_assured: AmountRange | None = None
    premium_frequencies: list[Frequency] | None = Field(default=None, min_length=1)
    policy_terms: TermRange | None = None
    premium_payment_terms: TermRange | None = None
    pricing: PricingRules | None = None
    # Policy benefits as configured by the insurer. Optional; missing means "Not Available".
    cover_type: str | None = Field(default=None, max_length=200)
    death_benefit: str | None = Field(default=None, max_length=500)
    maturity_benefit: str | None = Field(default=None, max_length=500)
    riders: list[RiderOption] | None = None
    additional_benefits: list[str] | None = None

    @field_validator("product_name", "insurer")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be blank")
        return value


class CatalogueFile(_Strict):
    catalogue_id: str = Field(pattern=PRODUCT_ID_RE)
    catalogue_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    source: str = Field(min_length=3, max_length=300)
    is_demo: bool
    effective_date: str | None = None
    products: list[Product] = Field(default_factory=list)


class CatalogueError(ValueError):
    pass


class ProductCatalogue:
    """In-memory view over one or more catalogue files."""

    def __init__(self, files: list[CatalogueFile]):
        self.files = files
        self._products: dict[str, tuple[Product, CatalogueFile]] = {}
        for catalogue in files:
            for product in catalogue.products:
                if product.product_id in self._products:
                    raise CatalogueError(f"duplicate product_id: {product.product_id}")
                self._products[product.product_id] = (product, catalogue)

    @classmethod
    def load(cls, path: Path | None) -> ProductCatalogue:
        if path is None:
            return cls([])
        source = path.expanduser()
        if not source.exists():
            return cls([])
        paths = sorted(source.glob("*.json")) if source.is_dir() else [source]
        files: list[CatalogueFile] = []
        for item in paths:
            with item.open("r", encoding="utf-8") as stream:
                files.append(CatalogueFile.model_validate(json.load(stream)))
        return cls(files)

    def search(self, query: str = "", *, include_withdrawn: bool = False) -> list[tuple[Product, CatalogueFile]]:
        tokens = [t for t in re.split(r"\s+", query.casefold().strip()) if t]
        results = []
        for product, catalogue in self._products.values():
            if product.status != "active" and not include_withdrawn:
                continue
            haystack = " ".join(
                filter(None, [product.product_name, product.insurer, product.insurance_type,
                              product.plan_name, product.uin])
            ).casefold()
            if all(token in haystack for token in tokens):
                results.append((product, catalogue))
        results.sort(key=lambda item: (item[0].product_name.casefold(), item[0].insurer.casefold()))
        return results

    def get(self, product_id: str) -> tuple[Product, CatalogueFile] | None:
        return self._products.get(product_id)


def describe_terms(terms: TermRange | None) -> dict[str, Any] | None:
    if terms is None:
        return None
    return terms.model_dump(exclude_none=True)


def allowed_frequency_label(value: str) -> str:
    return FREQUENCY_LABELS.get(value, value)
