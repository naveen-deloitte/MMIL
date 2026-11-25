from __future__ import annotations

from fastapi.testclient import TestClient

from idp.services.processing import ProcessingService

CASE_ID = "MMIL-UW-2027-00018492"


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
    assert uploaded["created_at"].endswith("+00:00")
    assert response.json()["replayed"] is False
    assert response.headers["x-correlation-id"]

    assert process_one(app) == uploaded["job_id"]

    workspace = client.get(f"/api/v1/cases/{CASE_ID}/workspace")
    assert workspace.status_code == 200, workspace.text
    body = workspace.json()
    assert body["documents"][0]["status"] == "review_required"
    assert body["runs"][0]["provider"] == "deterministic-local"
    assert body["counts"]["found"] >= 20
    bmi = next(field for field in body["fields"] if field["field_path"] == "observations.bmi")
    assert bmi["candidate_value"] == 26.1
    assert bmi["source_literal"] == "26.1"
    assert bmi["citations"][0]["document_id"] == document_id
    assert bmi["citations"][0]["page"] == 1
    assert "BMI: 26.1 kg/m2" in bmi["citations"][0]["excerpt"]
    assert bmi["review_state"] == "pending"

    content = client.get(f"/api/v1/documents/{document_id}/content")
    assert content.status_code == 200
    assert content.content == synthetic_pdf
    assert content.headers["content-type"].startswith("application/pdf")
    assert content.headers["cache-control"] == "private, no-store, max-age=0"
    assert content.headers["x-content-type-options"] == "nosniff"

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
