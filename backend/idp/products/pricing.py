"""Indicative premium calculation from configured pricing rules.

The result is always labelled ``indicative``. It is never an official insurer quote, which must
come from the insurer's own quotation system. When a required input or a configured rate is
missing, the premium is reported as not available with the reason, rather than estimated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from idp.products.catalogue import FixedPremium, Product, RateRow

QUOTE_DISCLAIMER = (
    "Indicative premium calculated from the configured product catalogue. It is not an official "
    "insurer quote. Final premium is set by the insurer after underwriting."
)


@dataclass
class QuoteInputs:
    sum_assured: int | None = None
    premium_frequency: str | None = None
    policy_term: int | None = None
    premium_payment_term: int | None = None
    age: int | None = None
    gender: str | None = None
    smoker: bool | None = None


@dataclass
class QuoteResult:
    status: str  # "indicative" | "not_available"
    amount: float | None = None
    amount_before_tax: float | None = None
    tax_amount: float | None = None
    currency: str | None = None
    premium_frequency: str | None = None
    method: str | None = None
    basis_note: str | None = None
    reasons: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    inputs_used: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "quote_type": "indicative",
            "official_quote": False,
            "status": self.status,
            "amount": self.amount,
            "amount_before_tax": self.amount_before_tax,
            "tax_amount": self.tax_amount,
            "currency": self.currency,
            "premium_frequency": self.premium_frequency,
            "method": self.method,
            "basis_note": self.basis_note,
            "reasons": list(self.reasons),
            "missing_inputs": list(self.missing_inputs),
            "inputs_used": dict(self.inputs_used),
            "disclaimer": QUOTE_DISCLAIMER,
        }


def validate_selection(product: Product, inputs: QuoteInputs) -> list[str]:
    """Return messages for selections outside the product's configured limits."""
    errors: list[str] = []
    if inputs.sum_assured is not None:
        if product.sum_assured is None:
            errors.append("This product has no configured sum assured.")
        elif not product.sum_assured.permits(inputs.sum_assured):
            errors.append("The sum assured is not one of the permitted options.")
    if inputs.premium_frequency is not None and (
        product.premium_frequencies is None or inputs.premium_frequency not in product.premium_frequencies
    ):
        errors.append("The premium frequency is not offered for this product.")
    if inputs.policy_term is not None and (
        product.policy_terms is None or not product.policy_terms.permits(inputs.policy_term)
    ):
        errors.append("The policy term is not permitted for this product.")
    if inputs.premium_payment_term is not None:
        if product.premium_payment_terms is None or not product.premium_payment_terms.permits(
            inputs.premium_payment_term, policy_term=inputs.policy_term
        ):
            errors.append("The premium payment term is not permitted for this product.")
        elif inputs.policy_term is not None and inputs.premium_payment_term > inputs.policy_term:
            errors.append("The premium payment term cannot exceed the policy term.")
    if inputs.age is not None:
        if product.entry_age_min is not None and inputs.age < product.entry_age_min:
            errors.append("The applicant is below the product's minimum entry age.")
        if product.entry_age_max is not None and inputs.age > product.entry_age_max:
            errors.append("The applicant is above the product's maximum entry age.")
    return errors


def _matching_rates(rows: list[RateRow], inputs: QuoteInputs) -> list[RateRow]:
    matches = []
    for row in rows:
        if inputs.age is None or not row.age_min <= inputs.age <= row.age_max:
            continue
        if row.gender is not None and row.gender != inputs.gender:
            continue
        if row.smoker is not None and row.smoker != inputs.smoker:
            continue
        if row.policy_term is not None and row.policy_term != inputs.policy_term:
            continue
        matches.append(row)
    return matches


def _fixed_match(rows: list[FixedPremium], inputs: QuoteInputs) -> list[FixedPremium]:
    return [
        row
        for row in rows
        if row.sum_assured == inputs.sum_assured
        and row.premium_frequency == inputs.premium_frequency
        and (row.policy_term is None or row.policy_term == inputs.policy_term)
    ]


def calculate_quote(product: Product, inputs: QuoteInputs) -> QuoteResult:
    currency = product.sum_assured.currency if product.sum_assured else None
    pricing = product.pricing
    if pricing is None:
        return QuoteResult(
            status="not_available",
            currency=currency,
            premium_frequency=inputs.premium_frequency,
            reasons=["No pricing rules are configured for this product. An insurer quote is required."],
        )
    result = QuoteResult(
        status="not_available",
        currency=currency,
        premium_frequency=inputs.premium_frequency,
        method=pricing.method,
        basis_note=pricing.basis_note,
    )
    errors = validate_selection(product, inputs)
    if errors:
        result.reasons = errors
        return result

    required = ["sum_assured", "premium_frequency", *pricing.rating_factors]
    missing = [name for name in dict.fromkeys(required) if getattr(inputs, name) is None]
    if missing:
        result.missing_inputs = missing
        result.reasons = ["Enter the missing inputs to calculate an indicative premium."]
        return result
    result.inputs_used = {
        name: getattr(inputs, name) for name in dict.fromkeys(required)
    }

    if pricing.method == "fixed_premium_table":
        rows = _fixed_match(pricing.premiums or [], inputs)
        if len(rows) != 1:
            result.reasons = [
                "No configured premium for this combination."
                if not rows
                else "More than one configured premium matches. The catalogue needs correcting."
            ]
            return result
        before_tax = rows[0].amount
    else:
        rates = _matching_rates(pricing.rate_table or [], inputs)
        if len(rates) != 1:
            result.reasons = [
                "No configured rate for these applicant details."
                if not rates
                else "More than one configured rate matches. The catalogue needs correcting."
            ]
            return result
        factor = (pricing.frequency_factors or {}).get(inputs.premium_frequency)  # type: ignore[arg-type]
        if factor is None:
            result.reasons = ["No configured factor for this premium frequency."]
            return result
        assert inputs.sum_assured is not None
        before_tax = inputs.sum_assured / 1000 * rates[0].rate * factor

    tax = before_tax * pricing.tax_rate if pricing.tax_rate else 0.0
    digits = pricing.rounding_decimals
    result.status = "indicative"
    result.amount_before_tax = round(before_tax, digits)
    result.tax_amount = round(tax, digits) if pricing.tax_rate is not None else None
    result.amount = round(before_tax + tax, digits)
    return result
