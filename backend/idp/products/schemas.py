"""API models for the product catalogue and case product selection."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from idp.products.catalogue import PRODUCT_ID_RE, CatalogueFile, Product, allowed_frequency_label


class CatalogueInfo(BaseModel):
    catalogue_id: str
    catalogue_version: str
    source: str
    is_demo: bool
    effective_date: str | None = None


class ProductListItem(BaseModel):
    product_id: str
    product_name: str
    insurer: str
    insurance_type: str | None = None
    catalogue: CatalogueInfo


class ProductListOut(BaseModel):
    items: list[ProductListItem]
    catalogue_configured: bool
    demo_catalogue: bool


class OptionOut(BaseModel):
    value: str
    label: str


class ProductDetailOut(BaseModel):
    product_id: str
    product_name: str
    insurer: str
    insurance_type: str | None = None
    plan_name: str | None = None
    uin: str | None = None
    description: str | None = None
    status: str
    entry_age_min: int | None = None
    entry_age_max: int | None = None
    sum_assured: dict[str, Any] | None = None
    premium_frequencies: list[OptionOut] | None = None
    policy_terms: dict[str, Any] | None = None
    premium_payment_terms: dict[str, Any] | None = None
    pricing_available: bool
    pricing_method: str | None = None
    pricing_basis_note: str | None = None
    rating_factors: list[str] = Field(default_factory=list)
    catalogue: CatalogueInfo


class RatingInputsIn(BaseModel):
    age: int | None = Field(default=None, ge=0, le=120)
    gender: Literal["male", "female", "other"] | None = None
    smoker: bool | None = None


class QuoteIn(BaseModel):
    sum_assured: int | None = Field(default=None, gt=0, le=10_000_000_000)
    premium_frequency: Literal["single", "annual", "half_yearly", "quarterly", "monthly"] | None = None
    policy_term: int | None = Field(default=None, gt=0, le=100)
    premium_payment_term: int | None = Field(default=None, gt=0, le=100)
    rating: RatingInputsIn = Field(default_factory=RatingInputsIn)


class QuoteOut(BaseModel):
    quote_type: Literal["indicative"]
    official_quote: Literal[False]
    status: Literal["indicative", "not_available"]
    amount: float | None = None
    amount_before_tax: float | None = None
    tax_amount: float | None = None
    currency: str | None = None
    premium_frequency: str | None = None
    method: str | None = None
    basis_note: str | None = None
    reasons: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    inputs_used: dict[str, Any] = Field(default_factory=dict)
    disclaimer: str


class ProductSelectionIn(QuoteIn):
    product_id: str = Field(pattern=PRODUCT_ID_RE)


def catalogue_info(catalogue: CatalogueFile) -> CatalogueInfo:
    return CatalogueInfo(
        catalogue_id=catalogue.catalogue_id,
        catalogue_version=catalogue.catalogue_version,
        source=catalogue.source,
        is_demo=catalogue.is_demo,
        effective_date=catalogue.effective_date,
    )


def product_detail(product: Product, catalogue: CatalogueFile) -> ProductDetailOut:
    return ProductDetailOut(
        product_id=product.product_id,
        product_name=product.product_name,
        insurer=product.insurer,
        insurance_type=product.insurance_type,
        plan_name=product.plan_name,
        uin=product.uin,
        description=product.description,
        status=product.status,
        entry_age_min=product.entry_age_min,
        entry_age_max=product.entry_age_max,
        sum_assured=product.sum_assured.model_dump(exclude_none=True) if product.sum_assured else None,
        premium_frequencies=(
            [OptionOut(value=v, label=allowed_frequency_label(v)) for v in product.premium_frequencies]
            if product.premium_frequencies
            else None
        ),
        policy_terms=product.policy_terms.model_dump(exclude_none=True) if product.policy_terms else None,
        premium_payment_terms=(
            product.premium_payment_terms.model_dump(exclude_none=True)
            if product.premium_payment_terms
            else None
        ),
        pricing_available=product.pricing is not None,
        pricing_method=product.pricing.method if product.pricing else None,
        pricing_basis_note=product.pricing.basis_note if product.pricing else None,
        rating_factors=list(product.pricing.rating_factors) if product.pricing else [],
        catalogue=catalogue_info(catalogue),
    )
