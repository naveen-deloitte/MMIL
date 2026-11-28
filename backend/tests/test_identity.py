from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from idp.config import Settings
from idp.identity.aadhaar_verifier import (
    AadhaarVerificationRequest,
    NotConfiguredAadhaarVerifier,
    UidaiOfflineQrVerifier,
    build_aadhaar_verifier,
)
from idp.identity.identity_matcher import (
    SourceValue,
    compare_dates,
    compare_names,
    match_identity,
)
from idp.identity.identity_validator import (
    validate_aadhaar_number,
    validate_date_of_birth,
    validate_pan_number,
)
from idp.identity.masking import (
    mask_aadhaar,
    mask_pan,
    mask_text,
    verhoeff_generate,
    verhoeff_is_valid,
)
from idp.identity.pan_verifier import (
    HttpPanVerifier,
    NotConfiguredPanVerifier,
    PanVerificationRequest,
    build_pan_verifier,
)
from idp.identity.verification_types import Consent
from idp.models import (
    AuditEvent,
    DocumentPage,
    ExtractedField,
    IdentityVerification,
)
from idp.services.processing import ProcessingService

CASE_ID = "Dummy-Dummy-29495"
_BASE = "23456789012"
AADHAAR = _BASE + verhoeff_generate(_BASE)  # fictional, checksum-valid
AADHAAR_SPACED = f"{AADHAAR[:4]} {AADHAAR[4:8]} {AADHAAR[8:]}"
PAN = "ABCPE1234F"  # fictional, holder category P (individual)


def make_pdf(lines: list[str]) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    y = 60
    for line in lines:
        page.insert_text((50, y), line, fontsize=11)
        y += 22
    content = document.tobytes()
    document.close()
    return content


def aadhaar_lines(name: str = "Rahul Sharma", number: str = AADHAAR_SPACED) -> list[str]:
    return [
        "Government of India",
        name,
        "DOB: 01/01/1990",
        "MALE",
        number,
        "Address: 12 MG Road",
        "Bengaluru Karnataka 560001",
    ]


def pan_lines(name: str = "RAHUL SHARMA", number: str = PAN) -> list[str]:
    return [
        "INCOME TAX DEPARTMENT",
        "Permanent Account Number",
        number,
        "Name",
        name,
        "Father's Name",
        "SURESH SHARMA",
        "Date of Birth",
        "01/01/1990",
        "Signature",
    ]


def kyc_lines(surname: str = "Sharma", first: str = "Rahul", dob: str = "01/01/1990") -> list[str]:
    return [
        "Individual KYC Form",
        f"Surname: {surname}",
        f"First Name: {first}",
        f"Date of Birth: {dob}",
        "Gender: Male",
        "Residential Address: 12 MG Road Bengaluru Karnataka 560001",
    ]


def upload(client: TestClient, lines: list[str], document_type: str, key: str, headers=None):
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/documents",
        headers={"Idempotency-Key": f"identity-test-{key}", **(headers or {})},
        files={"file": (f"{document_type}.pdf", make_pdf(lines), "application/pdf")},
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


