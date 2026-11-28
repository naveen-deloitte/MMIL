from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from idp.api.app import create_app
from idp.config import Settings
from idp.database import Database
from idp.products.catalogue import CatalogueError, CatalogueFile, ProductCatalogue
from idp.products.pricing import QuoteInputs, calculate_quote

ROOT = Path(__file__).resolve().parents[2]

# Test-only catalogue. Values are fixtures for arithmetic checks, not product data.
CATALOGUE = {
    "catalogue_id": "test-catalogue",
    "catalogue_version": "1.0.0",
    "source": "Unit test fixture",
    "is_demo": True,
    "products": [
        {
            "product_id": "rated",
            "product_name": "Rated Term",
            "insurer": "Insurer A",
            "insurance_type": "Term",
            "entry_age_min": 18,
            "entry_age_max": 60,
            "sum_assured": {"currency": "INR", "options": [1000000, 2000000]},
            "premium_frequencies": ["annual", "monthly"],
            "policy_terms": {"options": [10, 20]},
            "premium_payment_terms": {"options": ["policy_term"]},
            "pricing": {
                "method": "rate_per_thousand_sum_assured",
                "basis_note": "fixture",
                "rating_factors": ["age", "gender", "smoker"],
                "frequency_factors": {"annual": 1.0, "monthly": 0.1},
                "tax_rate": 0.18,
                "rate_table": [
                    {"age_min": 18, "age_max": 40, "gender": "male", "smoker": False, "rate": 1.0},
                    {"age_min": 18, "age_max": 40, "gender": "male", "smoker": True, "rate": 2.0},
                    {"age_min": 18, "age_max": 40, "gender": "female", "smoker": False, "rate": 0.8},
                ],
            },
        },
        {
            "product_id": "fixed",
            "product_name": "Fixed Savings",
            "insurer": "Insurer B",
            "sum_assured": {"currency": "INR", "options": [500000]},
            "premium_frequencies": ["annual"],
            "policy_terms": {"options": [15]},
            "premium_payment_terms": {"options": [10]},
            "pricing": {
                "method": "fixed_premium_table",
                "basis_note": "fixture",
                "premiums": [
                    {"sum_assured": 500000, "premium_frequency": "annual", "amount": 40000}
                ],
            },
        },
        {
            "product_id": "unpriced",
            "product_name": "Unpriced Health",
            "insurer": "Insurer B",
            "sum_assured": {"currency": "INR", "options": [500000]},
        },
        {
            "product_id": "old",
            "product_name": "Withdrawn Plan",
            "insurer": "Insurer A",
            "status": "withdrawn",
        },
    ],
}


@pytest.fixture
def catalogue_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "products"
    directory.mkdir()
    (directory / "test.json").write_text(json.dumps(CATALOGUE), encoding="utf-8")
    return directory


@pytest.fixture
def product_client(settings: Settings, catalogue_dir: Path):
    settings.product_catalogue_path = catalogue_dir
    with TestClient(create_app(settings)) as client:
        yield client


def catalogue() -> ProductCatalogue:
    return ProductCatalogue([CatalogueFile.model_validate(CATALOGUE)])


def test_shipped_demo_catalogue_is_valid_and_flagged_demo() -> None:
    loaded = ProductCatalogue.load(ROOT / "config" / "products")
    assert loaded.files and all(item.is_demo for item in loaded.files)
    assert loaded.search("")


def test_missing_catalogue_path_gives_empty_catalogue(tmp_path: Path) -> None:
    assert ProductCatalogue.load(tmp_path / "nope").search("") == []


def test_duplicate_product_ids_rejected() -> None:
    with pytest.raises(CatalogueError):
        ProductCatalogue([CatalogueFile.model_validate(CATALOGUE)] * 2)


def test_search_matches_name_and_insurer_and_hides_withdrawn() -> None:
    items = catalogue()
    assert [p.product_id for p, _ in items.search("insurer b")] == ["fixed", "unpriced"]
    assert [p.product_id for p, _ in items.search("rated")] == ["rated"]
    assert "old" not in [p.product_id for p, _ in items.search("")]


def test_premium_depends_on_rating_inputs() -> None:
    product, _ = catalogue().get("rated")  # type: ignore[misc]
    base = dict(sum_assured=1000000, premium_frequency="annual", policy_term=10, age=30)
    male = calculate_quote(product, QuoteInputs(**base, gender="male", smoker=False))
    smoker = calculate_quote(product, QuoteInputs(**base, gender="male", smoker=True))
    female = calculate_quote(product, QuoteInputs(**base, gender="female", smoker=False))
    assert (male.amount_before_tax, male.tax_amount, male.amount) == (1000, 180, 1180)
    assert smoker.amount == 2360
    assert female.amount == 944
    monthly = calculate_quote(
        product, QuoteInputs(**{**base, "premium_frequency": "monthly"}, gender="male", smoker=False)
    )
    assert monthly.amount == 118
    assert male.as_dict()["official_quote"] is False
    assert male.as_dict()["quote_type"] == "indicative"


