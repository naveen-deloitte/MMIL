from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import typer
from pydantic import ValidationError

from idp.config import Settings
from idp.document_types import DocumentTypeRegistry
from idp.errors import AppError, ProcessingError
from idp.extraction.engine import EXTRACTOR_VERSION, SchemaExtractor
from idp.extraction.providers import build_provider
from idp.extraction.text import PageTextService
from idp.file_validation import detect_media_type, validate_upload
from idp.services.processing import merge_provider_fields

app = typer.Typer(help="Validate configuration or process a document with the shared pipeline.")


@app.command("validate-config")
def validate_config(
    path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Validate a versioned document-type definition."""
    try:
        registry = DocumentTypeRegistry.load(path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        typer.echo(f"Configuration is invalid: {type(exc).__name__}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"Valid {registry.definition.document_type} schema "
        f"{registry.definition.schema_version} ({len(registry.definition.fields)} fields)"
    )


@app.command("process")
def process(
    input_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output_path: Path = typer.Argument(..., dir_okay=False),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing output file."),
) -> None:
    """Process one explicit input and write grounded JSON output."""
    if output_path.exists() and not overwrite:
        typer.echo("Output already exists; use --overwrite to replace it.", err=True)
        raise typer.Exit(2)
    settings = Settings()
    registry = DocumentTypeRegistry.load(settings.document_type_path)
    content = input_path.read_bytes()
    detected = detect_media_type(content)
    try:
        validated = validate_upload(
            content=content,
            filename=input_path.name,
            declared_media_type=detected,
            settings=settings,
        )
        pages = PageTextService(settings).extract(input_path, validated.media_type)
        candidates = SchemaExtractor(registry.definition).extract(
            document_id="standalone-document",
            document_version=1,
            pages=pages,
        )
        provider = build_provider(settings)
        provider_result = provider.extract(pages=pages, definition=registry.definition)
        if provider_result.fields:
            candidates = merge_provider_fields(
                candidates=candidates,
                provider_fields=provider_result.fields,
                pages=pages,
                document_id="standalone-document",
                document_version=1,
                registry=registry,
            )
    except (AppError, ProcessingError) as exc:
        code = exc.code
        typer.echo(f"Processing failed: {code}", err=True)
        raise typer.Exit(1) from exc

    output = {
        "document_type": registry.definition.document_type,
        "schema_version": registry.definition.schema_version,
        "extractor_version": EXTRACTOR_VERSION,
        "provider": provider.name,
        "model_version": provider.model_version,
        "page_count": len(pages),
        "fields": [
            {
                "field_path": item.field_path,
                "label": item.label,
                "ui_section": item.ui_section,
                "ui_group": item.ui_group,
                "source_literal": item.source_literal,
                "normalized_value": item.normalized_value,
                "data_type": item.data_type,
                "unit": item.unit,
                "status": item.status,
                "confidence": item.confidence,
                "validations": item.validations,
                "citations": [citation.as_dict() for citation in item.citations],
            }
            for item in candidates
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, output_path)
    typer.echo(
        f"Processed {len(pages)} page(s); wrote {len(candidates)} schema fields to {output_path}"
    )


if __name__ == "__main__":
    app()