def summary(client: TestClient, headers=None) -> dict:
    response = client.get(f"/api/v1/cases/{CASE_ID}/identity/summary", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- masking and validation


def test_verhoeff_and_aadhaar_validation() -> None:
    assert verhoeff_is_valid(AADHAAR)
    assert not verhoeff_is_valid(AADHAAR[:-1] + str((int(AADHAAR[-1]) + 1) % 10))
    assert validate_aadhaar_number(AADHAAR)[0]["code"] == "aadhaar_format_valid"
    assert "not proof" in validate_aadhaar_number(AADHAAR)[0]["message"]
    bad = AADHAAR[:-1] + str((int(AADHAAR[-1]) + 1) % 10)
    assert validate_aadhaar_number(bad)[0]["code"] == "aadhaar_checksum_invalid"
    assert validate_aadhaar_number("123456789012")[0]["code"] == "aadhaar_format_invalid"


def test_masked_aadhaar_is_not_invalid() -> None:
    result = validate_aadhaar_number("XXXXXXXX9012")
    assert result[0]["code"] == "aadhaar_masked"
    assert result[0]["severity"] == "info"


def test_pan_validation() -> None:
    assert validate_pan_number("ABCDE1234F")[0]["code"] == "pan_format_valid"
    assert [f["code"] for f in validate_pan_number(PAN)] == ["pan_format_valid"]
    assert validate_pan_number("ABCD1234EF")[0]["code"] == "pan_format_invalid"


def test_date_validation() -> None:
    assert validate_date_of_birth("1990-01-01") == []
    assert validate_date_of_birth("2999-01-01")[0]["code"] == "date_in_future"
    assert validate_date_of_birth("not-a-date")[0]["code"] == "date_invalid"


def test_masking_functions() -> None:
    assert mask_aadhaar(AADHAAR) == f"XXXX XXXX {AADHAAR[-4:]}"
    assert mask_pan(PAN) == "XXXXXX234F"
    text = mask_text(f"No {AADHAAR_SPACED} and {PAN} here")
    assert AADHAAR not in text.replace(" ", "")
    assert PAN not in text
    assert mask_text("VID 1234 5678 9012 3456") == "VID XXXX XXXX XXXX 3456"
    assert mask_text("1234:22343977") == "XXXX XXXX 3977"
    assert mask_text("1234F:22343977") == "1234F:XXXX3977"


def test_side_by_side_card_columns_are_read_separately() -> None:
    from idp.extraction.text import PageText, TextBlock
    from idp.identity.layout import reorder_card_columns

    # Front at x 20-470, back at x 520-960; OCR emitted rows across both sides.
    blocks = [
        TextBlock("Government of India", 150, 40, 300, 55),
        TextBlock("Unique Identification Authority", 600, 42, 900, 57),
        TextBlock("RAHUL SINGH", 530, 100, 640, 115),
        TextBlock("RAHUL SINGH", 180, 104, 290, 119),
        TextBlock("S/O: Suresh Singh", 530, 122, 660, 137),
        TextBlock("DOB: 01/01/1990", 180, 126, 400, 141),
        TextBlock("Flat 201, Green View", 530, 144, 760, 159),
        TextBlock("MALE", 180, 148, 260, 163),
        TextBlock("New Delhi - 110085", 530, 190, 700, 205),
    ]
    page = PageText(1, "\n".join(b.text for b in blocks), 972, 334, blocks, ocr_used=True)
    text = reorder_card_columns([page])[0].text.splitlines()
    assert text == [
        "Government of India",
        "RAHUL SINGH",
        "DOB: 01/01/1990",
        "MALE",
        "Unique Identification Authority",
        "RAHUL SINGH",
        "S/O: Suresh Singh",
        "Flat 201, Green View",
        "New Delhi - 110085",
    ]
    single = PageText(1, "a\nb", 972, 334, blocks[:2], ocr_used=False)
    assert reorder_card_columns([single])[0] is single
    assert mask_text("DOB: 01/01/1990") == "DOB: 01/01/1990"


def test_ocr_shaped_aadhaar_text_extracts_and_flags_16_digit_number() -> None:
    """Lines as RapidOCR returns them for a two-sided card image (fictional values)."""
    from idp.document_types import DocumentTypeRegistry
    from idp.extraction.engine import SchemaExtractor
    from idp.extraction.text import PageText
    from idp.identity.postprocess import finalize_identity_extraction

    lines = [
        "Government of India",
        "Aadhaar no. issued: 22/01/2015",
        "RAHUL SINGH",
        ":01/01/1990/DOB: 01/01/1990",
        "/MALE",
        "1234 5678 1234 3977",
        "RAHUL SINGH",
        "S/O: Suresh Singh",
        "Flat 201, Green View Apartmens,",
        "Rohini Sector-13,",
        "New Delhi - 110085",
        "1234:22343977",
    ]
    page = PageText(1, "\n".join(lines), 972, 334, engine="rapidocr", ocr_used=True, confidence=0.95)
    definition = DocumentTypeRegistry.load_catalog(
        Path(__file__).resolve().parents[2] / "config" / "document-types"
    ).for_type("aadhaar_card").definition
    candidates = SchemaExtractor(definition).extract(document_id="d", document_version=1, pages=[page])
    candidates, pages = finalize_identity_extraction("aadhaar_card", candidates, [page])
    by_path = {c.field_path: c for c in candidates}

    assert by_path["identity.full_name"].normalized_value == "RAHUL SINGH"
    assert by_path["identity.full_name"].status == "found"
    assert by_path["identity.date_of_birth"].normalized_value == "1990-01-01"
    assert by_path["identity.gender"].normalized_value == "Male"
    assert by_path["identity.address"].normalized_value == (
        "Flat 201, Green View Apartmens, Rohini Sector-13, New Delhi - 110085"
    )
    assert by_path["document.issue_context"].normalized_value == "2015-01-22"
    number = by_path["identity.aadhaar_number"]
    assert number.normalized_value == "XXXX XXXX XXXX 3977"
    assert "aadhaar_format_invalid" in {v["code"] for v in number.validations}
    stored = json.dumps(
        [pages[0].text, [(c.source_literal, c.normalized_value) for c in candidates],
         [x.excerpt for c in candidates for x in c.citations]]
    )
    assert "5678" not in stored and "22343977" not in stored


# ---------------------------------------------------------------- matching


def test_name_comparison_rules() -> None:
    assert compare_names("Rahul Sharma", "Rahul Sharma")[0] == "match"
    assert compare_names("Rahul Sharma", "RAHUL  SHARMA")[0] == "normalized_match"
    assert compare_names("Rahul Sharma", "Sharma, Rahul")[0] == "normalized_match"
    assert compare_names("Rahul Sharma", "R. Sharma")[0] == "review_required"
    assert compare_names("Rahul Sharma", "Rahul Kumar Sharma")[0] == "review_required"
    assert compare_names("Rahul Sharma", "Rahul Verma")[0] == "mismatch"
    assert compare_names("Rahul Sharma", "Amit Verma")[0] == "mismatch"


def test_date_comparison_rules() -> None:
    same = compare_dates(SourceValue("1990-01-01"), SourceValue("01/01/1990"))
    assert same[0] == "normalized_match"
    assert compare_dates(SourceValue("1990-01-01"), SourceValue("1991-01-01"))[0] == "mismatch"
    year_only = compare_dates(SourceValue(None, year_of_birth=1990), SourceValue("1990-01-01"))
    assert year_only[0] == "review_required"


def test_missing_documents_are_not_mismatches() -> None:
    rows = match_identity(
        {"kyc": {"full_name": SourceValue("Rahul Sharma")}},
        documents_present={"kyc": True, "aadhaar": False, "pan": False},
    )
    by_field = {row["field"]: row for row in rows}
    assert by_field["full_name"]["match_status"] == "not_available"
    assert by_field["full_name"]["missing_sources"] == ["aadhaar", "pan"]
    assert by_field["gender"]["not_applicable_sources"] == ["pan"]


def test_uncertain_extraction_requires_review() -> None:
    rows = match_identity(
        {
            "kyc": {"full_name": SourceValue("Rahul Sharma")},
            "aadhaar": {"full_name": SourceValue("Rahul Sharma", uncertain=True)},
        },
        documents_present={"kyc": True, "aadhaar": True, "pan": False},
    )
    assert next(r for r in rows if r["field"] == "full_name")["match_status"] == "review_required"


# ---------------------------------------------------------------- verification adapters


def _settings(**overrides) -> Settings:
    return Settings(environment="test", _env_file=None, **overrides)


def test_providers_default_to_not_configured() -> None:
    settings = _settings()
    aadhaar = build_aadhaar_verifier(settings)
    pan = build_pan_verifier(settings)
    assert isinstance(aadhaar, NotConfiguredAadhaarVerifier)
    assert isinstance(pan, NotConfiguredPanVerifier)
    consent = Consent(given=True)
    assert aadhaar.verify(AadhaarVerificationRequest(None, consent)).status == "not_configured"
    assert pan.verify(PanVerificationRequest(PAN, consent)).status == "not_configured"


def test_aadhaar_offline_provider_without_trust_material_is_not_configured(tmp_path) -> None:
    settings = _settings(identity_aadhaar_provider="uidai-offline-qr")
    assert isinstance(build_aadhaar_verifier(settings), NotConfiguredAadhaarVerifier)
    cert = tmp_path / "cert.pem"
    cert.write_bytes(b"cert")
    settings = _settings(
        identity_aadhaar_provider="uidai-offline-qr", identity_aadhaar_trust_cert_path=cert
    )
    # Certificate without a reviewed signature validator still never reports verified.
    assert isinstance(build_aadhaar_verifier(settings), NotConfiguredAadhaarVerifier)


def test_aadhaar_signature_results_use_mocked_validator() -> None:
    consent = Consent(given=True)
    ok = UidaiOfflineQrVerifier(trust_certificate=b"c", validator=lambda p, c: True)
    assert ok.verify(AadhaarVerificationRequest(b"payload", consent)).status == "verified"
    bad = UidaiOfflineQrVerifier(trust_certificate=b"c", validator=lambda p, c: False)
    result = bad.verify(AadhaarVerificationRequest(b"payload", consent))
    assert (result.status, result.reason_code) == ("failed", "signature_validation_failed")

    def malformed(payload: bytes, cert: bytes) -> bool:
        raise ValueError("malformed")

    assert (
        UidaiOfflineQrVerifier(trust_certificate=b"c", validator=malformed)
        .verify(AadhaarVerificationRequest(b"x", consent))
        .reason_code
        == "qr_payload_malformed"
    )
    missing = ok.verify(AadhaarVerificationRequest(b"payload", Consent(given=False)))
    assert missing.status == "consent_missing"
    assert ok.verify(AadhaarVerificationRequest(None, consent)).status == "not_configured"


def _pan_verifier(handler, retries: int = 2) -> HttpPanVerifier:
    return HttpPanVerifier(
        endpoint="https://provider.example/verify",
        api_key="test-key",
        timeout=1.0,
        max_retries=retries,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_pan_provider_success_and_failure() -> None:
    consent = Consent(given=True)
    ok = _pan_verifier(lambda r: httpx.Response(200, json={"status": "valid", "name_match": True}))
    result = ok.verify(PanVerificationRequest(PAN, consent))
    assert result.status == "verified" and result.details == {"name_match": True}
    bad = _pan_verifier(lambda r: httpx.Response(200, json={"status": "invalid"}))
    assert bad.verify(PanVerificationRequest(PAN, consent)).status == "failed"


def test_pan_provider_invalid_response_timeout_retry_and_consent() -> None:
    consent = Consent(given=True)
    junk = _pan_verifier(lambda r: httpx.Response(200, json={"unexpected": 1}))
    assert junk.verify(PanVerificationRequest(PAN, consent)).reason_code == "invalid_provider_response"
    not_json = _pan_verifier(lambda r: httpx.Response(200, text="<html>"))
    assert not_json.verify(PanVerificationRequest(PAN, consent)).status == "provider_error"

    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"status": "valid"})

    result = _pan_verifier(flaky, retries=2).verify(PanVerificationRequest(PAN, consent))
    assert result.status == "verified" and result.attempts == 3

    calls["n"] = -100
    timed_out = _pan_verifier(flaky, retries=1).verify(PanVerificationRequest(PAN, consent))
    assert (timed_out.status, timed_out.reason_code) == ("provider_error", "provider_timeout")

    refused = _pan_verifier(lambda r: httpx.Response(403))
    assert refused.verify(PanVerificationRequest(PAN, consent)).reason_code == "provider_rejected_403"
    no_consent = _pan_verifier(lambda r: httpx.Response(200, json={"status": "valid"}))
    assert no_consent.verify(PanVerificationRequest(PAN, Consent(given=False))).status == (
        "consent_missing"
    )
    assert "ABCPE" not in repr(PanVerificationRequest(PAN, consent))


