"""Decide which extracted fields need HITL review, which carry advisory notes, and which are clean.

Three levels:

* **Critical -> HITL (``pending``).** Blocks completion until a person decides.
  - name mismatch (KYC applicant vs signed/declared names, or vs the case's life assured);
  - conflicting values for the same field (status ``uncertain``);
  - a validation error (invalid or unreadable value);
  - confidence below ``LOW_CONFIDENCE_THRESHOLD``.
* **Advisory (``severity: advisory``).** The value is auto-accepted (or stays "not found"), but a
  note is stored on the field and listed for the reviewer. Does not block completion.
* **Clean.** Auto-accepted with an ``auto_accepted`` marker so the audit trail shows the system,
  not a person, accepted it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

LOW_CONFIDENCE_THRESHOLD = 0.6
# Native PDF text scores about 0.78, so this band only catches weaker OCR reads.
MEDIUM_CONFIDENCE_THRESHOLD = 0.75
SIGNATURE_MAX_AGE = timedelta(days=365)
MEDICAL_REPORT_MAX_AGE = timedelta(days=180)

KYC_DOCUMENT_TYPE = "kyc_individual"
MEDICAL_DOCUMENT_TYPE = "medical_report"
KYC_APPLICANT_NAME_PATHS = ("identity.surname", "identity.first_name", "identity.other_names")
KYC_SIGNED_NAME_PATHS = (
    "consent.declaration_name",
    "consent.privacy_name",
    "consent.marketing_name",
)
KYC_SIGNATURE_DATE_PATHS = (
    "consent.signature_date",
    "consent.privacy_signature_date",
    "consent.marketing_signature_date",
)

# Not mandatory, but their absence is worth a reviewer's attention.
RECOMMENDED_FIELDS: dict[str, tuple[str, ...]] = {
    KYC_DOCUMENT_TYPE: (
        "identity.date_of_birth",
        "contact.email",
        "contact.telephone",
        "contact.residential_address",
        "bank_details.bank_name",
        "bank_details.account_number",
        "consent.signature_date",
        "consent.declaration_name",
        "contact.next_of_kin_1_name",
    ),
    MEDICAL_DOCUMENT_TYPE: (
        "report.observed_date",
        "observations.blood_pressure",
        "observations.pulse_bpm",
    ),
}

AUTO_ACCEPTED = {"code": "auto_accepted", "severity": "info"}
ADVISORY = "advisory"


@dataclass(frozen=True)
class ReviewInput:
    field_path: str
    value: Any
    status: str
    confidence: float | None
    validations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ReviewOutcome:
    state: str
    """``pending``, ``accepted`` or ``not_reviewable``."""
    added_validations: list[dict[str, Any]]


def _advisory(code: str, message: str) -> dict[str, Any]:
    return {"code": code, "severity": ADVISORY, "message": message}


def _name_tokens(value: Any) -> list[str]:
    text = "".join(ch if ch.isalnum() else " " for ch in str(value or "").casefold())
    return text.split()


def _first_name_matches(first: list[str], tokens: list[str]) -> bool:
    return first[0] in tokens or any(len(t) == 1 and t == first[0][0] for t in tokens)


def _kyc_name_checks(
    values: dict[str, Any], case_applicant_name: str | None
) -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(critical, advisory)`` maps of ``{field_path: message}`` for name checks."""
    surname = _name_tokens(values.get("identity.surname"))
    first = _name_tokens(values.get("identity.first_name"))
    if not surname or not first:
        return {}, {}
    applicant_paths = [p for p in KYC_APPLICANT_NAME_PATHS if values.get(p)]
    form_tokens = set(surname) | set(first) | set(_name_tokens(values.get("identity.other_names")))
    critical: dict[str, str] = {}
    advisory: dict[str, str] = {}

    for path in KYC_SIGNED_NAME_PATHS:
        signed = _name_tokens(values.get(path))
        if not signed:
            continue
        if not (all(t in signed for t in surname) and _first_name_matches(first, signed)):
            message = "Applicant name differs from a signed or declared name on the form."
            critical[path] = message
            for applicant_path in applicant_paths:
                critical.setdefault(applicant_path, message)
        elif set(signed) != form_tokens:
            advisory[path] = (
                "Signed name matches the applicant but is written differently "
                "(initial, missing or extra middle name)."
            )

    case_tokens = set(_name_tokens(case_applicant_name))
    if case_tokens:
        if not form_tokens & case_tokens:
            message = "Applicant name on the form does not match the case's life assured."
            for applicant_path in applicant_paths:
                critical[applicant_path] = message
        elif not case_tokens <= form_tokens:
            for applicant_path in applicant_paths:
                advisory.setdefault(
                    applicant_path,
                    "Applicant name only partly matches the case's life assured.",
                )
    return critical, advisory


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _date_advisories(
    values: dict[str, Any], document_type: str, today: date
) -> dict[str, dict[str, Any]]:
    notes: dict[str, dict[str, Any]] = {}
    if document_type == KYC_DOCUMENT_TYPE:
        for path in KYC_SIGNATURE_DATE_PATHS:
            signed_on = _parse_date(values.get(path))
            if signed_on is None:
                continue
            if signed_on > today:
                notes[path] = _advisory("date_in_future", "Signature date is in the future.")
            elif today - signed_on > SIGNATURE_MAX_AGE:
                notes[path] = _advisory("signature_date_old", "Form was signed over a year ago.")
    if document_type == MEDICAL_DOCUMENT_TYPE:
        observed = _parse_date(values.get("report.observed_date"))
        if observed is not None:
            if observed > today:
                notes["report.observed_date"] = _advisory(
                    "date_in_future", "Report date is in the future."
                )
            elif today - observed > MEDICAL_REPORT_MAX_AGE:
                notes["report.observed_date"] = _advisory(
                    "report_date_old", "Medical report is older than six months."
                )
    return notes


