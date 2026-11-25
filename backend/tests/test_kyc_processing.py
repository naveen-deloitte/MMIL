from __future__ import annotations

from pathlib import Path

import pymupdf
from fastapi.testclient import TestClient

from idp.document_types import DocumentTypeRegistry
from idp.extraction.providers import ProviderResponse
from idp.services.processing import ProcessingService

ROOT = Path(__file__).resolve().parents[2]
CASE_ID = "Dummy-Dummy-29495"


def _filled_kyc_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Individual KYC Form")
    values = [
        ("Surname", "Sample"),
        ("First Name", "Applicant"),
        ("Bank Name", "Example Bank"),
        ("Account Number", "001234567890"),
        ("BVN", "12345678901"),
        ("Name", "Next of Kin One"),
        ("Name_2", "Next of Kin Two"),
    ]
    for index, (name, value) in enumerate(values):
        widget = pymupdf.Widget()
        widget.field_name = name
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        widget.rect = pymupdf.Rect(72, 100 + index * 35, 250, 125 + index * 35)
        widget.field_value = value
        page.add_widget(widget)
        widget.update()
    for index, name in enumerate(("Check Box16", "Check Box3")):
        widget = pymupdf.Widget()
        widget.field_name = name
        widget.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
        widget.rect = pymupdf.Rect(300, 100 + index * 35, 320, 120 + index * 35)
        widget.field_value = "Yes"
        page.add_widget(widget)
        widget.update()
    content = document.tobytes()
    document.close()
    return content


def test_catalog_loads_medical_and_kyc_contracts() -> None:
    catalog = DocumentTypeRegistry.load_catalog(
        ROOT / "config" / "document-types" / "medical-report.v1.json"
    )

    assert catalog.for_type("medical_report").definition.document_type == "medical_report"
    kyc = catalog.for_type("kyc_individual").definition
    assert kyc.display_name == "Individual KYC form"
    assert kyc.extraction.strategy == "deterministic_only"
    assert kyc.additional_facts.enabled is False


def test_kyc_upload_extracts_filled_pdf_form_fields_locally(
    client: TestClient,
    app,
) -> None:
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/documents",
        headers={"Idempotency-Key": "kyc-upload-test-001"},
        files={"file": ("kyc-form.pdf", _filled_kyc_pdf(), "application/pdf")},
        data={"document_type": "kyc_individual"},
    )
    assert response.status_code == 202, response.text
    uploaded = response.json()["document"]
    assert uploaded["document_type"] == "kyc_individual"

    class ExternalProviderMustNotRun:
        name = "openai-compatible"
        model_version = "must-not-run"

        def extract(self, **_kwargs) -> ProviderResponse:
            raise AssertionError("KYC data must not be sent to an external provider")

    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
        provider=ExternalProviderMustNotRun(),
    )
    assert service.process_next() == uploaded["job_id"]

    workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    run = next(run for run in workspace["runs"] if run["document_id"] == uploaded["id"])
    assert run["provider"] == "deterministic-local"
    assert run["ai_analysis"] is None

    fields = {
        field["field_path"]: field
        for field in workspace["fields"]
        if field["document_id"] == uploaded["id"]
    }
    assert fields["identity.surname"]["candidate_value"] == "Sample"
    assert fields["identity.first_name"]["candidate_value"] == "Applicant"
    assert fields["bank_details.account_number"]["candidate_value"] == "001234567890"
    assert fields["bank_details.bvn"]["candidate_value"] == "12345678901"
    assert fields["contact.next_of_kin_1_name"]["candidate_value"] == "Next of Kin One"
    assert fields["contact.next_of_kin_2_name"]["candidate_value"] == "Next of Kin Two"
    assert fields["identity.gender"]["candidate_value"] == "Male"
    assert fields["consent.direct_marketing"]["candidate_value"] == "Yes"
    assert fields["identity.surname"]["citations"][0]["excerpt"] == "Surname: Sample"
