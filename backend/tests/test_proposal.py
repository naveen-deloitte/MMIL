"""Proposal details and View Proposal with synthetic cases."""

from __future__ import annotations

import pymupdf
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import make_medical_pdf
from idp.models import AuditEvent, Case, UnderwritingDecision
from idp.services.processing import ProcessingService

CASE = "UW-PROP-1"
H = {"X-Demo-Cases": CASE}


def pdf(lines: list[str]) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    y = 60
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 20
    content = document.tobytes()
    document.close()
    return content


PROPOSAL_LINES = [
    "LIFE INSURANCE PROPOSAL FORM",
    "Proposal Number: P-PROP-1",
    "Proposal Date: 15/11/2026",
    "Application Channel: Bancassurance",
    "Payment Mode: NACH auto-debit",
    "Sum Assured: 10000000",
    "Riders Selected: Demo Accidental Death Benefit rider",
    "Rider Sum Assured: 2500000",
    "Nominee: Priya Sharma (Spouse)",
    "Occupation: Software engineer",
    "Annual Income: 1800000",
    "Smoking / Tobacco Status: Non-smoker",
    "Existing Insurance Cover: 2500000",
    "Medical History: None declared",
]


def create_case(client: TestClient, case_id: str = CASE) -> dict:
    response = client.post(
        "/api/v1/cases",
        headers={"X-Demo-Cases": case_id},
        json={
            "external_case_id": case_id,
            "applicant_display_name": "Rahul Sharma",
            "proposal_number": "P-PROP-1",
            "product": {
                "product_id": "demo-term-shield",
                "sum_assured": 10000000,
                "premium_frequency": "monthly",
                "policy_term": 20,
                "rating": {"age": 35, "gender": "male", "smoker": False},
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload(client: TestClient, content: bytes, document_type: str, key: str, case_id: str = CASE):
    response = client.post(
        f"/api/v1/cases/{case_id}/documents",
        headers={"Idempotency-Key": f"proposal-{key}", "X-Demo-Cases": case_id},
        files={"file": (f"{key}.pdf", content, "application/pdf")},
        data={"document_type": document_type},
    )
    assert response.status_code == 202, response.text
    return response.json()["document"]


def process_all(app) -> None:
    service = ProcessingService(
        settings=app.state.settings,
        database=app.state.database,
        store=app.state.object_store,
        registry=app.state.registry,
    )
    while service.process_next():
        pass


def items(view: dict) -> dict[str, dict]:
    return {item["key"]: item for section in view["sections"] for item in section["items"]}


def test_proposal_details_combine_sources_without_overwriting(client: TestClient, app) -> None:
    case = create_case(client)
    original = upload(client, pdf(PROPOSAL_LINES), "proposal_form", "form-1")
    upload(client, pdf(["Income Tax Return", "Gross Total Income: 1500000"]), "financial_document", "itr")
    upload(client, make_medical_pdf(), "medical_report", "medical")
    process_all(app)

    view = client.get(f"/api/v1/cases/{CASE}/proposal", headers=H).json()
    assert [s["id"] for s in view["sections"]] == [
        "basic", "coverage", "assessed", "benefits", "declarations",
    ]
    data = items(view)
    instalment = case["policy_details"]["indicative_quote"]["amount"]

    assert data["insurer"]["value"] == "Demo Life Assurance Ltd (fictional)"
    assert data["insurer"]["source"] == "product_selection"
    assert data["proposal_date"]["value"] == "2026-11-15"
    assert data["proposal_date"]["source"] == "proposal_form"
    assert data["proposal_date"]["citations"][0]["page"] == 1
    assert data["channel"]["value"] == "Bancassurance"
    assert data["proposal_number"]["note"] is None  # form agrees with case

    assert data["sum_assured"]["value"] == 10000000 and data["sum_assured"]["highlight"]
    assert data["sum_assured"]["evidence"][0]["source"] == "proposal_form"
    assert data["instalment_premium"]["value"] == instalment
    assert data["annual_premium"]["value"] == round(instalment * 12, 2)
    assert "12 × monthly" in data["annual_premium"]["note"]
    assert data["premium_frequency"]["value"] == "Monthly"
    assert data["payment_mode"]["value"] == "NACH auto-debit"
    assert data["premium_breakdown"]["value"]["total"] == instalment

    assert data["cover_type"]["source"] == "product_catalogue"
    assert "Demo Accidental Death Benefit rider" in data["riders_available"]["value"]
    assert data["riders_selected"]["source"] == "proposal_form"
    assert data["rider_sum_assured"]["value"] == 2500000
    assert data["nominee"]["value"] == "Priya Sharma (Spouse)"

    income = data["annual_income"]
    assert income["value"] == 1800000 and income["source"] == "proposal_form"
    assert "not independently verified" in income["note"]
    evidence = income["evidence"][0]
    assert evidence["value"] == 1500000 and evidence["document_type"] == "financial_document"
    assert evidence["verified"] is False  # extracted only, not reviewed by a person
    tobacco_sources = {e["source"] for e in data["tobacco"]["evidence"]}
    assert {"document_evidence", "product_selection"} <= tobacco_sources
    assert data["previous_insurance"]["value"] is None and data["previous_insurance"]["source"] is None

    assert data["revised_premium"]["value"] is None
    assert data["final_sum_assured"]["value"] is None
    assert view["catalogue"]["is_demo"] is True
    assert view["proposal_document"]["id"] == original["id"]

    # Original proposed values are untouched by the assessment and by a decision.
    with app.state.database.session() as session:
        stored = session.scalar(select(Case).where(Case.external_case_id == CASE))
        session.add(
            UnderwritingDecision(
                tenant_id=stored.tenant_id, case_id=stored.id, decision="approve",
                approved_sum_assured=9000000, applicable_premium=1500,
                decision_rationale="Synthetic.", authority_reference="t", guideline_reference="t",
                authority_attested=True, information_requests_acknowledged=True,
                underwriter_subject="reviewer-demo",
            )
        )
    after = items(client.get(f"/api/v1/cases/{CASE}/proposal", headers=H).json())
    assert after["sum_assured"]["value"] == 10000000
    assert after["instalment_premium"]["value"] == instalment
    assert after["final_sum_assured"]["value"] == 9000000
    assert after["final_sum_assured"]["source"] == "underwriter_decision"
    assert after["proposal_status"]["value"] == "Decision recorded: Approve"


def test_view_proposal_opens_original_document_for_that_case(client: TestClient, app) -> None:
    create_case(client)
    first = upload(client, pdf(PROPOSAL_LINES), "proposal_form", "form-a")
    upload(client, pdf([*PROPOSAL_LINES, "Revised copy"]), "proposal_form", "form-b")
    upload(client, make_medical_pdf(), "medical_report", "med-x")
    process_all(app)

    response = client.get(f"/api/v1/cases/{CASE}/proposal/document", headers=H).json()
    assert response["available"] is True
    assert response["original"]["id"] == first["id"]
    assert response["proposal_number"] == "P-PROP-1"
    assert {d["document_type"] for d in response["documents"]} == {"proposal_form"}
    assert len(response["documents"]) == 2
    content = client.get(f"/api/v1/documents/{first['id']}/content", headers=H)
    assert content.status_code == 200 and content.headers["content-type"] == "application/pdf"

    with app.state.database.session() as session:
        actions = [e.action for e in session.scalars(select(AuditEvent))]
    assert "case.proposal_document_requested" in actions
    assert "document.content_viewed" in actions


def test_missing_proposal_document_is_reported_and_audited(client: TestClient, app) -> None:
    create_case(client, "UW-PROP-NONE")
    response = client.get(
        "/api/v1/cases/UW-PROP-NONE/proposal/document", headers={"X-Demo-Cases": "UW-PROP-NONE"}
    ).json()
    assert response["available"] is False and response["original"] is None
    assert "Proposal document not available" in response["message"]
    view = client.get(
        "/api/v1/cases/UW-PROP-NONE/proposal", headers={"X-Demo-Cases": "UW-PROP-NONE"}
    ).json()
    assert view["proposal_document"] is None
    assert items(view)["proposal_date"]["value"] is None
    with app.state.database.session() as session:
        outcomes = [
            e.outcome for e in session.scalars(
                select(AuditEvent).where(AuditEvent.action == "case.proposal_document_requested")
            )
        ]
    assert outcomes == ["not_available"]


def test_proposal_access_is_case_and_tenant_scoped(client: TestClient, app) -> None:
    create_case(client)
    upload(client, pdf(PROPOSAL_LINES), "proposal_form", "form-s")
    # A different user without this case in scope (the creator always keeps access in demo mode).
    other_case = client.get(
        f"/api/v1/cases/{CASE}/proposal/document",
        headers={"X-Demo-Cases": "Other-Case", "X-Demo-User": "another-reviewer"},
    )
    assert other_case.status_code == 404
    other_tenant = client.get(
        f"/api/v1/cases/{CASE}/proposal", headers={**H, "X-Demo-Tenant": "another"}
    )
    assert other_tenant.status_code == 404


def test_free_text_case_shows_not_available(client: TestClient) -> None:
    client.post(
        "/api/v1/cases",
        json={
            "external_case_id": "UW-PROP-LEG",
            "applicant_display_name": "Legacy",
            "proposal_number": "P-LEG",
            "product_name": "Some plan",
        },
    )
    view = client.get("/api/v1/cases/UW-PROP-LEG/proposal").json()
    data = items(view)
    assert data["product_name"]["value"] == "Some plan"
    assert data["product_name"]["source"] == "case_record"
    for key in ("insurer", "sum_assured", "annual_premium", "cover_type", "death_benefit"):
        assert data[key]["value"] is None, key
