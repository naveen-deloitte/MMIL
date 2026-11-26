from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from idp.schemas import (
    CaseReviewExceptionOut,
    CaseReviewSummaryOut,
    DocumentSummary,
    FieldOut,
    RunSummary,
    ValidationOut,
)

_PROCESSING_STATUSES = {"uploaded", "scanning", "ocr", "extracting"}


def build_case_review_summary(
    *,
    documents: list[DocumentSummary],
    runs: list[RunSummary],
    fields: list[FieldOut],
) -> CaseReviewSummaryOut:
    exceptions: list[CaseReviewExceptionOut] = []
    document_names = {document.id: document.filename for document in documents}
    run_by_document = {run.document_id: run for run in runs}

    conflict_groups = _cross_document_conflicts(fields)
    conflict_field_ids = {
        field.id for group in conflict_groups for field in group["fields"]
    }

    for group in conflict_groups:
        group_fields = group["fields"]
        resolved = all(field.latest_review is not None for field in group_fields)
        filenames = [
            document_names.get(field.document_id, "Source document")
            for field in group_fields
        ]
        exceptions.append(
            CaseReviewExceptionOut(
                id=f"conflict:{group['field_path']}",
                kind="cross_document_conflict",
                category="Cross-document conflict",
                title=f"{group_fields[0].label} differs across documents",
                status="resolved" if resolved else "pending",
                severity="warning",
                field_ids=[field.id for field in group_fields],
                document_ids=list(dict.fromkeys(field.document_id for field in group_fields)),
                message=(
                    "Extracted values differ across uploaded documents. Review each source; "
                    "no value is selected as authoritative. Sources: "
                    + ", ".join(filenames)
                ),
            )
        )

    for field in fields:
        if field.id in conflict_field_ids:
            continue
        validations = [
            finding
            for finding in field.validations
            if finding.code != "auto_accepted"
            and finding.severity in {"error", "warning", "advisory"}
        ]
        if field.review_state == "pending":
            exceptions.append(
                CaseReviewExceptionOut(
                    id=f"field:{field.id}",
                    kind="field",
                    category=_field_category(field, validations),
                    title=f"{field.label} requires review",
                    status="pending",
                    severity="error"
                    if any(finding.severity == "error" for finding in validations)
                    else "warning",
                    field_ids=[field.id],
                    document_ids=[field.document_id],
                    message=_field_message(field, validations),
                )
            )
            continue

        flagged = (
            field.extraction_status == "uncertain"
            or any(finding.severity in {"error", "warning"} for finding in validations)
        )
        if field.latest_review is not None and flagged:
            exceptions.append(
                CaseReviewExceptionOut(
                    id=f"field:{field.id}",
                    kind="field",
                    category=_field_category(field, validations),
                    title=f"{field.label} review completed",
                    status="resolved",
                    severity="info",
                    field_ids=[field.id],
                    document_ids=[field.document_id],
                    message=(
                        f"Reviewed as {field.latest_review.decision.replace('_', ' ')}. "
                        "The original extracted value and citation remain available."
                    ),
                )
            )
            continue

        advisory = next(
            (finding for finding in validations if finding.severity == "advisory"),
            None,
        )
        if advisory is not None:
            exceptions.append(
                CaseReviewExceptionOut(
                    id=f"advisory:{field.id}:{advisory.code}",
                    kind="field",
                    category="Advisory",
                    title=f"{field.label}: {advisory.code.replace('_', ' ')}",
                    status="advisory",
                    severity="warning",
                    field_ids=[field.id],
                    document_ids=[field.document_id],
                    message=advisory.message or "The extraction pipeline recorded an advisory.",
                )
            )

    for document in documents:
        if document.status == "failed":
            code = (
                document.failure_code.replace("_", " ")
                if document.failure_code
                else "unknown error"
            )
            exceptions.append(
                CaseReviewExceptionOut(
                    id=f"document:{document.id}",
                    kind="document",
                    category="Document processing failure",
                    title=f"{document.filename} failed processing",
                    status="pending",
                    severity="error",
                    document_ids=[document.id],
                    message=f"Processing failed: {code}. Retry is available in Document Review.",
                )
            )
        elif document.status == "cancelled":
            exceptions.append(
                CaseReviewExceptionOut(
                    id=f"document:{document.id}",
                    kind="document",
                    category="Document processing",
                    title=f"{document.filename} processing was cancelled",
                    status="pending",
                    severity="warning",
                    document_ids=[document.id],
                    message="This document did not complete processing.",
                )
            )

    exceptions.sort(
        key=lambda item: (
            {"pending": 0, "resolved": 1, "advisory": 2}[item.status],
            item.title.casefold(),
        )
    )
    return CaseReviewSummaryOut(
        open_flags=sum(item.status == "pending" for item in exceptions),
        documents_analysed=sum(
            run.status == "succeeded" for run in run_by_document.values()
        ),
        cross_document_conflicts=len(conflict_groups),
        resolved_flags=sum(item.status == "resolved" for item in exceptions),
        processing_documents=sum(document.status in _PROCESSING_STATUSES for document in documents),
        exceptions=exceptions,
    )


def _cross_document_conflicts(fields: list[FieldOut]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str | None], list[tuple[FieldOut, Any]]] = defaultdict(list)
    for field in fields:
        normalized = _comparable_value(field)
        if normalized is None:
            continue
        grouped[(field.field_path, field.data_type, field.unit)].append((field, normalized))

    conflicts: list[dict[str, Any]] = []
    for key, items in grouped.items():
        field_path = key[0]
        by_document: dict[str, tuple[FieldOut, Any]] = {}
        for field, value in items:
            by_document.setdefault(field.document_id, (field, value))
        sources = list(by_document.values())
        if len(sources) < 2 or len({value for _, value in sources}) < 2:
            continue
        conflicts.append(
            {
                "field_path": field_path,
                "fields": [field for field, _ in sources],
            }
        )
    return conflicts


def _comparable_value(field: FieldOut) -> Any | None:
    if field.extraction_status not in {"found", "uncertain"}:
        return None
    value = field.candidate_value
    if value is None:
        return None
    if field.data_type in {"decimal", "integer"}:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None
        is_fractional_integer = (
            field.data_type == "integer" and number != number.to_integral_value()
        )
        if not number.is_finite() or is_fractional_integer:
            return None
        return ("number", number.normalize())
    if field.data_type == "measurement_pair":
        if not isinstance(value, dict) or set(value) != {"systolic", "diastolic"}:
            return None
        systolic = _decimal_component(value["systolic"])
        diastolic = _decimal_component(value["diastolic"])
        if systolic is None or diastolic is None:
            return None
        return ("measurement_pair", systolic.normalize(), diastolic.normalize())
    if field.data_type == "boolean" and isinstance(value, bool):
        return ("boolean", value)
    if field.data_type == "date" and isinstance(value, str):
        try:
            return ("date", date.fromisoformat(value[:10]))
        except ValueError:
            return None
    return None


def _decimal_component(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _field_category(field: FieldOut, validations: list[ValidationOut]) -> str:
    if any(finding.severity == "error" for finding in validations):
        return "Validation error"
    if any(finding.code == "low_confidence" for finding in validations):
        return "Low confidence"
    if field.extraction_status == "uncertain":
        return "Unclear extracted value"
    return "Review required"


def _field_message(field: FieldOut, validations: list[ValidationOut]) -> str:
    messages = [finding.message for finding in validations if finding.message]
    if messages:
        return " ".join(dict.fromkeys(messages))
    return f"The extraction pipeline marked {field.label} for human review."
