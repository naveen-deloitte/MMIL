from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

DEMO_CASE_ID = "MMIL-DEMO-001"


def variance_url(case_id: str = DEMO_CASE_ID) -> str:
    return f"/api/v1/cases/{case_id}/underwriting-variances"


def test_demo_variance_is_seeded_but_excluded_from_regular_case_list(
    client: TestClient,
) -> None:
    response = client.get(variance_url())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["demo_mode"] is True
    assert body["case"]["applicant_display_name"] == "Ananya Sharma"
    assert body["case"]["is_demo"] is True
    assert body["pending_variances"] == 1
    assert body["resolved_variances"] == 0
    assert body["total_variances"] == 1
    assert body["cases_requiring_decision"] == 1
    variance = body["variances"][0]
    assert variance["title"] == "Premium Variance"
    assert variance["applied_value"] == 50000
    assert variance["suggested_value"] == 60000
    assert variance["difference"] == 10000
    assert variance["recommendation_source"].startswith("DEMO")
    assert variance["status"] == "pending"

    listed_cases = client.get("/api/v1/cases").json()
    assert all(item["case"]["external_case_id"] != DEMO_CASE_ID for item in listed_cases)


def test_real_case_has_no_fabricated_variance(client: TestClient) -> None:
    response = client.get(variance_url("Dummy-Dummy-29495"))

    assert response.status_code == 200, response.text
    assert response.json()["demo_mode"] is False
    assert response.json()["variances"] == []
    assert response.json()["total_variances"] == 0
    assert response.json()["cases_requiring_decision"] == 0


@pytest.mark.parametrize(
    ("decision", "selected_value", "expected_value", "expected_status"),
    [
        ("retain_original", None, 50000, "resolved"),
        ("accept_suggested", None, 60000, "resolved"),
        ("custom_value", 55000, 55000, "resolved"),
        ("refer", None, None, "referred"),
    ],
)
def test_demo_variance_decisions_are_persisted_without_overwriting_recommendation(
    client: TestClient,
    decision: str,
    selected_value: int | None,
    expected_value: int | None,
    expected_status: str,
) -> None:
    initial = client.get(variance_url()).json()["variances"][0]
    payload: dict[str, object] = {
        "decision": decision,
        "justification": "Reviewed against the demo application and recommendation.",
    }
    if selected_value is not None:
        payload["selected_value"] = selected_value

    response = client.post(
        f"{variance_url()}/{initial['id']}/decisions",
        json=payload,
    )
    assert response.status_code == 200, response.text

    updated = response.json()
    variance = updated["variances"][0]
    assert variance["status"] == expected_status
    assert variance["applied_value"] == 50000
    assert variance["suggested_value"] == 60000
    assert variance["difference"] == 10000
    assert variance["current_decision"]["decision"] == decision
    assert variance["current_decision"]["selected_value"] == expected_value
    assert variance["current_decision"]["reviewer_subject"] == "reviewer-demo"
    assert variance["current_decision"]["approval_status"] == "demo_only"

    if expected_status == "resolved":
        assert updated["resolved_variances"] == 1
        assert updated["pending_variances"] == 0
    else:
        assert updated["cases_requiring_decision"] == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "retain_original", "justification": "   "},
        {"decision": "custom_value", "justification": "Use custom amount."},
        {
            "decision": "custom_value",
            "selected_value": 0,
            "justification": "Use custom amount.",
        },
        {
            "decision": "retain_original",
            "selected_value": 55000,
            "justification": "Keep original.",
        },
    ],
)
def test_invalid_or_missing_justification_and_custom_amount_are_rejected(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    variance = client.get(variance_url()).json()["variances"][0]
    response = client.post(f"{variance_url()}/{variance['id']}/decisions", json=payload)

    assert response.status_code == 422
    assert client.get(variance_url()).json()["variances"][0]["status"] == "pending"


def test_demo_reset_reopens_variance_and_preserves_audit_history(
    client: TestClient,
) -> None:
    variance = client.get(variance_url()).json()["variances"][0]
    recorded = client.post(
        f"{variance_url()}/{variance['id']}/decisions",
        json={
            "decision": "accept_suggested",
            "justification": "Accept the simulated recommendation for the demo.",
        },
    )
    assert recorded.status_code == 200, recorded.text

    reset = client.post(f"{variance_url()}/demo-reset")
    assert reset.status_code == 200, reset.text
    body = reset.json()
    reopened = body["variances"][0]
    assert reopened["status"] == "pending"
    assert reopened["current_decision"] is None
    assert [event["decision"] for event in reopened["history"]] == ["accept_suggested", "reset"]
    assert body["pending_variances"] == 1

    audit = client.get(f"/api/v1/cases/{DEMO_CASE_ID}/audit")
    assert audit.status_code == 200, audit.text
    actions = [item["action"] for item in audit.json()["items"]]
    assert "underwriting.variance_decision_recorded" in actions
    assert "underwriting.variance_demo_reset" in actions


def test_only_reviewers_can_record_variance_decisions(client: TestClient) -> None:
    variance = client.get(variance_url()).json()["variances"][0]
    response = client.post(
        f"{variance_url()}/{variance['id']}/decisions",
        headers={"X-Demo-Role": "operator"},
        json={
            "decision": "retain_original",
            "justification": "Keep the original demo premium.",
        },
    )

    assert response.status_code == 403
    assert client.get(variance_url()).json()["variances"][0]["status"] == "pending"


def test_variance_case_cannot_be_accessed_from_another_tenant(client: TestClient) -> None:
    response = client.get(
        variance_url(),
        headers={"X-Demo-Tenant": "tenant-other"},
    )
    assert response.status_code == 404


def test_submitting_a_second_decision_requires_demo_reset(client: TestClient) -> None:
    variance = client.get(variance_url()).json()["variances"][0]
    payload = {
        "decision": "retain_original",
        "justification": "Keep the original demo premium.",
    }
    first = client.post(f"{variance_url()}/{variance['id']}/decisions", json=payload)
    second = client.post(f"{variance_url()}/{variance['id']}/decisions", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["code"] == "variance_already_reviewed"
