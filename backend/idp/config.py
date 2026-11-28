from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
PlatformProfile = Literal["local", "launchpad-dev", "custom"]
AuthMode = Literal["demo", "oidc"]
OcrProvider = Literal["none", "rapidocr", "textract"]
StorageBackend = Literal["local", "s3"]
QueueBackend = Literal["database", "sqs"]
ScannerBackend = Literal["development-basic", "approved-service"]
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Validated process configuration.

    Secrets are accepted through the environment only and are excluded from repr/serialization.
    Request data can never override provider or authentication settings.
    """

    model_config = SettingsConfigDict(
        env_prefix="IDP_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = "development"
    platform_profile: PlatformProfile = "local"
    auth_mode: AuthMode = "demo"
    database_url: str = "sqlite:///./var/idp.db"
    object_root: Path = PROJECT_ROOT / "sample-data" / "uploads"
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
    external_provider_approved: bool = False
    allowed_providers: str = "deterministic-local"
    approved_provider_regions: str = ""
    model_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IDP_MODEL_ID", "OPENAI_MODEL", "model_id"),
    )
    model_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("IDP_MODEL_ENDPOINT", "OPENAI_BASE_URL", "model_endpoint"),
    )
    model_api_version: str | None = None
    model_region: str | None = None
    model_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        validation_alias=AliasChoices("IDP_MODEL_API_KEY", "OPENAI_API_KEY", "model_api_key"),
    )

    # Official identity verification. Both default to "not_configured": no verification is
    # attempted and nothing is ever reported as verified without an authorized provider.
    identity_aadhaar_provider: Literal["not_configured", "uidai-offline-qr"] = "not_configured"
    identity_aadhaar_trust_cert_path: Path | None = None
    identity_pan_provider: Literal["not_configured", "http"] = "not_configured"
    identity_pan_endpoint: str | None = None
    identity_pan_api_key: SecretStr | None = Field(default=None, repr=False)
    identity_pan_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
    identity_pan_max_retries: int = Field(default=2, ge=0, le=5)

    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    tenant_claim: str = "tenant_id"
    roles_claim: str = "roles"
    cases_claim: str = "case_ids"

    demo_tenant_id: str = "tenant-demo"
    demo_user_id: str = "reviewer-demo"
    demo_role: str = "reviewer"
    demo_case_ids: str = "Dummy-Dummy-29495"
    seed_demo_case: bool = True
    cors_origins: str = "http://localhost:5173"

    @field_validator("object_root")
    @classmethod
    def resolve_object_root(cls, value: Path) -> Path:
        expanded = value.expanduser()
        if not expanded.is_absolute():
            expanded = PROJECT_ROOT / expanded
        return expanded.resolve()

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
        if self.platform_profile == "launchpad-dev":
            if self.ocr_provider == "textract":
                raise ValueError("Textract is not permitted by the Launchpad dev runtime role")
            if self.extraction_provider not in {"deterministic-local", "azure-openai"}:
                raise ValueError(
                    "only Azure OpenAI is permitted by the Launchpad dev provider policy"
                )
        if self.identity_pan_provider == "http":
            if not self.identity_pan_endpoint or not self.identity_pan_api_key:
                raise ValueError("PAN verification requires an endpoint and API key")
            if not self.identity_pan_endpoint.startswith("https://"):
                raise ValueError("PAN verification endpoint must use https")
        if self.ocr_provider == "textract":
            if not self.ocr_region:
                raise ValueError("textract OCR requires an ocr_region")
            if self.approved_region_set and self.ocr_region not in self.approved_region_set:
                raise ValueError("selected OCR region is not approved")
        if self.extraction_provider not in self.allowed_provider_set:
            raise ValueError("selected extraction provider is not allowlisted")
        if (
            self.extraction_provider != "deterministic-local"
            and not self.external_provider_approved
        ):
            raise ValueError("external extraction provider is not approved")
        if self.extraction_provider != "deterministic-local" and not self.model_id:
            raise ValueError("external extraction providers require a pinned model_id")
        if self.extraction_provider in {"openai-compatible", "azure-openai"}:
            if not self.model_endpoint or not self.model_endpoint.startswith("https://"):
                raise ValueError("OpenAI-compatible providers require an HTTPS model_endpoint")
            if not self.model_api_key:
                raise ValueError("OpenAI-compatible providers require a model API secret")
        if self.extraction_provider == "azure-openai" and not self.model_api_version:
            raise ValueError("azure-openai requires a pinned model_api_version")
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
