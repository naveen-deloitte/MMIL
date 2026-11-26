from __future__ import annotations

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import select

from idp.errors import ProcessingError
from idp.extraction.providers import ProviderResponse
from idp.models import Document, ExtractionRun
from idp.services.processing import ProcessingService

CASE_ID = "Dummy-Dummy-29495"


def upload(client: TestClient, content: bytes, *, key: str = "upload-key-0001"):
    return client.post(
        f"/api/v1/cases/{CASE_ID}/documents",
        headers={"Idempotency-Key": key},
        files={"file": ("synthetic-medical-report.pdf", content, "application/pdf")},
        data={"document_type": "medical_report"},
    )


def process_one(app) -> str | None:
    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
    )
    return service.process_next()


def test_complete_upload_extract_source_review_and_audit_flow(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    response = upload(client, synthetic_pdf)
    assert response.status_code == 202, response.text
    uploaded = response.json()["document"]
    document_id = uploaded["id"]
    assert uploaded["status"] == "uploaded"
    assert uploaded["created_at"].endswith(("Z", "+00:00"))
    assert response.json()["replayed"] is False
    assert response.headers["x-correlation-id"]
    with app.state.database.session() as session:
        stored_document = session.get(Document, document_id)
        assert stored_document is not None
        object_key = stored_document.object_key
    stored_path = app.state.object_store.path_for(object_key)
    assert stored_path.read_bytes() == synthetic_pdf

    assert process_one(app) == uploaded["job_id"]

    workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace")
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    # The synthetic report is clean, so nothing is critical and it completes without HITL.
    assert body["documents"][0]["status"] == "completed"
    assert body["counts"]["pending"] == 0
    assert body["case_review"]["documents_analysed"] == 1
    assert body["case_review"]["open_flags"] == 0
    assert body["runs"][0]["provider"] == "deterministic-local"
    assert body["counts"]["found"] >= 20
    bmi = next(field for field in body["fields"] if field["field_path"] == "observations.bmi")
    assert bmi["candidate_value"] == 26.1
    assert bmi["source_literal"] == "26.1"
    assert bmi["citations"][0]["document_id"] == document_id
    assert bmi["citations"][0]["page"] == 1
    assert "BMI: 26.1 kg/m2" in bmi["citations"][0]["excerpt"]
    assert bmi["review_state"] == "accepted"
    assert {"code": "auto_accepted", "severity": "info", "message": None} in bmi["validations"]

    history = client.get(f"/api/v1/documents/{document_id}/extractions/history")
    assert history.status_code == 200, history.text
    history_body = history.json()
    assert history_body["document"]["id"] == document_id
    assert len(history_body["runs"]) == 1
    assert history_body["runs"][0]["run"]["id"] == body["runs"][0]["id"]
    assert history_body["runs"][0]["field_count"] == sum(
        body["counts"][key] for key in ("found", "uncertain", "not_found")
    )
    assert history_body["runs"][0]["pending_fields"] == 0

    content = client.get(f"/api/v1/documents/{document_id}/content")
    assert content.status_code == 200
    assert content.content == synthetic_pdf
    assert content.headers["content-type"].startswith("application/pdf")
    assert content.headers["cache-control"] == "private, no-store, max-age=0"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" not in content.headers["content-security-policy"]
    assert "frame-ancestors 'self'" in content.headers["content-security-policy"]

    review = client.post(
        f"/api/v1/documents/{document_id}/reviews",
        json={
            "decisions": [
                {
                    "field_id": bmi["id"],
                    "decision": "corrected",
                    "expected_version": 0,
                    "corrected_value": "26.2",
                    "rationale": "Verified against the synthetic source fixture.",
                }
            ]
        },
    )
    assert review.status_code == 200, review.text
    assert review.json()["reviews"][0]["after_value"] == 26.2

    refreshed = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    corrected = next(field for field in refreshed["fields"] if field["id"] == bmi["id"])
    assert corrected["candidate_value"] == 26.1
    assert corrected["effective_value"] == 26.2
    assert corrected["review_state"] == "corrected"
    assert corrected["review_version"] == 1

    stale = client.post(
        f"/api/v1/documents/{document_id}/reviews",
        json={
            "decisions": [
                {
                    "field_id": bmi["id"],
                    "decision": "accepted",
                    "expected_version": 0,
                }
            ]
        },
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_review"

    audit = client.get(f"/api/v1/cases/{CASE_ID}/audit")
    assert audit.status_code == 200
    audit_text = audit.text
    assert "evidence.reviewed" in audit_text
    assert "26.2" not in audit_text
    assert "Verified against" not in audit_text


def test_case_can_be_created_listed_opened_and_audited(
    client: TestClient, synthetic_pdf: bytes
) -> None:
    created = client.post(
        "/api/v1/cases",
        json={
            "external_case_id": "DEMO-CASE-1001",
            "applicant_display_name": "Synthetic Applicant",
            "proposal_number": "PROP-1001",
            "product_name": "Life Protect Plus",
        },
    )
    assert created.status_code == 201, created.text
    case = created.json()
    assert case["external_case_id"] == "DEMO-CASE-1001"

    listed = client.get("/api/v1/cases")
    assert listed.status_code == 200, listed.text
    case_row = next(
        item for item in listed.json() if item["case"]["external_case_id"] == "DEMO-CASE-1001"
    )
    assert case_row["document_count"] == 0

    opened = client.get("/api/v1/cases/DEMO-CASE-1001/workspace")
    assert opened.status_code == 200, opened.text
    assert opened.json()["case"]["proposal_number"] == "PROP-1001"
    assert opened.json()["documents"] == []

    case_upload = client.post(
        "/api/v1/cases/DEMO-CASE-1001/documents",
        headers={"Idempotency-Key": "new-case-upload-1001"},
        files={"file": ("synthetic-medical-report.pdf", synthetic_pdf, "application/pdf")},
        data={"document_type": "medical_report"},
    )
    assert case_upload.status_code == 202
    case_workspace = client.get("/api/v1/cases/DEMO-CASE-1001/workspace").json()
    assert len(case_workspace["documents"]) == 1
    assert client.get("/api/v1/cases/DEMO-CASE-1001/audit").status_code == 200

    duplicate = client.post(
        "/api/v1/cases",
        json={
            "external_case_id": "DEMO-CASE-1001",
            "applicant_display_name": "Synthetic Applicant",
            "proposal_number": "PROP-1001",
            "product_name": "Life Protect Plus",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "case_id_conflict"

    other_user = {"X-Demo-User": "other-reviewer"}
    assert client.get(
        "/api/v1/cases/DEMO-CASE-1001/workspace", headers=other_user
    ).status_code == 404


def test_external_provider_receives_redacted_text_and_citation_is_restored(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    class CapturingProvider:
        name = "test-external"
        model_version = "test-model"

        def __init__(self) -> None:
            self.input_text = ""
            self.input_blocks = ""

        def extract(self, *, pages, definition):
            del definition
            self.input_text = "\n".join(page.text for page in pages)
            self.input_blocks = "\n".join(
                block.text for page in pages for block in page.blocks
            )
            return ProviderResponse(
                fields=[
                    {
                        "field_path": "observations.bmi",
                        "source_literal": "26.1",
                        "page": 1,
                        "excerpt": "BMI: 26.1 kg/m2",
                        "confidence": 0.9,
                    }
                ],
                additional_facts=[
                    {
                        "name": "ECG finding",
                        "category": "observation",
                        "data_type": "text",
                        "source_literal": "Normal sinus rhythm",
                        "page": 1,
                        "excerpt": "Resting ECG: Normal sinus rhythm",
                        "confidence": 0.95,
                    },
                    {
                        "name": "Malformed fact",
                        "category": "unsupported-category",
                        "data_type": "text",
                        "source_literal": "Occasional",
                        "page": 1,
                        "excerpt": "Alcohol: Occasional",
                        "confidence": 0.8,
                    },
                ],
                ai_analysis={
                    "summary": {
                        "text": "The report records a normal resting ECG.",
                        "citations": [{
                            "page": 1,
                            "excerpt": "Resting ECG: Normal sinus rhythm",
                        }],
                    },
                    "recommendations": [{
                        "text": "Discuss the report findings with a qualified clinician.",
                        "citations": [{
                            "page": 1,
                            "excerpt": "Resting ECG: Normal sinus rhythm",
                        }],
                    }],
                    "vitals_summary": {
                        "text": "The report records a BMI of 26.1 kg/m2.",
                        "citations": [{
                            "page": 1,
                            "excerpt": "BMI: 26.1 kg/m2",
                        }],
                    },
                    "major_vital_factors": [{
                        "text": "BMI is listed as 26.1 kg/m2.",
                        "citations": [{
                            "page": 1,
                            "excerpt": "BMI: 26.1 kg/m2",
                        }],
                    }],
                    "key_medical_findings": [{
                        "text": "The ECG records normal sinus rhythm.",
                        "citations": [{
                            "page": 1,
                            "excerpt": "Resting ECG: Normal sinus rhythm",
                        }],
                    }],
                    "lab_results": [{
                        "category": "hematology",
                        "name": "Hemoglobin",
                        "value": "13.2",
                        "unit": "g/dL",
                        "reference_range": "12.0-16.0",
                        "reported_flag": None,
                        "confidence": 0.94,
                        "citations": [{
                            "page": 1,
                            "excerpt": "Hemoglobin: 13.2 g/dL",
                        }],
                    }],
                    "knockout_checks": [{
                        "factor": "HIV",
                        "value": "Non-reactive",
                        "confidence": 0.96,
                        "citations": [{
                            "page": 1,
                            "excerpt": "HIV: Non-reactive",
                        }],
                    }],
                },
            )

    provider = CapturingProvider()
    document = pymupdf.open(stream=synthetic_pdf, filetype="pdf")
    document[0].insert_text((50, 500), "Patient Name: Aarav Mehta", fontsize=11)
    document[0].insert_text((50, 480), "Hemoglobin: 13.2 g/dL", fontsize=11)
    document[0].insert_text((50, 460), "HIV: Non-reactive", fontsize=11)
    pdf = document.tobytes(garbage=4, deflate=True)
    document.close()
    response = upload(client, pdf, key="redaction-test-12345")
    assert response.status_code == 202, response.text

    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
        provider=provider,
    )
    service.process_next()

    assert "Aarav" not in provider.input_text
    assert "Mehta" not in provider.input_text
    assert "Aarav" not in provider.input_blocks
    assert "Mehta" not in provider.input_blocks
    assert "BMI: 26.1 kg/m2" in provider.input_text
    workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    bmi = next(field for field in workspace["fields"] if field["field_path"] == "observations.bmi")
    assert bmi["source_literal"] == "26.1"
    assert bmi["citations"][0]["excerpt"] == "BMI: 26.1 kg/m2"
    assert [fact["name"] for fact in workspace["additional_facts"]] == ["ECG finding"]
    assert workspace["additional_facts"][0]["citations"][0]["excerpt"] == (
        "Resting ECG: Normal sinus rhythm"
    )
    ai_analysis = workspace["runs"][0]["ai_analysis"]
    assert ai_analysis["summary"]["text"] == "The report records a normal resting ECG."
    assert ai_analysis["summary"]["citations"][0]["excerpt"] == (
        "Resting ECG: Normal sinus rhythm"
    )
    assert ai_analysis["recommendations"][0]["citations"][0]["document_id"] == bmi["document_id"]
    assert ai_analysis["vitals_summary"]["citations"][0]["excerpt"] == "BMI: 26.1 kg/m2"
    assert ai_analysis["key_medical_findings"][0]["text"] == (
        "The ECG records normal sinus rhythm."
    )
    assert ai_analysis["lab_results"][0]["citations"][0]["document_id"] == bmi["document_id"]
    assert ai_analysis["knockout_checks"][0]["citations"][0]["excerpt"] == (
        "HIV: Non-reactive"
    )
    audit = client.get(f"/api/v1/cases/{CASE_ID}/audit").json()
    extraction_event = next(
        event for event in audit["items"] if event["action"] == "document.extraction_completed"
    )
    assert extraction_event["metadata"]["rejected_provider_items"] == 1
    assert extraction_event["metadata"]["provider_item_rejections"] == {
        "invalid_additional_fact": 1
    }


def test_provider_failure_records_stage_without_saving_raw_response(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    class FailingProvider:
        name = "test-external"
        model_version = "test-model"

        def extract(self, *, pages, definition):
            del pages, definition
            raise ProcessingError("provider_response_schema_invalid", retryable=False)

    uploaded = upload(client, synthetic_pdf, key="provider-failure-12345").json()["document"]
    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
        provider=FailingProvider(),
    )
    service.process_next()

    workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    failed_document = next(
        item for item in workspace["documents"] if item["id"] == uploaded["id"]
    )
    assert failed_document["status"] == "failed"
    assert failed_document["failure_code"] == "provider_response_schema_invalid"
    assert not workspace["runs"]

    audit = client.get(f"/api/v1/cases/{CASE_ID}/audit").json()
    failure_event = next(
        event
        for event in audit["items"]
        if event["action"] == "document.processing_failed"
        and event["document_id"] == uploaded["id"]
    )
    assert failure_event["metadata"]["failure_stage"] == "provider_request"
    assert "response" not in failure_event["metadata"]


def test_invalid_ai_analysis_does_not_discard_valid_extraction(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    uploaded = upload(
        client,
        synthetic_pdf,
        key="invalid-ai-analysis-salvage-12345",
    ).json()["document"]

    class ProviderWithInvalidAnalysis:
        name = "test-external"
        model_version = "test-model"

        def extract(self, *, pages, definition):
            del pages, definition
            return ProviderResponse(
                fields=[{
                    "field_path": "observations.bmi",
                    "source_literal": "26.1",
                    "page": 1,
                    "excerpt": "BMI: 26.1 kg/m2",
                    "confidence": 0.9,
                }],
                additional_facts=[],
                ai_analysis_error="provider_ai_analysis_schema_invalid",
            )

    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
        provider=ProviderWithInvalidAnalysis(),
    )

    assert service.process_next() == uploaded["job_id"]

    workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    document = next(item for item in workspace["documents"] if item["id"] == uploaded["id"])
    run = next(item for item in workspace["runs"] if item["document_id"] == uploaded["id"])
    bmi = next(
        field for field in workspace["fields"]
        if field["document_id"] == uploaded["id"]
        and field["field_path"] == "observations.bmi"
    )
    assert document["status"] == "completed"
    assert bmi["candidate_value"] == 26.1
    assert run["ai_analysis"] is None

    audit = client.get(f"/api/v1/cases/{CASE_ID}/audit").json()
    completed = next(
        event for event in audit["items"]
        if event["action"] == "document.extraction_completed"
        and event["document_id"] == uploaded["id"]
    )
    assert completed["metadata"]["provider_item_rejections"] == {
        "provider_ai_analysis_schema_invalid": 1
    }


def test_missing_ai_summary_can_be_regenerated_without_overwriting_prior_run(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    uploaded = upload(
        client,
        synthetic_pdf,
        key="missing-ai-summary-regeneration-12345",
    ).json()["document"]

    def analysis(summary):
        return {
            "summary": summary,
            "key_medical_findings": [{
                "text": "BMI is recorded as 26.1 kg/m2.",
                "citations": [{"page": 1, "excerpt": "BMI: 26.1 kg/m2"}],
            }],
            "recommendations": [],
            "vitals_summary": None,
            "major_vital_factors": [],
            "lab_results": [],
            "knockout_checks": [],
        }

    class Provider:
        name = "openai-compatible"
        model_version = "test-model"

        def __init__(self, ai_analysis):
            self.ai_analysis = ai_analysis

        def extract(self, *, pages, definition):
            del pages, definition
            return ProviderResponse(
                fields=[{
                    "field_path": "observations.bmi",
                    "source_literal": "26.1",
                    "page": 1,
                    "excerpt": "BMI: 26.1 kg/m2",
                    "confidence": 0.9,
                }],
                additional_facts=[],
                ai_analysis=self.ai_analysis,
            )

    missing_summary = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
        provider=Provider(analysis(None)),
    )
    assert missing_summary.process_next() == uploaded["job_id"]

    first_workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    first_run = next(
        run for run in first_workspace["runs"] if run["document_id"] == uploaded["id"]
    )
    assert first_run["ai_analysis"]["summary"] is None

    retry = client.post(f"/api/v1/documents/{uploaded['id']}/retry")
    assert retry.status_code == 200, retry.text
    queued = retry.json()
    assert queued["status"] == "uploaded"
    assert queued["job_id"] != uploaded["job_id"]

    summary = {
        "text": "The report records a BMI of 26.1 kg/m2.",
        "citations": [{"page": 1, "excerpt": "BMI: 26.1 kg/m2"}],
    }
    summary_provider = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
        provider=Provider(analysis(summary)),
    )
    assert summary_provider.process_next() == queued["job_id"]

    final_workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    runs = [run for run in final_workspace["runs"] if run["document_id"] == uploaded["id"]]
    assert runs[0]["ai_analysis"]["summary"]["text"] == summary["text"]
    with app.state.database.session() as session:
        stored_runs = session.scalars(
            select(ExtractionRun).where(ExtractionRun.document_id == uploaded["id"])
        ).all()
    assert len(stored_runs) == 2
    assert next(run for run in stored_runs if run.sequence == 1).ai_analysis_json["summary"] is None
    assert client.post(f"/api/v1/documents/{uploaded['id']}/retry").status_code == 409
    audit = client.get(f"/api/v1/cases/{CASE_ID}/audit").json()["items"]
    retry_event = next(
        event for event in audit
        if event["action"] == "document.ai_summary_retry_requested"
        and event["document_id"] == uploaded["id"]
    )
    assert retry_event["metadata"]["reason"] == "missing_ai_summary"


def test_completed_local_run_can_be_reprocessed(client: TestClient, app, synthetic_pdf: bytes) -> None:
    uploaded = upload(
        client,
        synthetic_pdf,
        key="local-reprocess-key-12345",
    ).json()["document"]
    assert process_one(app) == uploaded["job_id"]

    retry = client.post(f"/api/v1/documents/{uploaded['id']}/retry")

    assert retry.status_code == 200, retry.text
    queued = retry.json()
    assert queued["status"] == "uploaded"
    assert queued["job_id"] != uploaded["job_id"]
    audit = client.get(f"/api/v1/cases/{CASE_ID}/audit").json()["items"]
    retry_event = next(
        event for event in audit
        if event["action"] == "document.local_extraction_retry_requested"
        and event["document_id"] == uploaded["id"]
    )
    assert retry_event["metadata"]["reason"] == "manual_local_reprocess"


def test_document_removal_deletes_source_and_evidence_but_retains_audit(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    uploaded = upload(client, synthetic_pdf, key="remove-completed-key-123").json()["document"]
    assert process_one(app) == uploaded["job_id"]
    with app.state.database.session() as session:
        stored = session.get(Document, uploaded["id"])
        assert stored is not None
        object_path = app.state.object_store.path_for(stored.object_key)

    removed = client.delete(f"/api/v1/documents/{uploaded['id']}")

    assert removed.status_code == 200, removed.text
    assert removed.json() == {"document_id": uploaded["id"], "deleted": True}
    assert not object_path.exists()
    assert client.get(f"/api/v1/documents/{uploaded['id']}").status_code == 404
    assert client.get(f"/api/v1/documents/{uploaded['id']}/extractions/history").status_code == 404
    workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    assert all(document["id"] != uploaded["id"] for document in workspace["documents"])
    assert all(field["document_id"] != uploaded["id"] for field in workspace["fields"])
    audit = client.get(f"/api/v1/cases/{CASE_ID}/audit").json()["items"]
    deletion = next(event for event in audit if event["action"] == "document.deleted")
    assert deletion["document_id"] == uploaded["id"]
    assert deletion["metadata"]["reason"] == "user_requested"


def test_queued_document_can_be_removed_without_leaving_a_worker_job(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    uploaded = upload(client, synthetic_pdf, key="remove-queued-key-123").json()["document"]

    removed = client.delete(f"/api/v1/documents/{uploaded['id']}")

    assert removed.status_code == 200, removed.text
    assert process_one(app) is None
    assert client.get(f"/api/v1/documents/{uploaded['id']}").status_code == 404


def test_removing_a_claimed_document_stops_the_worker_without_retrying_it(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    uploaded = upload(client, synthetic_pdf, key="remove-claimed-key-123").json()["document"]
    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
    )
    job_id = service._claim_next()
    assert job_id == uploaded["job_id"]

    removed = client.delete(f"/api/v1/documents/{uploaded['id']}")

    assert removed.status_code == 200, removed.text
    service.process_job(job_id)
    assert client.get(f"/api/v1/documents/{uploaded['id']}").status_code == 404


def test_document_removal_requires_document_management_permission(
    client: TestClient, synthetic_pdf: bytes
) -> None:
    uploaded = upload(client, synthetic_pdf, key="remove-denied-key-123").json()["document"]

    removed = client.delete(
        f"/api/v1/documents/{uploaded['id']}",
        headers={"X-Demo-Role": "auditor"},
    )

    assert removed.status_code == 403
    assert client.get(f"/api/v1/documents/{uploaded['id']}").status_code == 200


def test_upload_idempotency_and_changed_content_conflict(
    client: TestClient, synthetic_pdf: bytes
) -> None:
    first = upload(client, synthetic_pdf, key="same-key-12345")
    assert first.status_code == 202
    replay = upload(client, synthetic_pdf, key="same-key-12345")
    assert replay.status_code == 202
    assert replay.json()["replayed"] is True
    assert replay.json()["document"]["id"] == first.json()["document"]["id"]

    changed = upload(client, synthetic_pdf + b"\n% changed valid fixture", key="same-key-12345")
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_conflict"

    same_hash_new_key = upload(client, synthetic_pdf, key="second-key-12345")
    assert same_hash_new_key.status_code == 202
    assert same_hash_new_key.json()["document"]["id"] == first.json()["document"]["id"]
    changed_after_hash_replay = upload(
        client,
        synthetic_pdf + b"\n% another changed fixture",
        key="second-key-12345",
    )
    assert changed_after_hash_replay.status_code == 409
    assert changed_after_hash_replay.json()["code"] == "idempotency_conflict"


def test_mime_spoof_and_cross_tenant_access_are_rejected(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    spoof = client.post(
        f"/api/v1/cases/{CASE_ID}/documents",
        headers={"Idempotency-Key": "spoof-key-12345"},
        files={"file": ("not-a-report.pdf", b"plain text", "application/pdf")},
        data={"document_type": "medical_report"},
    )
    assert spoof.status_code == 415
    assert spoof.json()["code"] == "unsupported_media_type"

    uploaded = upload(client, synthetic_pdf, key="tenant-key-12345").json()["document"]
    process_one(app)
    other_tenant = {"X-Demo-Tenant": "tenant-other", "X-Demo-Role": "reviewer"}
    denied_content = client.get(f"/api/v1/documents/{uploaded['id']}/content", headers=other_tenant)
    assert denied_content.status_code == 404
    assert synthetic_pdf[:20] not in denied_content.content
    denied_case = client.get(f"/api/v1/cases/{CASE_ID}/workspace", headers=other_tenant)
    assert denied_case.status_code == 404

    unassigned = {
        "X-Demo-Tenant": "tenant-demo",
        "X-Demo-Role": "reviewer",
        "X-Demo-Cases": "MMIL-UW-OTHER",
    }
    denied_unassigned_content = client.get(
        f"/api/v1/documents/{uploaded['id']}/content", headers=unassigned
    )
    assert denied_unassigned_content.status_code == 404
    denied_unassigned_case = client.get(
        f"/api/v1/cases/{CASE_ID}/workspace", headers=unassigned
    )
    assert denied_unassigned_case.status_code == 404


def test_document_completes_only_after_all_candidates_receive_terminal_review(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    uploaded = upload(client, synthetic_pdf, key="complete-review-12345").json()["document"]
    process_one(app)
    workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    decisions = [
        {
            "field_id": field["id"],
            "decision": "accepted",
            "expected_version": field["review_version"],
        }
        for field in workspace["fields"]
        if field["candidate_value"] is not None
    ]
    response = client.post(
        f"/api/v1/documents/{uploaded['id']}/reviews",
        json={"decisions": decisions},
    )
    assert response.status_code == 200, response.text
    assert response.json()["document_status"] == "completed"
    refreshed = client.get(f"/api/v1/cases/{CASE_ID}/workspace").json()
    assert refreshed["documents"][0]["status"] == "completed"
    assert refreshed["counts"]["pending"] == 0
    assert refreshed["counts"]["accepted"] == len(decisions)


def test_auditor_cannot_upload(client: TestClient, synthetic_pdf: bytes) -> None:
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/documents",
        headers={"Idempotency-Key": "audit-key-12345", "X-Demo-Role": "auditor"},
        files={"file": ("synthetic-medical-report.pdf", synthetic_pdf, "application/pdf")},
        data={"document_type": "medical_report"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