# ---------------------------------------------------------------- end to end


def test_identity_documents_extract_masked_and_never_store_full_numbers(
    client: TestClient, app, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    aadhaar = upload(client, aadhaar_lines(), "aadhaar_card", "aadhaar-1")
    pan = upload(client, pan_lines(), "pan_card", "pan-1")
    upload(client, kyc_lines(), "kyc_individual", "kyc-1")
    process_all(app)

    data = summary(client)
    docs = {d["subject"]: d for d in data["documents"]}
    assert docs["aadhaar"]["state"] == "extracted" and docs["pan"]["state"] == "extracted"
    aadhaar_fields = {f["field_path"]: f for f in docs["aadhaar"]["fields"]}
    pan_fields = {f["field_path"]: f for f in docs["pan"]["fields"]}
    assert aadhaar_fields["identity.aadhaar_number"]["candidate_value"] == (
        f"XXXX XXXX {AADHAAR[-4:]}"
    )
    assert aadhaar_fields["identity.full_name"]["candidate_value"] == "Rahul Sharma"
    assert aadhaar_fields["identity.date_of_birth"]["candidate_value"] == "1990-01-01"
    assert aadhaar_fields["identity.gender"]["candidate_value"] == "Male"
    assert aadhaar_fields["identity.address"]["candidate_value"].endswith("560001")
    assert aadhaar_fields["identity.aadhaar_number"]["citations"][0]["page"] == 1
    codes = {v["code"] for v in aadhaar_fields["identity.aadhaar_number"]["validations"]}
    assert "aadhaar_format_valid" in codes
    assert pan_fields["identity.pan_number"]["candidate_value"] == "XXXXXX234F"
    assert pan_fields["identity.full_name"]["candidate_value"] == "RAHUL SHARMA"
    assert pan_fields["identity.father_name"]["candidate_value"] == "SURESH SHARMA"
    assert pan_fields["identity.pan_holder_category"]["candidate_value"] == "Individual"

    # Distinct states: extraction and format validation never imply verification.
    assert data["stages"]["authenticity_verified"] == {
        "aadhaar": "not_verified",
        "pan": "not_verified",
    }
    assert data["stages"]["human_review_completed"] == "not_started"
    assert data["stages"]["format_validated"]["aadhaar"] == "passed"
    assert data["match_status"] == "match"

    # Full identifiers must not appear in stored data, API responses or logs.
    with app.state.database.session() as session:
        stored = json.dumps(
            [
                [p.text, p.blocks_json]
                for p in session.scalars(select(DocumentPage))
            ]
            + [
                [f.source_literal, f.normalized_value_json, f.validation_json, f.citations_json]
                for f in session.scalars(select(ExtractedField))
            ]
            + [e.metadata_json for e in session.scalars(select(AuditEvent))],
            default=str,
        )
    for text in (stored, json.dumps(data), caplog.text):
        assert AADHAAR not in text.replace(" ", "")
        assert PAN not in text
    assert aadhaar["document_type"] == "aadhaar_card" and pan["document_type"] == "pan_card"


def test_mismatch_is_flagged_routed_to_review_and_kyc_unchanged(
    client: TestClient, app
) -> None:
    upload(client, aadhaar_lines(name="Rahul Sharma"), "aadhaar_card", "aadhaar-2")
    kyc = upload(client, kyc_lines(surname="Verma", first="Amit", dob="02/02/1985"), "kyc_individual", "kyc-2")
    process_all(app)

    before = client.get(f"/api/v1/documents/{kyc['id']}/extractions/latest").json()
    response = client.post(f"/api/v1/cases/{CASE_ID}/identity/verify", json={})
    assert response.status_code == 200, response.text
    data = response.json()["summary"]
    rows = {m["field"]: m for m in data["matches"]}
    assert rows["full_name"]["match_status"] == "mismatch"
    assert rows["date_of_birth"]["match_status"] == "mismatch"
    assert data["match_status"] == "mismatch"
    assert any(i["category"] == "data_mismatch" for i in data["issues"])

    aadhaar_doc = next(d for d in data["documents"] if d["subject"] == "aadhaar")
    name_field = next(f for f in aadhaar_doc["fields"] if f["field_path"] == "identity.full_name")
    assert name_field["review_state"] == "pending"
    assert aadhaar_doc["document_status"] == "review_required"

    after = client.get(f"/api/v1/documents/{kyc['id']}/extractions/latest").json()
    assert before["fields"] == after["fields"]

    # Official verification was not attempted: nothing is reported as verified.
    statuses = {v["subject"]: v["status"] for v in data["verification"]}
    assert statuses == {"aadhaar": "not_configured", "pan": "not_verified"}
    assert "verified" not in statuses.values()
    # Repeating is idempotent: no duplicate verification rows.
    second = client.post(f"/api/v1/cases/{CASE_ID}/identity/verify", json={}).json()
    assert second["reused_existing"] == ["aadhaar"]
    with app.state.database.session() as session:
        assert len(list(session.scalars(select(IdentityVerification)))) == 1

    # Confirming with open mismatches requires explicit resolution and rationale.
    bad = client.post(
        f"/api/v1/cases/{CASE_ID}/identity/review", json={"decision": "confirmed"}
    )
    assert bad.status_code == 422
    good = client.post(
        f"/api/v1/cases/{CASE_ID}/identity/review",
        json={
            "decision": "confirmed",
            "rationale": "Checked originals; KYC form keyed incorrectly.",
            "resolved_fields": ["full_name", "date_of_birth"],
        },
    )
    assert good.status_code == 200, good.text
    assert good.json()["review"]["status"] == "completed"
    assert good.json()["stages"]["authenticity_verified"]["aadhaar"] == "not_configured"


def test_missing_pan_is_not_a_mismatch(client: TestClient, app) -> None:
    upload(client, aadhaar_lines(), "aadhaar_card", "aadhaar-3")
    process_all(app)
    data = summary(client)
    assert data["match_status"] != "mismatch"
    assert any(i["code"] == "document_missing" and i["subject"] == "pan" for i in data["issues"])
    assert not any(i["category"] == "data_mismatch" for i in data["issues"])


def test_invalid_pan_format_is_flagged(client: TestClient, app) -> None:
    upload(client, pan_lines(number="ABCD12345E"), "pan_card", "pan-bad")
    process_all(app)
    data = summary(client)
    pan = next(d for d in data["documents"] if d["subject"] == "pan")
    number = next(f for f in pan["fields"] if f["field_path"] == "identity.pan_number")
    assert "pan_format_invalid" in {v["code"] for v in number["validations"]}
    assert number["review_state"] == "pending"
    assert data["stages"]["format_validated"]["pan"] == "failed"


def test_image_without_ocr_fails_with_actionable_message(client: TestClient, app) -> None:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 80), False)
    pixmap.clear_with(255)
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/documents",
        headers={"Idempotency-Key": "identity-test-img-1"},
        files={"file": ("aadhaar.png", pixmap.tobytes("png"), "image/png")},
        data={"document_type": "aadhaar_card"},
    )
    assert response.status_code == 202, response.text
    process_all(app)
    data = summary(client)
    aadhaar = next(d for d in data["documents"] if d["subject"] == "aadhaar")
    assert aadhaar["state"] == "failed"
    assert aadhaar["failure_code"] == "ocr_unavailable"
    assert "IDP_OCR_PROVIDER" in aadhaar["action_required"]
    assert aadhaar["fields"] == []


