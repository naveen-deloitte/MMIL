from __future__ import annotations

import time

import typer

from idp.config import Settings
from idp.database import Database, seed_demo_case
from idp.document_types import DocumentTypeRegistry
from idp.services.processing import ProcessingService
from idp.storage import LocalObjectStore

app = typer.Typer(help="Run the separate medical-document processing worker.")


@app.callback(invoke_without_command=True)
def run(
    once: bool = typer.Option(False, "--once", help="Process at most one queued job and exit."),
) -> None:
    settings = Settings()
    database = Database(settings)
    database.create_schema()
    if settings.seed_demo_case:
        seed_demo_case(database, settings)
    service = ProcessingService(
        settings=settings,
        database=database,
        store=LocalObjectStore(settings.object_root),
        registry=DocumentTypeRegistry.load_catalog(settings.document_type_path),
    )
    try:
        while True:
            processed = service.process_next()
            if once:
                if processed:
                    typer.echo(f"Processed job {processed}")
                else:
                    typer.echo("No queued job")
                return
            if processed is None:
                time.sleep(settings.worker_poll_seconds)
    except KeyboardInterrupt:
        typer.echo("Worker stopped")
    finally:
        database.dispose()


if __name__ == "__main__":
    app()
