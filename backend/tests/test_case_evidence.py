from __future__ import annotations

from types import SimpleNamespace

from idp.services.case_evidence import build_case_review_summary


def field(
    field_id: str,
    document_id: str,
    value: object,
    *,
    field_path: str = "observations.bmi",
    data_type: str = "decimal",
    unit: str | None = "kg/m2",
    review_state: str = "accepted",
    latest_review: object | None = None,
    extraction_status: str = "found",
    validations: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=field_id,
        document_id=document_id,
        field_path=field_path,
        label="BMI",
        data_type=data_type,
        unit=unit,
        candidate_value=value,
        extraction_status=extraction_status,
        review_state=review_state,
        latest_review=latest_review,
        validations=validations or [],
    )


def document(document_id: str, status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        filename=f"{document_id}.pdf",
        status=status,
        failure_code=None,
    )


def test_conflicts_require_same_path_type_and_exact_unit_and_never_choose_a_value() -> None:
    fields = [
        field("bmi-a", "doc-a", 26.1),
        field("bmi-b", "doc-b", "29.0"),
        field("bmi-different-unit", "doc-c", 27.0, unit=""),
        field("pressure-a", "doc-a", 120, field_path="observations.pressure", unit="mmHg"),
        field(
            "pressure-b",
            "doc-b",
            130,
            field_path="observations.pressure",
            data_type="integer",
            unit="mmHg",
        ),
    ]

    summary = build_case_review_summary(
        documents=[document("doc-a"), document("doc-b"), document("doc-c")],
        runs=[],
        fields=fields,
    )

    assert summary.cross_document_conflicts == 1
    conflict = next(item for item in summary.exceptions if item.kind == "cross_document_conflict")
    assert conflict.field_ids == ["bmi-a", "bmi-b"]
    assert "no value is selected as authoritative" in conflict.message


def test_summary_includes_processing_failures_pending_fields_and_resolved_flags() -> None:
    reviewed = SimpleNamespace(decision="corrected")
    fields = [
        field(
            "resolved-field",
            "doc-complete",
            26.1,
            review_state="corrected",
            latest_review=reviewed,
            extraction_status="uncertain",
            validations=[SimpleNamespace(code="low_confidence", severity="warning", message=None)],
        ),
        field(
            "pending-field",
            "doc-complete",
            None,
            review_state="pending",
            extraction_status="not_found",
            validations=[
                SimpleNamespace(
                    code="required_field_missing",
                    severity="error",
                    message="Required field is missing.",
                )
            ],
        ),
    ]

    summary = build_case_review_summary(
        documents=[
            document("doc-complete"),
            document("doc-failed", "failed"),
            document("doc-processing", "ocr"),
        ],
        runs=[SimpleNamespace(document_id="doc-complete", status="succeeded")],
        fields=fields,
    )

    assert summary.documents_analysed == 1
    assert summary.processing_documents == 1
    assert summary.open_flags == 2
    assert summary.resolved_flags == 1
    assert {item.status for item in summary.exceptions} == {"pending", "resolved"}
    assert any(item.kind == "document" and item.status == "pending" for item in summary.exceptions)


def test_advisory_validation_is_separate_from_open_review_flags() -> None:
    advisory_field = field(
        "advisory-field",
        "doc-a",
        "Example",
        data_type="text",
        unit=None,
        validations=[
            SimpleNamespace(
                code="not_relevant",
                severity="advisory",
                message="This item is informational.",
            )
        ],
    )

    summary = build_case_review_summary(
        documents=[document("doc-a")],
        runs=[],
        fields=[advisory_field],
    )

    assert summary.open_flags == 0
    assert summary.exceptions[0].status == "advisory"
    assert summary.exceptions[0].message == "This item is informational."
