from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from idp.config import Settings
from idp.errors import ProcessingError
from idp.extraction.providers import OpenAICompatibleProvider
from idp.storage import LocalObjectStore


def test_production_rejects_demo_authentication() -> None:
    with pytest.raises(ValidationError, match="demo authentication"):
        Settings(
            environment="production",
            auth_mode="demo",
            extraction_provider="bedrock-claude",
            allowed_providers="bedrock-claude",
            model_id="approved-model-version",
            model_region="ap-south-1",
            approved_provider_regions="ap-south-1",
        )


def test_production_rejects_local_storage_and_queue_adapters() -> None:
    with pytest.raises(ValidationError, match="S3 storage"):
        Settings(
            environment="production",
            auth_mode="oidc",
            oidc_issuer="https://identity.example.test/",
            oidc_audience="idp-api",
            oidc_jwks_url="https://identity.example.test/jwks.json",
            extraction_provider="bedrock-claude",
            allowed_providers="bedrock-claude",
            model_id="approved-model-version",
            model_region="ap-south-1",
            approved_provider_regions="ap-south-1",
        )


def test_launchpad_profile_rejects_unavailable_bedrock_provider() -> None:
    with pytest.raises(ValidationError, match="only Azure OpenAI"):
        Settings(
            environment="test",
            platform_profile="launchpad-dev",
            extraction_provider="bedrock-claude",
            external_provider_approved=True,
            allowed_providers="bedrock-claude",
            model_id="model",
            model_region="ap-south-1",
            approved_provider_regions="ap-south-1",
        )


def test_external_provider_requires_explicit_approval() -> None:
    with pytest.raises(ValidationError, match="not approved"):
        Settings(
            environment="test",
            extraction_provider="openai-compatible",
            allowed_providers="openai-compatible",
            external_provider_approved=False,
            model_id="deployment",
            model_endpoint="https://approved.example.test/openai",
            model_region="centralindia",
            model_api_key="test-secret",
        )


def test_selected_provider_must_be_allowlisted() -> None:
    with pytest.raises(ValidationError, match="not allowlisted"):
        Settings(
            environment="test",
            extraction_provider="openai-compatible",
            allowed_providers="deterministic-local",
            model_id="pinned-model",
        )


@pytest.mark.parametrize(
    ("base_url", "expected_endpoint"),
    [
        ("https://api.example.test/v1", "https://api.example.test/v1/chat/completions"),
        (
            "https://api.example.test/v1/chat/completions",
            "https://api.example.test/v1/chat/completions",
        ),
    ],
)
def test_openai_environment_aliases_configure_extraction_provider(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    expected_endpoint: str,
) -> None:
    monkeypatch.setenv("IDP_EXTRACTION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("IDP_ALLOWED_PROVIDERS", "openai-compatible")
    monkeypatch.setenv("IDP_EXTERNAL_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    monkeypatch.setenv("OPENAI_MODEL", "approved-model")
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")

    settings = Settings(_env_file=None)
    provider = OpenAICompatibleProvider(settings)

    assert settings.model_id == "approved-model"
    assert settings.model_api_key is not None
    assert provider.endpoint == expected_endpoint
    assert provider.model_version == "approved-model"


def test_local_object_store_rejects_traversal(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ProcessingError) as error:
        store.path_for("../../outside.pdf")
    assert error.value.code == "invalid_object_key"


def test_local_upload_storage_defaults_to_sample_data_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IDP_OBJECT_ROOT", raising=False)
    settings = Settings(_env_file=None)
    expected_root = Path(__file__).resolve().parents[2] / "sample-data" / "uploads"
    assert settings.object_root == expected_root.resolve()
    relative_override = Settings(_env_file=None, object_root=Path("./sample-data/uploads"))
    assert relative_override.object_root == expected_root.resolve()
