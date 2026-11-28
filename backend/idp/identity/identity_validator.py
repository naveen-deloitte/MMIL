"""Document-specific validation for Aadhaar and PAN extraction results.

Findings use the same shape as the existing field validations
(``code``, ``severity``, ``message``) plus a ``rule`` identifying the check. A passing format or
checksum check is always reported with the caveat that it does not prove authenticity.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from idp.identity.masking import (
    PAN_HOLDER_CATEGORIES,
    PAN_STRICT_RE,
    compact_identifier,
    is_full_aadhaar_shape,
    is_masked_aadhaar,
    verhoeff_is_valid,
)

AADHAAR_DOCUMENT_TYPE = "aadhaar_card"
PAN_DOCUMENT_TYPE = "pan_card"
IDENTITY_DOCUMENT_TYPES = frozenset({AADHAAR_DOCUMENT_TYPE, PAN_DOCUMENT_TYPE})

NOT_PROOF = "A valid format is not proof that the document is authentic."


def finding(code: str, severity: str, rule: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "rule": rule, "message": message}


def validate_aadhaar_number(raw: str) -> list[dict[str, Any]]:
    """Validate a visible Aadhaar number. Masked numbers are valid, not failures."""
    compact = compact_identifier(raw)
    if is_masked_aadhaar(compact):
        return [
            finding(
                "aadhaar_masked",
                "info",
                "aadhaar_masked_format",
                "Masked Aadhaar number. The full number is not shown on the document.",
            )
        ]
    if len(compact) == 16 and compact.isdigit():
        return [
            finding(
                "aadhaar_format_invalid",
                "error",
                "aadhaar_12_digits",
                "The number has 16 digits. An Aadhaar number has 12; a 16 digit number is a "
                "Virtual ID (VID). Check the original document.",
            )
        ]
    if not is_full_aadhaar_shape(compact):
        return [
            finding(
                "aadhaar_format_invalid",
                "error",
                "aadhaar_12_digits",
                "The Aadhaar number is not twelve digits.",
            )
        ]
    if compact[0] in "01":
        return [
            finding(
                "aadhaar_format_invalid",
                "error",
                "aadhaar_first_digit",
                "An Aadhaar number cannot start with 0 or 1.",
            )
        ]
    if not verhoeff_is_valid(compact):
        return [
            finding(
                "aadhaar_checksum_invalid",
                "error",
                "verhoeff_checksum",
                "The Aadhaar number fails its checksum. It may be misread or incorrect.",
            )
        ]
    return [
        finding(
            "aadhaar_format_valid",
            "info",
            "verhoeff_checksum",
            f"Number structure and checksum are valid. {NOT_PROOF}",
        )
    ]


def validate_pan_number(raw: str) -> list[dict[str, Any]]:
    compact = compact_identifier(raw)
    if not PAN_STRICT_RE.fullmatch(compact):
        return [
            finding(
                "pan_format_invalid",
                "error",
                "pan_structure",
                "A PAN has five letters, four digits and one letter.",
            )
        ]
    results = [
        finding(
            "pan_format_valid",
            "info",
            "pan_structure",
            f"PAN structure is valid. {NOT_PROOF}",
        )
    ]
    if compact[3] not in PAN_HOLDER_CATEGORIES:
        results.append(
            finding(
                "pan_holder_category_unknown",
                "warning",
                "pan_holder_category",
                "The fourth character is not a recognised holder category.",
            )
        )
    return results


def parse_iso_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def validate_date_of_birth(value: Any, *, today: date | None = None) -> list[dict[str, Any]]:
    parsed = parse_iso_date(value)
    today = today or date.today()
    if parsed is None:
        return [finding("date_invalid", "error", "date_format", "The date could not be read.")]
    if parsed > today:
        return [
            finding("date_in_future", "error", "date_not_future", "Date of birth is in the future.")
        ]
    if today.year - parsed.year > 120:
        return [
            finding(
                "date_implausible",
                "warning",
                "date_plausible_age",
                "Date of birth implies an age over 120.",
            )
        ]
    return []


def validate_year_of_birth(value: Any, *, today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.today()
    try:
        year = int(value)
    except (TypeError, ValueError):
        return [finding("year_invalid", "error", "year_format", "The year could not be read.")]
    if year > today.year or year < today.year - 120:
        return [
            finding(
                "year_implausible",
                "error",
                "year_plausible_range",
                "Year of birth is outside a plausible range.",
            )
        ]
    return []


def check_dob_consistency(date_of_birth: Any, year_of_birth: Any) -> list[dict[str, Any]]:
    parsed = parse_iso_date(date_of_birth)
    if parsed is None or year_of_birth in (None, ""):
        return []
    try:
        if int(year_of_birth) != parsed.year:
            return [
                finding(
                    "dob_year_inconsistent",
                    "error",
                    "dob_matches_year_of_birth",
                    "The date of birth and the year of birth on the document disagree.",
                )
            ]
    except (TypeError, ValueError):
        return []
    return []


def aadhaar_completeness(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Return completeness findings for the Aadhaar card as a whole."""
    findings: list[dict[str, Any]] = []
    if not values.get("identity.aadhaar_number"):
        findings.append(
            finding(
                "identity_number_missing",
                "warning",
                "mandatory_field",
                "No Aadhaar number (full or masked) was found.",
            )
        )
    if not values.get("identity.full_name"):
        findings.append(
            finding("name_missing", "warning", "mandatory_field", "No name was found.")
        )
    if not values.get("identity.date_of_birth") and not values.get("identity.year_of_birth"):
        findings.append(
            finding(
                "dob_or_yob_missing",
                "warning",
                "mandatory_field",
                "Neither a date of birth nor a year of birth was found.",
            )
        )
    return findings


def pan_completeness(values: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if not values.get("identity.pan_number"):
        findings.append(
            finding("identity_number_missing",
                "warning", "mandatory_field", "No PAN was found.")
        )
    if not values.get("identity.full_name"):
        findings.append(
            finding("name_missing", "warning", "mandatory_field", "No name was found.")
        )
    if not values.get("identity.date_of_birth"):
        findings.append(
            finding("dob_missing", "warning", "expected_field", "No date of birth was found.")
        )
    return findings
