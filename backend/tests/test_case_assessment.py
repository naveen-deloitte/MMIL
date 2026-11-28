"""End-to-end case assessment with synthetic cases: product -> documents -> assessment."""

from __future__ import annotations

import json
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from idp.api.app import create_app
from idp.config import Settings
from idp.models import AuditEvent, Case, CaseAssessment
from idp.services.processing import ProcessingService
from conftest import make_medical_pdf

ROOT = Path(__file__).resolve().parents[2]
CASE_ID = "UW-ASSESS-1"


def pdf(lines: list[str]) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    y = 60
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 22
    content = document.tobytes()
    document.close()
    return content


def create_case(client: TestClient, case_id: str = CASE_ID, **product) -> dict:
    response = client.post(
        "/api/v1/cases",
        json={
            "external_case_id": case_id,
            "applicant_display_name": "Rahul Sharma",
            "proposal_number": f"P-{case_id}",
            "product": {
                "product_id": "demo-term-shield",
                "sum_assured": 10000000,
                "premium_frequency": "annual",
                "policy_term": 20,
                "rating": {"age": 35, "gender": "male", "smoker": False},
                **product,
            },
        },
        headers={"X-Demo-Cases": case_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(client: TestClient, content: bytes, document_type: str, key: str, case_id: str = CASE_ID):
    response = client.post(
        f"/api/v1/cases/{case_id}/documents",
        headers={"Idempotency-Key": f"assess-{key}", "X-Demo-Cases": case_id},
        files={"file": (f"{key}.pdf", content, "application/pdf")},
        data={"document_type": document_type},
    )
    assert response.status_code == 202, response.text


def process_all(app) -> None:
    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
    )
    while service.process_next():
        pass


def assessment(client: TestClient, case_id: str = CASE_ID) -> dict:
    response = client.get(f"/api/v1/cases/{case_id}/assessment", headers={"X-Demo-Cases": case_id})
    assert response.status_code == 200, response.text
    return response.json()


def rules_by_id(result: dict) -> dict:
    return {rule["rule_id"]: rule for rule in result["rule_results"]}


def test_new_case_records_proposed_terms_before_evidence(client: TestClient) -> None:
    case = create_case(client)
    view = assessment(client)
    assert view["rules_configured"] is True and view["stale"] is False
    result = view["latest"]["result"]
    assert view["latest"]["version"] == 1 and view["latest"]["trigger"] == "case_created"
    proposed = result["proposed_terms"]
    assert proposed["status"] == "captured"
    assert proposed["sum_assured"] == 10000000
    assert proposed["premium"] == case["policy_details"]["indicative_quote"]["amount"]
    assert proposed["premium_status"] == "indicative"
    assert proposed["insurer"] == "Demo Life Assurance Ltd (fictional)"
    assert result["recommendation"]["code"] == "insufficient_evidence"
    assert result["recommendation"]["automatic_decision"] is False
    assert result["revised_premium"]["status"] == "not_available"
    assert result["recommended_terms"]["status"] == "not_available"
    assert view["final_terms"]["status"] == "not_recorded"


def test_documents_drive_rules_risk_and_recommendation(client: TestClient, app) -> None:
    create_case(client)
    upload(client, make_medical_pdf(bmi="37.2"), "medical_report", "medical")
    upload(
        client,
        pdf(
            [
                "Income Tax Return",
                "Assessment Year: 2026-27",
                "Gross Total Income: 400000",
                "Existing Life Cover: 2500000",
            ]
        ),
        "financial_document",
        "financial",
    )
    process_all(app)

    view = assessment(client)
    assert view["stale"] is False  # the worker refreshed it after processing
    latest = view["latest"]
    assert latest["version"] >= 3 and latest["trigger"] == "document_processed"
    result = latest["result"]
    rules = rules_by_id(result)

    bmi = rules["bmi_above_35"]
    assert bmi["status"] == "triggered"
    assert bmi["evidence"][0]["value"] == 37.2
    assert bmi["evidence"][0]["citations"][0]["page"] == 1
    assert "BMI: 37.2" in bmi["evidence"][0]["citations"][0]["excerpt"]
    assert rules["systolic_bp_above_160"]["status"] == "not_triggered"
    assert rules["identity_mismatch"]["status"] == "not_evaluable"

    exposure = result["financial"]["exposure"]
    assert exposure["proposed_sum_assured"] == 10000000
    assert exposure["existing_cover"]["amount"] == 2500000
    assert exposure["existing_cover"]["citations"]
    assert exposure["total_exposure"] == 12500000
    assert exposure["cover_to_income_multiple"] == 31.25
    assert rules["cover_over_20x_income"]["status"] == "triggered"

    for rule in result["rule_results"]:
        if rule["status"] == "triggered" and rule["category"] != "financial":
            assert all(item["citations"] for item in rule["evidence"]), rule["rule_id"]

    rec = result["recommendation"]
    assert rec["code"] == "refer_to_underwriter"
    assert {"bmi_above_35", "cover_over_20x_income"} <= set(rec["triggered_rule_ids"])
    risk = result["risk_score"]
    assert risk["status"] == "assessed"
    assert risk["model"]["approved"] is False and risk["model"]["is_demo"] is True
    assert risk["scale_min"] == 0 and risk["scale_max"] == 100 and risk["band"]
    # Proposed terms are untouched by the assessment.
    assert result["proposed_terms"]["sum_assured"] == 10000000
    with app.state.database.session() as session:
        case = session.scalar(select(Case).where(Case.external_case_id == CASE_ID))
        assert case.policy_details_json["sum_assured"] == 10000000


def test_review_correction_creates_new_version_and_keeps_history(client: TestClient, app) -> None:
    create_case(client)
    upload(client, make_medical_pdf(bmi="37.2"), "medical_report", "medical-2")
    process_all(app)
    before = assessment(client)["latest"]
    assert rules_by_id(before["result"])["bmi_above_35"]["status"] == "triggered"

    workspace = client.get(
        f"/api/v1/cases/{CASE_ID}/workspace", headers={"X-Demo-Cases": CASE_ID}
    ).json()
    bmi = next(f for f in workspace["fields"] if f["field_path"] == "observations.bmi")
    response = client.post(
        f"/api/v1/documents/{bmi['document_id']}/reviews",
        headers={"X-Demo-Cases": CASE_ID},
        json={
            "decisions": [
                {
                    "field_id": bmi["id"],
                    "decision": "corrected",
                    "expected_version": bmi["review_version"],
                    "corrected_value": "27.2",
                    "rationale": "Report misprint confirmed with the examiner.",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    after = assessment(client)
    assert after["latest"]["version"] == before["version"] + 1
    assert after["latest"]["trigger"] == "evidence_reviewed"
    assert rules_by_id(after["latest"]["result"])["bmi_above_35"]["status"] == "not_triggered"
    old = client.get(
        f"/api/v1/cases/{CASE_ID}/assessment/versions/{before['version']}",
        headers={"X-Demo-Cases": CASE_ID},
    ).json()
    assert rules_by_id(old["result"])["bmi_above_35"]["status"] == "triggered"
    assert [v["version"] for v in after["versions"]][:2] == [
        after["latest"]["version"],
        before["version"],
    ]
    with app.state.database.session() as session:
        events = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.action == "case.assessment_generated")
            )
        )
    assert len(events) == after["latest"]["version"]
    assert {e.metadata_json.get("assessment_version") for e in events} == set(
        range(1, after["latest"]["version"] + 1)
    )


def test_refresh_is_idempotent_and_requires_review_role(client: TestClient) -> None:
    create_case(client)
    headers = {"X-Demo-Cases": CASE_ID}
    first = client.post(f"/api/v1/cases/{CASE_ID}/assessment/refresh", headers=headers).json()
    second = client.post(f"/api/v1/cases/{CASE_ID}/assessment/refresh", headers=headers).json()
    assert first["latest"]["version"] == second["latest"]["version"] == 1
    forbidden = client.post(
        f"/api/v1/cases/{CASE_ID}/assessment/refresh",
        headers={**headers, "X-Demo-Role": "operator"},
    )
    assert forbidden.status_code == 403
    other_tenant = client.get(
        f"/api/v1/cases/{CASE_ID}/assessment", headers={**headers, "X-Demo-Tenant": "other"}
    )
    assert other_tenant.status_code == 404
    missing = client.get(f"/api/v1/cases/{CASE_ID}/assessment/versions/99", headers=headers)
    assert missing.status_code == 404


def test_without_rules_nothing_is_invented(settings: Settings, tmp_path: Path) -> None:
    settings.underwriting_rules_path = tmp_path / "no-rules"
    with TestClient(create_app(settings)) as client:
        create_case(client, "UW-NORULES")
        result = assessment(client, "UW-NORULES")["latest"]["result"]
    assert result["rule_results"] == []
    assert result["recommendation"]["status"] == "not_available"
    assert result["risk_score"]["status"] == "not_assessed"
    assert result["risk_score"]["score"] is None


def test_free_text_case_has_no_proposed_terms(client: TestClient) -> None:
    response = client.post(
        "/api/v1/cases",
        json={
            "external_case_id": "UW-LEGACY-A",
            "applicant_display_name": "Legacy",
            "proposal_number": "P",
            "product_name": "Some plan",
        },
    )
    assert response.status_code == 201
    result = assessment(client, "UW-LEGACY-A")["latest"]["result"]
    assert result["proposed_terms"]["status"] == "not_available"
    assert result["financial"]["exposure"]["proposed_sum_assured"] is None


def test_final_terms_come_only_from_recorded_decision(client: TestClient, app) -> None:
    create_case(client)
    with app.state.database.session() as session:
        case = session.scalar(select(Case).where(Case.external_case_id == CASE_ID))
        from idp.models import UnderwritingDecision

        session.add(
            UnderwritingDecision(
                tenant_id=case.tenant_id,
                case_id=case.id,
                decision="approve",
                approved_sum_assured=9000000,
                applicable_premium=12345,
                decision_rationale="Synthetic test decision.",
                authority_reference="test",
                guideline_reference="test",
                authority_attested=True,
                information_requests_acknowledged=True,
                underwriter_subject="reviewer-demo",
            )
        )
    view = assessment(client)
    assert view["final_terms"]["status"] == "recorded"
    assert view["final_terms"]["approved_sum_assured"] == 9000000
    # The decision never alters proposed terms.
    assert view["latest"]["result"]["proposed_terms"]["sum_assured"] == 10000000


def test_shipped_demo_rules_are_valid_and_flagged() -> None:
    from idp.assessment.rules import load_rule_set

    rules = load_rule_set(ROOT / "config" / "underwriting")
    assert rules is not None and rules.is_demo and rules.risk_scoring is not None
    assert rules.risk_scoring.approved is False
    assert json.dumps(rules.model_dump(mode="json"))  # serialisable


@pytest.mark.parametrize("bad", [{"rules": [{"rule_id": "x"}]}])
def test_invalid_rule_set_rejected(tmp_path: Path, bad: dict) -> None:
    from pydantic import ValidationError

    from idp.assessment.rules import load_rule_set

    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps({"rule_set_id": "r", "version": "1.0.0", "is_demo": True, "source": "test", **bad})
    )
    with pytest.raises(ValidationError):
        load_rule_set(path)


def test_case_assessment_table_created(client: TestClient, app) -> None:
    del client  # starts the app, which creates the schema
    with app.state.database.session() as session:
        assert session.scalars(select(CaseAssessment)).all() == []


def test_requote_adds_missing_inputs_and_keeps_history(client: TestClient, app) -> None:
    headers = {"X-Demo-Cases": "UW-REQUOTE"}
    created = client.post(
        "/api/v1/cases",
        headers=headers,
        json={
            "external_case_id": "UW-REQUOTE",
            "applicant_display_name": "Health Applicant",
            "proposal_number": "P-RQ",
            "product": {"product_id": "demo-health-secure", "sum_assured": 500000},
        },
    ).json()
    first_quote = created["policy_details"]["indicative_quote"]
    assert first_quote["status"] == "not_available"
    assert first_quote["missing_inputs"] == ["age"]

    response = client.post(
        "/api/v1/cases/UW-REQUOTE/product/requote", headers=headers, json={"age": 30}
    )
    assert response.status_code == 200, response.text
    details = response.json()["policy_details"]
    assert details["indicative_quote"]["status"] == "indicative"
    assert details["indicative_quote"]["amount"] == 7080  # 500000/1000 * 12 * 1.18
    assert details["sum_assured"] == 500000  # cover unchanged
    assert details["rating_inputs"]["age"] == 30
    assert details["proposal_history"][0]["indicative_quote"]["status"] == "not_available"

    view = assessment(client, "UW-REQUOTE")
    assert view["latest"]["trigger"] == "proposal_requoted"
    assert view["latest"]["result"]["proposed_terms"]["premium"] == 7080

    # Recorded details cannot be changed, and operators cannot re-price.
    changed = client.post(
        "/api/v1/cases/UW-REQUOTE/product/requote", headers=headers, json={"age": 45}
    )
    assert changed.json()["code"] == "rating_input_already_recorded"
    forbidden = client.post(
        "/api/v1/cases/UW-REQUOTE/product/requote",
        headers={**headers, "X-Demo-Role": "operator"},
        json={"age": 30},
    )
    assert forbidden.status_code == 403
    with app.state.database.session() as session:
        actions = [e.action for e in session.scalars(select(AuditEvent))]
    assert "case.proposal_requoted" in actions