def test_quote_not_available_when_inputs_or_rates_missing() -> None:
    product, _ = catalogue().get("rated")  # type: ignore[misc]
    missing = calculate_quote(product, QuoteInputs(sum_assured=1000000, premium_frequency="annual"))
    assert missing.status == "not_available"
    assert missing.missing_inputs == ["age", "gender", "smoker"]
    no_rate = calculate_quote(
        product,
        QuoteInputs(sum_assured=1000000, premium_frequency="annual", age=30, gender="female", smoker=True),
    )
    assert no_rate.status == "not_available" and no_rate.amount is None
    too_old = calculate_quote(
        product,
        QuoteInputs(sum_assured=1000000, premium_frequency="annual", age=70, gender="male", smoker=False),
    )
    assert "maximum entry age" in too_old.reasons[0]
    bad_sa = calculate_quote(product, QuoteInputs(sum_assured=1234, premium_frequency="annual"))
    assert "permitted" in bad_sa.reasons[0]
    unpriced, _ = catalogue().get("unpriced")  # type: ignore[misc]
    assert calculate_quote(unpriced, QuoteInputs(sum_assured=500000)).status == "not_available"


def test_product_api_list_detail_and_quote(product_client: TestClient) -> None:
    listing = product_client.get("/api/v1/products", params={"q": "term"}).json()
    assert [item["product_id"] for item in listing["items"]] == ["rated"]
    assert listing["demo_catalogue"] is True
    detail = product_client.get("/api/v1/products/unpriced").json()
    assert detail["pricing_available"] is False
    assert detail["premium_frequencies"] is None and detail["policy_terms"] is None
    quote = product_client.post(
        "/api/v1/products/rated/quote",
        json={
            "sum_assured": 2000000,
            "premium_frequency": "annual",
            "policy_term": 20,
            "rating": {"age": 25, "gender": "male", "smoker": False},
        },
    ).json()
    assert quote["status"] == "indicative" and quote["amount"] == 2360
    assert quote["inputs_used"]["sum_assured"] == 2000000
    assert product_client.get("/api/v1/products/missing").status_code == 404


def test_case_persists_product_and_server_computed_quote(product_client: TestClient) -> None:
    response = product_client.post(
        "/api/v1/cases",
        json={
            "external_case_id": "UW-PROD-1",
            "applicant_display_name": "Test Applicant",
            "proposal_number": "P-1",
            "product_name": "Something the client typed",
            "product": {
                "product_id": "rated",
                "sum_assured": 1000000,
                "premium_frequency": "annual",
                "policy_term": 10,
                "rating": {"age": 30, "gender": "male", "smoker": False},
            },
        },
    )
    assert response.status_code == 201, response.text
    case = response.json()
    assert case["product_id"] == "rated"
    assert case["product_name"] == "Rated Term"
    details = case["policy_details"]
    assert details["insurer"] == "Insurer A"
    assert details["premium_payment_term"] == 10  # "policy_term" option resolves to the term
    assert details["indicative_quote"]["amount"] == 1180
    assert details["indicative_quote"]["official_quote"] is False
    assert details["catalogue"]["catalogue_version"] == "1.0.0"
    listed = product_client.get("/api/v1/cases").json()
    assert any(item["case"]["product_id"] == "rated" for item in listed)


def test_single_option_selections_are_filled_from_catalogue(product_client: TestClient) -> None:
    response = product_client.post(
        "/api/v1/cases",
        json={
            "external_case_id": "UW-PROD-2",
            "applicant_display_name": "Test",
            "proposal_number": "P-2",
            "product": {"product_id": "fixed"},
        },
    )
    details = response.json()["policy_details"]
    assert (details["sum_assured"], details["premium_frequency"]) == (500000, "annual")
    assert (details["policy_term"], details["premium_payment_term"]) == (15, 10)
    assert details["indicative_quote"]["amount"] == 40000


@pytest.mark.parametrize(
    ("product", "code"),
    [
        ({"product_id": "rated", "sum_assured": 7}, "product_selection_invalid"),
        ({"product_id": "rated", "premium_frequency": "quarterly"}, "product_selection_invalid"),
        ({"product_id": "old"}, "product_withdrawn"),
        ({"product_id": "nope"}, "product_not_found"),
    ],
)
def test_case_rejects_invalid_product_selection(
    product_client: TestClient, product: dict, code: str
) -> None:
    response = product_client.post(
        "/api/v1/cases",
        json={
            "external_case_id": "UW-PROD-X",
            "applicant_display_name": "Test",
            "proposal_number": "P-X",
            "product": product,
        },
    )
    assert response.json()["code"] == code


def test_case_requires_a_product_and_keeps_legacy_free_text(product_client: TestClient) -> None:
    base = {"external_case_id": "UW-LEG-1", "applicant_display_name": "A", "proposal_number": "P"}
    assert product_client.post("/api/v1/cases", json=base).status_code == 422
    legacy = product_client.post("/api/v1/cases", json={**base, "product_name": "Term Plan"})
    assert legacy.status_code == 201
    assert legacy.json()["product_id"] is None and legacy.json()["policy_details"] is None


def test_existing_cases_table_gets_product_columns(tmp_path: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE cases (id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(100) NOT NULL, "
                "external_case_id VARCHAR(100) NOT NULL, applicant_display_name VARCHAR(200) NOT NULL, "
                "proposal_number VARCHAR(100) NOT NULL, product_name VARCHAR(200) NOT NULL, "
                "workflow_stage VARCHAR(50) NOT NULL, sla_label VARCHAR(100) NOT NULL, "
                "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO cases VALUES ('c1','t','UW-OLD','Old','P','Plan','human_review','x',"
                "'2026-01-01','2026-01-01')"
            )
        )
    engine.dispose()
    Database(Settings(environment="test", database_url=url, _env_file=None)).create_schema()
    engine = create_engine(url)
    columns = {column["name"] for column in inspect(engine).get_columns("cases")}
    assert {"product_id", "policy_details_json"} <= columns
    with engine.connect() as connection:
        assert connection.execute(text("select product_name from cases")).scalar_one() == "Plan"
    engine.dispose()
