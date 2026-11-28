"""Masking and structural validation helpers for Aadhaar and PAN identifiers.

Full identifiers exist only in memory while a document is processed. Everything that is stored,
returned by the API, or written to a log goes through the masking helpers below.

Structural validity (format, Verhoeff checksum) is never proof of authenticity.
"""

from __future__ import annotations

import re

AADHAAR_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?<!\d )(\d{4})([ \t]?)(\d{4})([ \t]?)(\d{4})(?![ \t]?\d)(?![A-Za-z])"
)
# Used only for masking free text, never for extraction. Covers 16 digit Virtual IDs and OCR
# output where a separator was misread (``1234:5678 9012``). Dates use "/" and are not matched.
_SEP = r"[ \t:.\-]?"
_LONG_ID_MASK_RE = re.compile(
    rf"(?<![A-Za-z0-9])\d{{4}}{_SEP}\d{{4}}{_SEP}\d{{4}}{_SEP}(\d{{4}})(?!{_SEP}\d)"
)
_DIGIT_RUN_RE = re.compile(r"(?<!\d)\d{8,}(?!\d)")
_ID_MASK_RE = re.compile(rf"(?<![A-Za-z0-9])(?<!\d )\d{{4}}{_SEP}\d{{4}}{_SEP}(\d{{4}})(?!{_SEP}\d)")
PAN_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{5})(\d{4})([A-Z])(?![A-Za-z0-9])")
PAN_STRICT_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
MASKED_AADHAAR_RE = re.compile(r"^[Xx*]{4}[ ]?[Xx*]{4}[ ]?\d{4}$")
MASKED_AADHAAR_COMPACT_RE = re.compile(r"^X{8}\d{4}$")

PAN_HOLDER_CATEGORIES = {
    "P": "Individual",
    "C": "Company",
    "H": "Hindu Undivided Family",
    "F": "Firm or Limited Liability Partnership",
    "A": "Association of Persons",
    "T": "Trust",
    "B": "Body of Individuals",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
    "G": "Government",
}

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def verhoeff_is_valid(number: str) -> bool:
    """Return True when ``number`` (digits only) satisfies the Verhoeff checksum."""
    if not number.isdigit():
        return False
    checksum = 0
    for index, char in enumerate(reversed(number)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[index % 8][int(char)]]
    return checksum == 0


def verhoeff_generate(number: str) -> str:
    """Return the Verhoeff check digit for ``number``. Used by tests to build fictional values."""
    checksum = 0
    for index, char in enumerate(reversed(number)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[(index + 1) % 8][int(char)]]
    return str(_VERHOEFF_INV[checksum])


def compact_identifier(value: str) -> str:
    return re.sub(r"[\s\-]", "", value).upper().replace("*", "X")


def is_masked_aadhaar(value: str) -> bool:
    return bool(MASKED_AADHAAR_COMPACT_RE.fullmatch(compact_identifier(value)))


def is_full_aadhaar_shape(value: str) -> bool:
    compact = compact_identifier(value)
    return len(compact) == 12 and compact.isdigit()


def mask_aadhaar(value: str) -> str:
    """Return ``XXXX XXXX 1234``. A 16 digit value (VID shape) keeps its length."""
    compact = compact_identifier(value)
    if len(compact) == 16:
        return f"XXXX XXXX XXXX {compact[-4:]}"
    return f"XXXX XXXX {compact[-4:]}"


def mask_pan(value: str) -> str:
    """Return ``XXXXXX234F``-style output: the last four characters stay visible."""
    compact = compact_identifier(value)
    if len(compact) < 5:
        return "X" * len(compact)
    return "X" * (len(compact) - 4) + compact[-4:]


def mask_text(text: str) -> str:
    """Mask every Aadhaar-shaped or PAN-shaped identifier inside free text."""
    text = _LONG_ID_MASK_RE.sub(lambda m: f"XXXX XXXX XXXX {m.group(1)}", text)
    text = _ID_MASK_RE.sub(lambda m: f"XXXX XXXX {m.group(1)}", text)
    # Any remaining run of 8+ digits (OCR fragments of an identifier) keeps only its last four.
    text = _DIGIT_RUN_RE.sub(lambda m: "X" * (len(m.group(0)) - 4) + m.group(0)[-4:], text)
    return PAN_NUMBER_RE.sub(lambda m: mask_pan(m.group(0)), text)


def masked_identifier(value: str | None, *, kind: str) -> str | None:
    if not value:
        return None
    compact = compact_identifier(value)
    if kind == "aadhaar":
        return mask_aadhaar(compact)
    return mask_pan(compact)


IDENTIFIER_FIELD_PATHS = frozenset({"identity.aadhaar_number", "identity.pan_number"})


def mask_identifier_correction(field_path: str, value: str) -> str:
    """Mask a reviewer-entered identifier so a corrected value never stores the full number."""
    if field_path == "identity.aadhaar_number":
        compact = compact_identifier(value)
        if not (is_full_aadhaar_shape(compact) or is_masked_aadhaar(compact)):
            raise ValueError("invalid Aadhaar number")
        return mask_aadhaar(compact)
    compact = compact_identifier(value)
    if not (PAN_STRICT_RE.fullmatch(compact) or re.fullmatch(r"X{4,6}\d{0,4}[A-Z]?", compact)):
        raise ValueError("invalid PAN")
    return mask_pan(compact)
