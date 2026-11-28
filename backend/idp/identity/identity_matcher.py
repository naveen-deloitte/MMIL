"""Cross-document matching of KYC, Aadhaar and PAN values.

Matching is deliberately conservative. Only exact and normalized (case, spacing, punctuation,
token order) equality count as a match. Initials and missing name parts return ``review_required``
for a person to decide. Different names are never merged on loose similarity. A missing document
is ``not_available`` and never a mismatch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

MATCH = "match"
NORMALIZED_MATCH = "normalized_match"
REVIEW_REQUIRED = "review_required"
MISMATCH = "mismatch"
NOT_AVAILABLE = "not_available"
NOT_APPLICABLE = "not_applicable"

SOURCES = ("kyc", "aadhaar", "pan")
FIELD_LABELS = {
    "full_name": "Full name",
    "date_of_birth": "Date of birth",
    "gender": "Gender",
    "address": "Address",
    "pan_number": "PAN",
}
# Sources for which a field has no meaning. These are shown as "N/A", not as missing.
NOT_APPLICABLE_SOURCES = {
    "gender": {"pan"},
    "address": {"pan"},
    "pan_number": {"kyc", "aadhaar"},
}
_SEVERITY = {MATCH: 0, NORMALIZED_MATCH: 1, REVIEW_REQUIRED: 2, MISMATCH: 3}


@dataclass(frozen=True)
class SourceValue:
    """One extracted value for one field from one source document."""

    value: Any | None = None
    uncertain: bool = False
    year_of_birth: int | None = None  # Aadhaar cards that print only a year.


def _tokens(value: Any) -> list[str]:
    text = "".join(ch if ch.isalnum() else " " for ch in str(value or "").casefold())
    return text.split()


def _initial_compatible(short: str, other: str) -> bool:
    return short == other or (len(short) == 1 and other.startswith(short))


def compare_names(left: Any, right: Any) -> tuple[str, float, str]:
    if str(left).strip() == str(right).strip():
        return MATCH, 1.0, "Names are identical."
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return NOT_AVAILABLE, 0.0, "A name is empty."
    if a == b:
        return NORMALIZED_MATCH, 0.98, "Names differ only in case, spacing or punctuation."
    if sorted(a) == sorted(b):
        return NORMALIZED_MATCH, 0.95, "Names have the same parts in a different order."
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    remaining = list(longer)
    for token in shorter:
        hit = next((o for o in remaining if _initial_compatible(token, o) or
                    _initial_compatible(o, token)), None)
        if hit is None:
            return MISMATCH, 0.0, "The names contain different words."
        remaining.remove(hit)
    reason = (
        "One name uses initials."
        if len(a) == len(b)
        else "One name has additional or missing name parts."
    )
    return REVIEW_REQUIRED, 0.7, f"{reason} A person must confirm they are the same."


def normalize_date(value: Any) -> str | None:
    text = str(value or "").strip()
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text[:10] if date_format == "%Y-%m-%d" else text, date_format)\
                .date().isoformat()
        except ValueError:
            continue
    return None


def compare_dates(
    left: SourceValue, right: SourceValue
) -> tuple[str, float, str]:
    left_date, right_date = normalize_date(left.value), normalize_date(right.value)
    if left_date and right_date:
        if left_date == right_date:
            same_text = str(left.value).strip() == str(right.value).strip()
            return (
                (MATCH, 1.0, "Dates are identical.")
                if same_text
                else (NORMALIZED_MATCH, 0.99, "Dates are equal after format normalization.")
            )
        return MISMATCH, 0.0, "The dates of birth differ."
    left_year = left.year_of_birth or (int(left_date[:4]) if left_date else None)
    right_year = right.year_of_birth or (int(right_date[:4]) if right_date else None)
    if left_year and right_year:
        if left_year == right_year:
            return (
                REVIEW_REQUIRED,
                0.6,
                "Only the year of birth can be compared. The years agree.",
            )
        return MISMATCH, 0.0, "The years of birth differ."
    return NOT_AVAILABLE, 0.0, "No comparable date was available."


_GENDERS = {
    "male": "male", "m": "male", "man": "male",
    "female": "female", "f": "female", "woman": "female",
    "transgender": "other", "other": "other", "third gender": "other",
}


def compare_gender(left: Any, right: Any) -> tuple[str, float, str]:
    a = _GENDERS.get(" ".join(_tokens(left)))
    b = _GENDERS.get(" ".join(_tokens(right)))
    if a is None or b is None:
        return REVIEW_REQUIRED, 0.4, "A gender value was not recognised."
    if a == b:
        same = str(left).strip() == str(right).strip()
        return (MATCH, 1.0, "Identical.") if same else (NORMALIZED_MATCH, 0.98, "Equivalent.")
    return MISMATCH, 0.0, "The recorded genders differ."


_PIN_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")


def compare_addresses(left: Any, right: Any) -> tuple[str, float, str]:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return NOT_AVAILABLE, 0.0, "An address is empty."
    if a == b:
        same = str(left).strip() == str(right).strip()
        return (MATCH, 1.0, "Identical.") if same else (NORMALIZED_MATCH, 0.97, "Equivalent.")
    pins_a, pins_b = set(_PIN_RE.findall(str(left))), set(_PIN_RE.findall(str(right)))
    if pins_a and pins_b and not pins_a & pins_b:
        return MISMATCH, 0.0, "The PIN codes differ."
    smaller, larger = (set(a), set(b)) if len(set(a)) <= len(set(b)) else (set(b), set(a))
    overlap = len(smaller & larger) / len(smaller)
    if overlap >= 0.8:
        return REVIEW_REQUIRED, 0.7, "Addresses largely overlap but are not identical."
    if overlap < 0.5:
        return MISMATCH, 0.0, "The addresses share little in common."
    return REVIEW_REQUIRED, 0.4, "Addresses partly overlap."


def compare_identifiers(left: Any, right: Any) -> tuple[str, float, str]:
    a = re.sub(r"\s", "", str(left)).upper()
    b = re.sub(r"\s", "", str(right)).upper()
    if a == b:
        return MATCH, 1.0, "Masked identifiers are identical."
    return MISMATCH, 0.0, "The identifiers differ."


def _compare(field: str, left: SourceValue, right: SourceValue) -> tuple[str, float, str]:
    if left.uncertain or right.uncertain:
        return (
            REVIEW_REQUIRED,
            0.3,
            "At least one value was read with uncertainty. A person must confirm it.",
        )
    if field == "full_name":
        return compare_names(left.value, right.value)
    if field == "date_of_birth":
        return compare_dates(left, right)
    if field == "gender":
        return compare_gender(left.value, right.value)
    if field == "address":
        return compare_addresses(left.value, right.value)
    return compare_identifiers(left.value, right.value)


def _present(value: SourceValue | None) -> bool:
    return bool(
        value is not None
        and (value.value not in (None, "") or value.year_of_birth is not None)
    )


def match_identity(
    sources: dict[str, dict[str, SourceValue]],
    *,
    documents_present: dict[str, bool],
) -> list[dict[str, Any]]:
    """Return one comparison row per field. ``sources`` maps source -> field -> value."""
    rows: list[dict[str, Any]] = []
    for field, label in FIELD_LABELS.items():
        inapplicable = NOT_APPLICABLE_SOURCES.get(field, set())
        values = {
            source: sources.get(source, {}).get(field)
            for source in SOURCES
            if source not in inapplicable
        }
        available = {s: v for s, v in values.items() if _present(v)}
        pairs: list[dict[str, Any]] = []
        names = list(available)
        for i, first in enumerate(names):
            for second in names[i + 1 :]:
                status, confidence, reason = _compare(field, available[first], available[second])
                pairs.append(
                    {
                        "left": first,
                        "right": second,
                        "status": status,
                        "confidence": confidence,
                        "reason": reason,
                    }
                )
        if field == "pan_number":
            status, confidence, reason = (
                NOT_APPLICABLE,
                0.0,
                "No PAN was supplied on the KYC form to compare with.",
            )
        elif not pairs:
            status, confidence, reason = (
                NOT_AVAILABLE,
                0.0,
                "At least two documents with this value are needed to compare.",
            )
        else:
            worst = max(pairs, key=lambda p: _SEVERITY.get(p["status"], 0))
            usable = [p for p in pairs if p["status"] in _SEVERITY]
            if not usable:
                status, confidence, reason = NOT_AVAILABLE, 0.0, worst["reason"]
            else:
                worst = max(usable, key=lambda p: _SEVERITY[p["status"]])
                status = worst["status"]
                confidence = min(p["confidence"] for p in usable)
                reason = worst["reason"]

        def display(source: str, _values=values, _field=field) -> Any:
            if source in inapplicable:
                return None
            item = _values.get(source)
            if item is None:
                return None
            if item.value not in (None, ""):
                return item.value
            return f"Year {item.year_of_birth}" if item.year_of_birth else None

        rows.append(
            {
                "field": field,
                "label": label,
                "kyc_value": display("kyc"),
                "aadhaar_value": display("aadhaar"),
                "pan_value": display("pan"),
                "match_status": status,
                "confidence": round(confidence, 2),
                "explanation": reason,
                "pairs": pairs,
                "not_applicable_sources": sorted(inapplicable),
                "missing_sources": [
                    s
                    for s in SOURCES
                    if s not in inapplicable and not documents_present.get(s, False)
                ],
            }
        )
    return rows


def overall_match_status(rows: list[dict[str, Any]]) -> str:
    statuses = [r["match_status"] for r in rows if r["field"] != "pan_number"]
    if any(s == MISMATCH for s in statuses):
        return MISMATCH
    if any(s == REVIEW_REQUIRED for s in statuses):
        return REVIEW_REQUIRED
    if any(s in (MATCH, NORMALIZED_MATCH) for s in statuses):
        return MATCH
    return NOT_AVAILABLE
