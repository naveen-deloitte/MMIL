from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from idp.services.processing import ProcessingService

CASE_ID = "Dummy-Dummy-29495"


def process_one(app) -> str | None:
    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
    )
    return service.process_next()


def approve_payload() -> dict:
    return {
        "decision": "approve",
        "approved_sum_assured": "1000000.00",
        "applicable_premium": "12000.00",
        "decision_rationale": "Reviewed source evidence and product eligibility.",
        "additional_terms": "Standard terms.",
    }


def test_final_decisions_require_completed_readiness_and_preserve_history(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    url = f"/api/v1/cases/{CASE_ID}/underwriting-decisions"
    initial = client.get(url)
    assert initial.status_code == 200, initial.text
    assert initial.json()["readiness"]["source_documents_complete"] is False
    assert initial.json()["readiness"]["underwriting_guidelines_available"] is False
    assert initial.json()["readiness"]["information_requests_tracked"] is False

    denied = client.post(url, json=approve_payload())
    assert denied.status_code == 409
    assert denied.json()["code"] == "decision_prerequisites_not_met"

    unauthorized = client.post(
        url,
        headers={"X-Demo-Role": "operator"},
        json=approve_payload(),
    )
    assert unauthorized.status_code == 403

    upload = client.post(
        f"/api/v1/cases/{CASE_ID}/documents",
        headers={"Idempotency-Key": "decision-test-upload-001"},
        files={"file": ("decision-source.pdf", synthetic_pdf, "application/pdf")},
        data={"document_type": "medical_report"},
    )
    assert upload.status_code == 202, upload.text
    assert process_one(app) == upload.json()["document"]["job_id"]

    ready = client.get(url).json()
    assert ready["readiness"]["mandatory_prerequisites_met"] is True
    assert ready["readiness"]["source_documents_complete"] is True
    assert ready["readiness"]["evidence_review_complete"] is True

    recorded = client.post(url, json=approve_payload())
    assert recorded.status_code == 200, recorded.text
    response = recorded.json()
    assert response["case"]["workflow_stage"] == "resolved"
    assert len(response["decisions"]) == 1
    decision = response["decisions"][0]
    assert decision["decision"] == "approve"
    assert decision["approved_sum_assured"] == "1000000.00"
    assert decision["underwriter_subject"] == "reviewer-demo"
    assert decision["supporting_document_ids"] == []
    assert decision["authority_reference"] == ""
    assert decision["guideline_reference"] == ""
    assert decision["authority_attested"] is False
    assert decision["information_requests_acknowledged"] is False

    decline = {
        "decision": "decline",
        "decline_reason": "A later authorized review changed the outcome.",
    }
    changed = client.post(url, json=decline)
    assert changed.status_code == 200, changed.text
    assert [item["decision"] for item in changed.json()["decisions"]] == ["decline", "approve"]

    postpone = {
        "decision": "postpone",
        "postponement_reason": "Additional financial documents need assessment.",
        "additional_requirements": "Provide the latest income statement.",
        "expected_reassessment_date": (date.today() + timedelta(days=30)).isoformat(),
    }
    postponed = client.post(url, json=postpone)
    assert postponed.status_code == 200, postponed.text
    assert postponed.json()["case"]["workflow_stage"] == "resolved"

    refer = {
        "decision": "refer",
        "referral_reason": "Requires specialist review.",
        "target_authority": "Senior medical underwriter",
    }
    referred = client.post(url, json=refer)
    assert referred.status_code == 200, referred.text
    assert referred.json()["case"]["workflow_stage"] == "hilt_escalated"
    history = referred.json()["decisions"]
    assert [item["decision"] for item in history] == ["refer", "postpone", "decline", "approve"]
    assert history[-1]["decision_rationale"] == "Reviewed source evidence and product eligibility."
    assert history[0]["authority_reference"] == ""
    assert history[0]["guideline_reference"] == ""
    assert history[0]["authority_attested"] is False
    assert history[0]["information_requests_acknowledged"] is False
    case_list = client.get("/api/v1/cases")
    listed_case = next(
        item["case"] for item in case_list.json() if item["case"]["external_case_id"] == CASE_ID
    )
    assert listed_case["final_decision"] == "refer"
    assert listed_case["decision_rationale"] == "Requires specialist review."

    audit = client.get(f"/api/v1/cases/{CASE_ID}/audit")
    assert audit.status_code == 200
    assert audit.text.count("underwriting.decision_recorded") == 4
    assert "Reviewed source evidence and product eligibility." not in audit.text


def test_decision_payload_requires_outcome_fields_and_case_owned_evidence(
    client: TestClient, app, synthetic_pdf: bytes
) -> None:
    url = f"/api/v1/cases/{CASE_ID}/underwriting-decisions"
    upload = client.post(
        f"/api/v1/cases/{CASE_ID}/documents",
        headers={"Idempotency-Key": "decision-test-upload-002"},
        files={"file": ("decision-source.pdf", synthetic_pdf, "application/pdf")},
        data={"document_type": "medical_report"},
    )
    assert upload.status_code == 202, upload.text
    assert process_one(app) == upload.json()["document"]["job_id"]

    invalid = approve_payload()
    invalid.pop("approved_sum_assured")
    response = client.post(url, json=invalid)
    assert response.status_code == 422

    invalid_evidence = approve_payload()
    invalid_evidence["supporting_document_ids"] = ["document-from-another-case"]
    response = client.post(url, json=invalid_evidence)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_decision_evidence"
