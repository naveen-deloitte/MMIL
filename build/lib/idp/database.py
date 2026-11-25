from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from idp.config import Settings
from idp.models import Base, Case


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
        existing = session.scalar(
            select(Case).where(
                Case.tenant_id == settings.demo_tenant_id,
                Case.external_case_id == "MMIL-UW-2027-00018492",
            )
        )
        if existing:
            return existing
        demo_case = Case(
            tenant_id=settings.demo_tenant_id,
            external_case_id="MMIL-UW-2027-00018492",
            applicant_display_name="Aarav Mehta",
            proposal_number="MMIL-PROP-00018492",
            product_name="Mahindra Manulife Life Protect Plus",
            workflow_stage="human_review",
            sla_label="2d 04h left",
        )
        session.add(demo_case)
        session.flush()
        return demo_case
