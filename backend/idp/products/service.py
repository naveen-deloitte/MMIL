"""Resolve a case's product selection into persisted policy details."""

from __future__ import annotations

from typing import Any

from idp.errors import AppError
from idp.products.catalogue import POLICY_TERM_KEYWORD, Product, ProductCatalogue, TermRange
from idp.products.pricing import QuoteInputs, calculate_quote, validate_selection
from idp.products.schemas import ProductSelectionIn, QuoteIn, catalogue_info


def _single_option(options: list[Any] | None) -> Any | None:
    if options and len(options) == 1:
        return options[0]
    return None


def _single_term(terms: TermRange | None, policy_term: int | None) -> int | None:
    if terms is None or terms.options is None or len(terms.options) != 1:
        return None
    only = terms.options[0]
    return policy_term if only == POLICY_TERM_KEYWORD else only  # type: ignore[return-value]


def quote_inputs(product: Product, payload: QuoteIn) -> QuoteInputs:
    """Build quote inputs, filling a selection only when the product permits exactly one value."""
    sum_assured = payload.sum_assured
    if sum_assured is None and product.sum_assured is not None:
        sum_assured = _single_option(product.sum_assured.options)
    frequency = payload.premium_frequency or _single_option(product.premium_frequencies)
    policy_term = payload.policy_term or _single_term(product.policy_terms, None)
    payment_term = payload.premium_payment_term or _single_term(
        product.premium_payment_terms, policy_term
    )
    return QuoteInputs(
        sum_assured=sum_assured,
        premium_frequency=frequency,
        policy_term=policy_term,
        premium_payment_term=payment_term,
        age=payload.rating.age,
        gender=payload.rating.gender,
        smoker=payload.rating.smoker,
    )


def find_product(catalogue: ProductCatalogue, product_id: str):
    found = catalogue.get(product_id)
    if found is None:
        raise AppError(
            404, "product_not_found", "Product not found", "The product is not in the catalogue."
        )
    return found


def resolve_case_product(
    catalogue: ProductCatalogue, selection: ProductSelectionIn
) -> tuple[Product, dict[str, Any]]:
    """Validate a selection against the catalogue and return the snapshot stored on the case."""
    product, catalogue_file = find_product(catalogue, selection.product_id)
    if product.status != "active":
        raise AppError(
            422,
            "product_withdrawn",
            "Product withdrawn",
            "This product is no longer offered. Choose another product.",
        )
    inputs = quote_inputs(product, selection)
    errors = validate_selection(product, inputs)
    if errors:
        raise AppError(422, "product_selection_invalid", "Invalid product selection", " ".join(errors))
    quote = calculate_quote(product, inputs)
    details = {
        "catalogue": catalogue_info(catalogue_file).model_dump(),
        "product_id": product.product_id,
        "product_name": product.product_name,
        "insurer": product.insurer,
        "insurance_type": product.insurance_type,
        "plan_name": product.plan_name,
        "uin": product.uin,
        "currency": product.sum_assured.currency if product.sum_assured else None,
        "sum_assured": inputs.sum_assured,
        "premium_frequency": inputs.premium_frequency,
        "policy_term": inputs.policy_term,
        "premium_payment_term": inputs.premium_payment_term,
        "rating_inputs": {
            "age": inputs.age,
            "gender": inputs.gender,
            "smoker": inputs.smoker,
        },
        "indicative_quote": quote.as_dict(),
    }
    return product, details


def requote_case_product(
    catalogue: ProductCatalogue,
    policy_details: dict[str, Any],
    rating: dict[str, Any],
    *,
    actor: str,
    when: str,
) -> dict[str, Any]:
    """Recalculate the proposed premium for the case's saved product selection.

    The product, sum assured, frequency and terms stay as originally selected. Only missing
    applicant rating inputs may be supplied. The previous quote is kept in ``proposal_history``.
    """
    if not policy_details or not policy_details.get("product_id"):
        raise AppError(
            409,
            "case_has_no_catalogue_product",
            "No catalogue product",
            "This case was created without a catalogue product, so there is nothing to price.",
        )
    saved_rating = dict(policy_details.get("rating_inputs") or {})
    changed = {
        key: value
        for key, value in rating.items()
        if value is not None and saved_rating.get(key) not in (None, value)
    }
    if changed:
        raise AppError(
            422,
            "rating_input_already_recorded",
            "Applicant detail already recorded",
            "Only missing applicant details can be added; recorded details cannot be changed here.",
        )
    merged = {
        key: saved_rating.get(key) if saved_rating.get(key) is not None else rating.get(key)
        for key in ("age", "gender", "smoker")
    }
    selection = ProductSelectionIn(
        product_id=policy_details["product_id"],
        sum_assured=policy_details.get("sum_assured"),
        premium_frequency=policy_details.get("premium_frequency"),
        policy_term=policy_details.get("policy_term"),
        premium_payment_term=policy_details.get("premium_payment_term"),
        rating={k: v for k, v in merged.items() if v is not None},
    )
    _, details = resolve_case_product(catalogue, selection)
    history = list(policy_details.get("proposal_history") or [])
    history.append(
        {
            "replaced_at": when,
            "replaced_by": actor,
            "indicative_quote": policy_details.get("indicative_quote"),
            "rating_inputs": policy_details.get("rating_inputs"),
            "catalogue": policy_details.get("catalogue"),
        }
    )
    # Selected cover and terms are carried over unchanged from the original selection.
    for key in ("sum_assured", "premium_frequency", "policy_term", "premium_payment_term"):
        details[key] = policy_details.get(key)
    details["proposal_history"] = history
    details["requoted_at"] = when
    details["requoted_by"] = actor
    return details
