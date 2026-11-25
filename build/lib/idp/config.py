from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
AuthMode = Literal["demo", "oidc"]
OcrProvider = Literal["none", "rapidocr", "textract"]
StorageBackend = Literal["local", "s3"]
QueueBackend = Literal["database", "sqs"]
ScannerBackend = Literal["development-basic", "approved-service"]


class Settings(BaseSettings):
    """Validated process configuration.

    Secrets are accepted through the environment only and are excluded from repr/serialization.
    Request data can never override provider or authentication settings.
    """

    model_config = SettingsConfigDict(
        env_prefix="IDP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = "development"
    auth_mode: AuthMode = "demo"
    database_url: str = "sqlite:///./var/idp.db"
    object_root: Path = Path("./var/objects")
    document_type_path: Path = Path("./config/document-types/medical-report.v1.json")
    storage_backend: StorageBackend = "local"
    queue_backend: QueueBackend = "database"
    scanner_backend: ScannerBackend = "development-basic"

    max_upload_bytes: int = Field(default=50 * 1024 * 1024, ge=1024, le=500 * 1024 * 1024)
    max_pages: int = Field(default=200, ge=1, le=2000)
    max_image_pixels: int = Field(default=50_000_000, ge=1_000_000, le=500_000_000)
    native_text_min_chars: int = Field(default=20, ge=0, le=5000)
    job_max_attempts: int = Field(default=3, ge=1, le=20)
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60.0)
    worker_lease_seconds: int = Field(default=300, ge=30, le=3600)

    ocr_provider: OcrProvider = "none"
    ocr_region: str | None = None
    extraction_provider: str = "deterministic-local"
    allowed_providers: str = "deterministic-local"
    approved_provider_regions: str = ""
    model_id: str | None = None
    model_endpoint: str | None = None
    model_region: str | None = None
    model_api_key: SecretStr | None = Field(default=None, repr=False)
    prompt_version: str = "medical-extraction-1.0.0"

    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    tenant_claim: str = "tenant_id"
    roles_claim: str = "roles"

    demo_tenant_id: str = "tenant-demo"
    demo_user_id: str = "reviewer-demo"
    demo_role: str = "reviewer"
    seed_demo_case: bool = True
    cors_origins: str = "http://localhost:5173"

    @property
    def allowed_provider_set(self) -> set[str]:
        return {value.strip() for value in self.allowed_providers.split(",") if value.strip()}

    @property
    def approved_region_set(self) -> set[str]:
        return {
            value.strip() for value in self.approved_provider_regions.split(",") if value.strip()
        }

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @model_validator(mode="after")
    def validate_security_modes(self) -> Settings:
        if self.environment == "production":
            if self.auth_mode == "demo":
                raise ValueError("demo authentication is forbidden in production")
            if self.storage_backend != "s3":
                raise ValueError("production requires the S3 storage backend")
            if self.queue_backend != "sqs":
                raise ValueError("production requires the SQS queue backend")
            if self.scanner_backend != "approved-service":
                raise ValueError("production requires an approved scanner backend")
            if self.database_url.startswith("sqlite"):
                raise ValueError("production requires PostgreSQL")
            if self.extraction_provider == "deterministic-local":
                raise ValueError("deterministic-local extraction is forbidden in production")
            if self.ocr_provider == "rapidocr":
                raise ValueError("rapidocr is a local adapter and is forbidden in production")
            if (
                self.ocr_provider == "textract"
                or self.extraction_provider != "deterministic-local"
            ) and not self.approved_region_set:
                raise ValueError("production providers require an approved region allowlist")
        if self.auth_mode == "oidc":
            missing = [
                name
                for name, value in {
                    "oidc_issuer": self.oidc_issuer,
                    "oidc_audience": self.oidc_audience,
                    "oidc_jwks_url": self.oidc_jwks_url,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError(f"OIDC mode requires: {', '.join(missing)}")
        if self.ocr_provider == "textract":
            if not self.ocr_region:
                raise ValueError("textract OCR requires an ocr_region")
            if self.approved_region_set and self.ocr_region not in self.approved_region_set:
                raise ValueError("selected OCR region is not approved")
        if self.extraction_provider not in self.allowed_provider_set:
            raise ValueError("selected extraction provider is not allowlisted")
        if self.extraction_provider != "deterministic-local" and not self.model_id:
            raise ValueError("external extraction providers require a pinned model_id")
        if self.extraction_provider == "openai-compatible":
            if not self.model_endpoint or not self.model_endpoint.startswith("https://"):
                raise ValueError("openai-compatible requires an HTTPS model_endpoint")
            if not self.model_api_key:
                raise ValueError("openai-compatible requires a model API secret")
        if self.extraction_provider == "bedrock-claude" and not self.model_region:
            raise ValueError("bedrock-claude requires a model_region")
        if (
            self.model_region
            and self.approved_region_set
            and self.model_region not in self.approved_region_set
        ):
            raise ValueError("selected model region is not approved")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