def test_identity_access_controls(client: TestClient, app) -> None:
    upload(client, aadhaar_lines(), "aadhaar_card", "aadhaar-4")
    process_all(app)
    other_tenant = {"X-Demo-Tenant": "another-tenant"}
    assert (
        client.get(f"/api/v1/cases/{CASE_ID}/identity/summary", headers=other_tenant).status_code
        == 404
    )
    no_case = {"X-Demo-Cases": "Some-Other-Case"}
    assert (
        client.get(f"/api/v1/cases/{CASE_ID}/identity/summary", headers=no_case).status_code
        == 404
    )
    operator = {"X-Demo-Role": "operator"}
    assert (
        client.post(
            f"/api/v1/cases/{CASE_ID}/identity/verify", json={}, headers=operator
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/cases/{CASE_ID}/identity/review",
            json={"decision": "confirmed"},
            headers=operator,
        ).status_code
        == 403
    )


def test_corrected_identifier_is_stored_masked(client: TestClient, app) -> None:
    doc = upload(client, aadhaar_lines(), "aadhaar_card", "aadhaar-5")
    process_all(app)
    fields = client.get(f"/api/v1/documents/{doc['id']}/extractions/latest").json()["fields"]
    number = next(f for f in fields if f["field_path"] == "identity.aadhaar_number")
    response = client.post(
        f"/api/v1/documents/{doc['id']}/reviews",
        json={
            "decisions": [
                {
                    "field_id": number["id"],
                    "decision": "corrected",
                    "expected_version": number["review_version"],
                    "corrected_value": "3456 7890 1234",
                    "rationale": "OCR misread; original shows 3456 7890 1234",
                }
            ]
        },
    )
    assert response.status_code == 200, response.text
    body = json.dumps(response.json())
    assert "345678901234" not in body.replace(" ", "")
    assert response.json()["reviews"][0]["after_value"] == "XXXX XXXX 1234"