def decide_review_states(
    inputs: Iterable[ReviewInput],
    *,
    document_type: str,
    case_applicant_name: str | None = None,
    today: date | None = None,
) -> dict[str, ReviewOutcome]:
    items = list(inputs)
    values = {item.field_path: item.value for item in items if item.value not in (None, "")}
    if document_type == KYC_DOCUMENT_TYPE:
        name_critical, name_advisory = _kyc_name_checks(values, case_applicant_name)
    else:
        name_critical, name_advisory = {}, {}
    date_notes = _date_advisories(values, document_type, today or date.today())
    recommended = set(RECOMMENDED_FIELDS.get(document_type, ()))

    outcomes: dict[str, ReviewOutcome] = {}
    for item in items:
        if item.value is None:
            # Nothing to approve. Missing recommended fields still get an advisory note;
            # missing required fields already carry ``required_field_missing``.
            notes = []
            if item.field_path in recommended and item.status == "not_found":
                notes.append(
                    _advisory("recommended_field_missing", "Expected field was not found.")
                )
            outcomes[item.field_path] = ReviewOutcome("not_reviewable", notes)
            continue

        added: list[dict[str, Any]] = []
        if item.field_path in name_critical:
            added.append(
                {
                    "code": "name_mismatch",
                    "severity": "error",
                    "message": name_critical[item.field_path],
                }
            )
        low_confidence = item.confidence is not None and item.confidence < LOW_CONFIDENCE_THRESHOLD
        if low_confidence:
            added.append({"code": "low_confidence", "severity": "warning"})
        has_error = any(v.get("severity") == "error" for v in [*item.validations, *added])
        if has_error or item.status == "uncertain" or low_confidence:
            outcomes[item.field_path] = ReviewOutcome("pending", added)
            continue

        if item.field_path in name_advisory:
            added.append(_advisory("name_variation", name_advisory[item.field_path]))
        if item.confidence is not None and item.confidence < MEDIUM_CONFIDENCE_THRESHOLD:
            added.append(
                _advisory("medium_confidence", "Read with moderate confidence; spot-check it.")
            )
        if item.field_path in date_notes:
            added.append(date_notes[item.field_path])
        outcomes[item.field_path] = ReviewOutcome("accepted", [*added, dict(AUTO_ACCEPTED)])
    return outcomes
