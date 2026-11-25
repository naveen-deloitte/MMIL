from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from idp import __version__
from idp.api.routes import router
from idp.auth import Authenticator
from idp.config import Settings, get_settings
from idp.database import Database, seed_demo_case
from idp.document_types import DocumentTypeRegistry
from idp.errors import AppError
from idp.storage import LocalObjectStore

logger = logging.getLogger(__name__)
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9._-]{8,100}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    if resolved_settings.storage_backend != "local":
        raise RuntimeError("The S3 object-store adapter is not implemented in this local MVP.")
    if resolved_settings.queue_backend != "database":
        raise RuntimeError("The SQS queue adapter is not implemented in this local MVP.")
    database = Database(resolved_settings)
    object_store = LocalObjectStore(resolved_settings.object_root)
    registry = DocumentTypeRegistry.load_catalog(resolved_settings.document_type_path)
    authenticator = Authenticator(resolved_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        database.create_schema()
        if resolved_settings.seed_demo_case:
            seed_demo_case(database, resolved_settings)
        yield
        database.dispose()

    application = FastAPI(
        title="Configurable IDP Engine API",
        version=__version__,
        description=(
            "Reusable document ingestion, classification, grounded extraction, source provenance, "
            "and versioned results. The engine does not make business or medical decisions."
        ),
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.database = database
    application.state.object_store = object_store
    application.state.registry = registry
    application.state.authenticator = authenticator

    if resolved_settings.cors_origin_list:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=resolved_settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Correlation-ID",
                "X-Demo-User",
                "X-Demo-Tenant",
                "X-Demo-Role",
                "X-Demo-Cases",
            ],
            expose_headers=["X-Correlation-ID"],
        )

    @application.middleware("http")
    async def request_controls(request: Request, call_next):
        requested = request.headers.get("X-Correlation-ID", "")
        request.state.correlation_id = (
            requested if _CORRELATION_RE.fullmatch(requested) else str(uuid4())
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "private, no-store, max-age=0")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; frame-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'self'",
        )
        return response

    @application.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _problem_response(request, exc.status_code, exc.code, exc.title, exc.detail)

    @application.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = sorted(
            {
                ".".join(str(part) for part in error.get("loc", ()) if part not in {"body"})
                for error in exc.errors()
            }
        )
        suffix = f" Invalid fields: {', '.join(fields)}." if fields else ""
        return _problem_response(
            request,
            422,
            "request_validation_failed",
            "Invalid request",
            f"The request could not be validated.{suffix}",
        )

    @application.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        title = "Request failed"
        detail = "The request could not be completed."
        if exc.status_code == 404:
            title, detail = "Not found", "The requested resource was not found."
        elif exc.status_code == 405:
            title, detail = "Method not allowed", "This method is not supported for the resource."
        return _problem_response(request, exc.status_code, "http_error", title, detail)

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Never interpolate exception text or request content into ordinary logs.
        logger.error(
            "Unhandled request failure correlation_id=%s exception_type=%s",
            request.state.correlation_id,
            type(exc).__name__,
        )
        return _problem_response(
            request,
            500,
            "internal_error",
            "Internal server error",
            "The request could not be completed.",
        )

    application.include_router(router)

    frontend_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if frontend_dist.is_dir():
        application.mount("/", StaticFiles(directory=frontend_dist, html=True), name="web")
    return application


def _problem_response(
    request: Request, status: int, code: str, title: str, detail: str
) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid4()))
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers={"X-Correlation-ID": correlation_id},
        content={
            "type": f"https://errors.example.invalid/idp/{code}",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
            "correlation_id": correlation_id,
        },
    )


app = create_app()
