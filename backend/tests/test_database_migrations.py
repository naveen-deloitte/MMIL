from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from idp.config import Settings
from idp.database import Database

ROOT = Path(__file__).resolve().parents[2]


def test_create_schema_adds_missing_extraction_checksum_without_dropping_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy.db"
    legacy_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with legacy_engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE extraction_runs "
                "(id VARCHAR(36) PRIMARY KEY NOT NULL)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE cases ("
                "id VARCHAR(36) PRIMARY KEY NOT NULL, "
                "tenant_id VARCHAR(100) NOT NULL, "
                "external_case_id VARCHAR(100) NOT NULL, "
                "applicant_display_name VARCHAR(200) NOT NULL, "
                "proposal_number VARCHAR(100) NOT NULL, "
                "product_name VARCHAR(200) NOT NULL, "
                "workflow_stage VARCHAR(50) NOT NULL, "
                "sla_label VARCHAR(100) NOT NULL, "
                "created_at DATETIME NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO extraction_runs (id) VALUES ('legacy-run')")
        )
        connection.execute(
            text(
                "INSERT INTO cases (id, tenant_id, external_case_id, "
                "applicant_display_name, proposal_number, product_name, workflow_stage, "
                "sla_label, created_at, updated_at) VALUES "
                "('legacy-case', 'tenant-demo', 'LEGACY-1', 'Legacy User', "
                "'PROP-1', 'Product', 'human_review', 'Not set', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            )
        )
    legacy_engine.dispose()

    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
        object_root=tmp_path / "objects",
        document_type_path=ROOT / "config" / "document-types" / "medical-report.v1.json",
        extraction_provider="deterministic-local",
        allowed_providers="deterministic-local",
    )
    database = Database(settings)
    try:
        database.create_schema()
        inspector = inspect(database.engine)
        column_names = {
            column["name"] for column in inspector.get_columns("extraction_runs")
        }
        case_column_names = {
            column["name"] for column in inspector.get_columns("cases")
        }
        with database.engine.connect() as connection:
            checksum = connection.execute(
                text(
                    "SELECT configuration_checksum FROM extraction_runs "
                    "WHERE id = 'legacy-run'"
                )
            ).scalar_one()
            ai_analysis = connection.execute(
                text("SELECT ai_analysis_json FROM extraction_runs WHERE id = 'legacy-run'")
            ).scalar_one()
            case_owner = connection.execute(
                text("SELECT created_by FROM cases WHERE id = 'legacy-case'")
            ).scalar_one()

        assert "configuration_checksum" in column_names
        assert "ai_analysis_json" in column_names
        assert checksum == "legacy-unavailable"
        assert ai_analysis is None
        assert "created_by" in case_column_names
        assert case_owner is None
    finally:
        database.dispose()
