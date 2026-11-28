from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from idp.config import Settings
from idp.models import Base, Case, UnderwritingVariance


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._ensure_sqlite_parent(settings.database_url)
        engine_kwargs: dict = {"pool_pre_ping": True}
        if settings.database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if settings.database_url in {"sqlite://", "sqlite:///:memory:"}:
                engine_kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(settings.database_url, **engine_kwargs)
        if settings.database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    @staticmethod
    def _ensure_sqlite_parent(database_url: str) -> None:
        prefix = "sqlite:///"
        if database_url.startswith(prefix) and database_url not in {
            "sqlite:///:memory:",
            "sqlite:///file::memory:?cache=shared",
        }:
            raw_path = database_url[len(prefix) :].split("?", 1)[0]
            if raw_path:
                Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        self._upgrade_schema()

    def _upgrade_schema(self) -> None:
        with self.engine.begin() as connection:
            inspector = inspect(connection)
            if inspector.has_table("extraction_runs"):
                columns = {column["name"] for column in inspector.get_columns("extraction_runs")}
                if "configuration_checksum" not in columns:
                    connection.execute(
                        text(
                            "ALTER TABLE extraction_runs "
                            "ADD COLUMN configuration_checksum VARCHAR(80) "
                            "NOT NULL DEFAULT 'legacy-unavailable'"
                        )
                    )
                if "ai_analysis_json" not in columns:
                    connection.execute(
                        text("ALTER TABLE extraction_runs ADD COLUMN ai_analysis_json JSON")
                    )
            if inspector.has_table("cases"):
                case_columns = {column["name"] for column in inspector.get_columns("cases")}
                if "created_by" not in case_columns:
                    connection.execute(text("ALTER TABLE cases ADD COLUMN created_by VARCHAR(200)"))
                if "is_demo" not in case_columns:
                    connection.execute(
                        text("ALTER TABLE cases ADD COLUMN is_demo BOOLEAN NOT NULL DEFAULT FALSE")
                    )
                if "product_id" not in case_columns:
                    connection.execute(text("ALTER TABLE cases ADD COLUMN product_id VARCHAR(100)"))
                if "policy_details_json" not in case_columns:
                    connection.execute(text("ALTER TABLE cases ADD COLUMN policy_details_json JSON"))

    @contextmanager
    def session(self) -> Iterator[Session]:
        db = self.session_factory()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def dispose(self) -> None:
        self.engine.dispose()


def seed_demo_case(db: Database, settings: Settings) -> Case:
    with db.session() as session:
        demo_case_id = next(
            (case_id.strip() for case_id in settings.demo_case_ids.split(",") if case_id.strip()),
            None,
        )
        if demo_case_id is None:
            raise ValueError("demo_case_ids must contain at least one case identifier")
        existing = session.scalar(
            select(Case).where(
                Case.tenant_id == settings.demo_tenant_id,
                Case.external_case_id == demo_case_id,
            )
        )
        if existing:
            return existing
        demo_case = Case(
            tenant_id=settings.demo_tenant_id,
            external_case_id=demo_case_id,
            applicant_display_name="Aarav Mehta",
            proposal_number="MMIL-PROP-00018492",
            product_name="Mahindra Manulife Life Protect Plus",
            workflow_stage="human_review",
            sla_label="2d 04h left",
        )
        session.add(demo_case)
        session.flush()
        return demo_case


def seed_demo_variance_case(db: Database, settings: Settings) -> Case:
    if settings.environment == "production" or settings.auth_mode != "demo":
        raise ValueError(
            "The variance demo case is only available in non-production demo auth mode."
        )

    external_case_id = "MMIL-DEMO-001"
    with db.session() as session:
        existing = session.scalar(
            select(Case).where(
                Case.tenant_id == settings.demo_tenant_id,
                Case.external_case_id == external_case_id,
            )
        )
        if existing is not None:
            if not existing.is_demo:
                raise ValueError("The reserved demo case ID belongs to a non-demo case.")
            if (
                session.scalar(
                    select(UnderwritingVariance.id).where(
                        UnderwritingVariance.tenant_id == settings.demo_tenant_id,
                        UnderwritingVariance.case_id == existing.id,
                        UnderwritingVariance.category == "premium",
                    )
                )
                is None
            ):
                session.add(
                    UnderwritingVariance(
                        tenant_id=settings.demo_tenant_id,
                        case_id=existing.id,
                        category="premium",
                        title="Premium Variance",
                        applied_value=50000,
                        suggested_value=60000,
                        currency="INR",
                        recommendation_source="DEMO – Simulated Approved Pricing Recommendation",
                        recommendation_rationale=(
                            "For demonstration purposes, the configured demo recommendation "
                            "indicates a higher premium than the applicant's original applied "
                            "premium. The underwriter must review the recommendation and record "
                            "an outcome. This is not a real pricing calculation or insurance quote."
                        ),
                    )
                )
            return existing

        demo_case = Case(
            tenant_id=settings.demo_tenant_id,
            external_case_id=external_case_id,
            applicant_display_name="Ananya Sharma",
            proposal_number="MMIL-DEMO-001",
            product_name="Individual Life Insurance",
            created_by=settings.demo_user_id,
            is_demo=True,
            workflow_stage="underwriting_variance_review",
            sla_label="Demo only — not an SLA",
        )
        session.add(demo_case)
        session.flush()
        session.add(
            UnderwritingVariance(
                tenant_id=settings.demo_tenant_id,
                case_id=demo_case.id,
                category="premium",
                title="Premium Variance",
                applied_value=50000,
                suggested_value=60000,
                currency="INR",
                recommendation_source="DEMO – Simulated Approved Pricing Recommendation",
                recommendation_rationale=(
                    "For demonstration purposes, the configured demo recommendation indicates "
                    "a higher premium than the applicant's original applied premium. The "
                    "underwriter must review the recommendation and record an outcome. This is "
                    "not a real pricing calculation or insurance quote."
                ),
            )
        )
        session.flush()
        return demo_case