def test_verify_validates_payload(client: TestClient, app) -> None:
    upload(client, pan_lines(), "pan_card", "pan-5")
    process_all(app)
    bad = client.post(f"/api/v1/cases/{CASE_ID}/identity/verify", json={"pan_number": "123"})
    assert bad.status_code == 422
    assert "123" not in bad.text
    bad_qr = client.post(
        f"/api/v1/cases/{CASE_ID}/identity/verify", json={"qr_payload_base64": "***"}
    )
    assert bad_qr.status_code == 422


def test_pan_verification_uses_injected_provider_and_requires_consent(
    client: TestClient, app
) -> None:
    upload(client, pan_lines(), "pan_card", "pan-6")
    process_all(app)
    app.state.pan_verifier = _pan_verifier(
        lambda r: httpx.Response(200, json={"status": "valid"})
    )
    no_consent = client.post(
        f"/api/v1/cases/{CASE_ID}/identity/verify",
        json={"subjects": ["pan"], "pan_number": PAN},
    ).json()["summary"]
    assert next(v for v in no_consent["verification"] if v["subject"] == "pan")["status"] == (
        "consent_missing"
    )
    done = client.post(
        f"/api/v1/cases/{CASE_ID}/identity/verify",
        json={
            "subjects": ["pan"],
            "pan_number": PAN,
            "consent": {"given": True, "purpose": "KYC identity verification"},
        },
    ).json()["summary"]
    pan = next(v for v in done["verification"] if v["subject"] == "pan")
    assert pan["status"] == "verified" and pan["consent_given"] is True
    assert PAN not in json.dumps(done)
    with app.state.database.session() as session:
        events = [e.metadata_json for e in session.scalars(select(AuditEvent))]
    assert any(e.get("verification_status") == "verified" for e in events)
    assert PAN not in json.dumps(events)

    mismatch = client.post(
        f"/api/v1/cases/{CASE_ID}/identity/verify",
        json={"subjects": ["pan"], "pan_number": "ZZZZZ9999Z", "consent": {"given": True}},
    )
    assert mismatch.status_code == 422


@pytest.mark.parametrize("subject", ["aadhaar", "pan"])
def test_extra_verify_subjects_rejected(client: TestClient, subject: str) -> None:
    response = client.post(
        f"/api/v1/cases/{CASE_ID}/identity/verify", json={"subjects": [subject, "passport"]}
    )
    assert response.status_code == 422
