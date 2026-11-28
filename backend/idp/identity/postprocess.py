"""Post-extraction step for Aadhaar and PAN documents.

Runs after the deterministic ``SchemaExtractor`` and before anything is persisted. While the full
identifier is still in memory it validates the identifier, then replaces every occurrence of the
full number (candidate values, citation excerpts, page text and text blocks) with a masked form.
Nothing that leaves this module contains a full Aadhaar number or PAN.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from typing import Any

from idp.extraction.engine import Citation, ExtractedCandidate
from idp.extraction.text import PageText, TextBlock
from idp.identity.identity_validator import (
    AADHAAR_DOCUMENT_TYPE,
    IDENTITY_DOCUMENT_TYPES,
    PAN_DOCUMENT_TYPE,
    aadhaar_completeness,
    check_dob_consistency,
    finding,
    pan_completeness,
    validate_aadhaar_number,
    validate_date_of_birth,
    validate_pan_number,
    validate_year_of_birth,
)
from idp.identity.masking import (
    PAN_HOLDER_CATEGORIES,
    compact_identifier,
    is_full_aadhaar_shape,
    is_masked_aadhaar,
    mask_aadhaar,
    mask_pan,
    mask_text,
)

_E_AADHAAR_RE = re.compile(r"e-?aadhaar", re.IGNORECASE)


def mask_pages(pages: list[PageText]) -> list[PageText]:
    return [
        replace(
            page,
            text=mask_text(page.text),
            blocks=[
                TextBlock(mask_text(block.text), block.x0, block.y0, block.x1, block.y1)
                for block in page.blocks
            ],
        )
        for page in pages
    ]


def _mask_citation(citation: Citation) -> Citation:
    return replace(citation, excerpt=mask_text(citation.excerpt))


def _with(
    candidate: ExtractedCandidate, extra: list[dict[str, Any]], **changes: Any
) -> ExtractedCandidate:
    return replace(candidate, validations=[*candidate.validations, *extra], **changes)


def finalize_identity_extraction(
    document_type: str,
    candidates: list[ExtractedCandidate],
    pages: list[PageText],
    *,
    today: date | None = None,
) -> tuple[list[ExtractedCandidate], list[PageText]]:
    """Validate, derive and mask. Returns candidates and pages that are safe to persist."""
    if document_type not in IDENTITY_DOCUMENT_TYPES:
        return candidates, pages
    values = {c.field_path: c.normalized_value for c in candidates if c.normalized_value}
    by_path = {c.field_path: c for c in candidates}
    page_text = "\n".join(page.text for page in pages)
    updated: dict[str, ExtractedCandidate] = {}

    if document_type == AADHAAR_DOCUMENT_TYPE:
        number = by_path.get("identity.aadhaar_number")
        if number is not None and number.normalized_value:
            raw = str(number.normalized_value)
            updated[number.field_path] = _with(
                number, validate_aadhaar_number(raw), normalized_value=mask_aadhaar(raw)
            )
        dob = by_path.get("identity.date_of_birth")
        if dob is not None and dob.normalized_value:
            updated[dob.field_path] = _with(dob, validate_date_of_birth(dob.normalized_value, today=today))
        yob = by_path.get("identity.year_of_birth")
        if yob is not None and yob.normalized_value is not None:
            extra = validate_year_of_birth(yob.normalized_value, today=today)
            extra += check_dob_consistency(
                values.get("identity.date_of_birth"), yob.normalized_value
            )
            updated[yob.field_path] = _with(yob, extra)
            if extra and any(f["code"] == "dob_year_inconsistent" for f in extra) and dob:
                updated[dob.field_path] = _with(
                    updated.get(dob.field_path, dob),
                    [f for f in extra if f["code"] == "dob_year_inconsistent"],
                )
        document = by_path.get("document.document_type")
        if document is not None and document.normalized_value:
            variant = "aadhaar_card"
            if _E_AADHAAR_RE.search(page_text):
                variant = "e_aadhaar"
            elif number is not None and number.normalized_value and is_masked_aadhaar(
                str(number.normalized_value)
            ):
                variant = "masked_aadhaar"
            updated[document.field_path] = replace(document, normalized_value=variant)
        qr = by_path.get("document.qr_present")
        if qr is not None and qr.normalized_value:
            updated[qr.field_path] = _with(
                qr,
                [
                    finding(
                        "qr_text_mention_only",
                        "info",
                        "qr_not_decoded",
                        "A QR code is mentioned in the document text. It has not been decoded "
                        "or signature-verified.",
                    )
                ],
            )
        completeness = aadhaar_completeness(values)
    else:
        number = by_path.get("identity.pan_number")
        if number is not None and number.normalized_value:
            raw = str(number.normalized_value)
            updated[number.field_path] = _with(
                number, validate_pan_number(raw), normalized_value=mask_pan(raw)
            )
        category = by_path.get("identity.pan_holder_category")
        if category is not None and category.normalized_value:
            code = str(category.normalized_value).upper()
            label = PAN_HOLDER_CATEGORIES.get(code)
            if label:
                bbox = (number.citations[0].bbox if number and number.citations else None)
                citations = [replace(c, bbox=bbox) for c in category.citations]
                updated[category.field_path] = replace(
                    category, normalized_value=label, citations=citations
                )
        dob = by_path.get("identity.date_of_birth")
        if dob is not None and dob.normalized_value:
            updated[dob.field_path] = _with(dob, validate_date_of_birth(dob.normalized_value, today=today))
        document = by_path.get("document.document_type")
        if document is not None and document.normalized_value:
            updated[document.field_path] = replace(document, normalized_value="pan_card")
        for path in ("document.photograph_present", "document.signature_present"):
            flag = by_path.get(path)
            if flag is not None and flag.normalized_value:
                updated[path] = _with(
                    flag,
                    [
                        finding(
                            "visual_element_label_only",
                            "info",
                            "visual_element_not_inspected",
                            "Based on a printed label only. The image was not inspected.",
                        )
                    ],
                )
        completeness = pan_completeness(values)

    # Document level completeness findings are attached to the identifier (or name) field so
    # they surface in the existing field validation list without creating fake values.
    anchor_path = (
        "identity.aadhaar_number" if document_type == AADHAAR_DOCUMENT_TYPE else "identity.pan_number"
    )
    anchor = updated.get(anchor_path) or by_path.get(anchor_path)
    if anchor is not None:
        existing_codes = {v.get("code") for v in anchor.validations}
        fresh = [f for f in completeness if f["code"] not in existing_codes]
        if fresh:
            updated[anchor_path] = _with(anchor, fresh)

    result: list[ExtractedCandidate] = []
    for candidate in candidates:
        candidate = updated.get(candidate.field_path, candidate)
        literal = candidate.source_literal
        if literal is not None:
            if candidate.field_path == "identity.aadhaar_number":
                literal = (
                    mask_aadhaar(literal)
                    if (is_full_aadhaar_shape(literal) or is_masked_aadhaar(literal))
                    else mask_text(literal)
                )
            elif candidate.field_path == "identity.pan_number":
                literal = mask_pan(compact_identifier(literal))
            else:
                literal = mask_text(literal)
        normalized = candidate.normalized_value
        if isinstance(normalized, str):
            normalized = mask_text(normalized)
        result.append(
            replace(
                candidate,
                source_literal=literal,
                normalized_value=normalized,
                citations=[_mask_citation(c) for c in candidate.citations],
            )
        )
    return result, mask_pages(pages)
