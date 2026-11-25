from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from idp.config import Settings
from idp.errors import ProcessingError
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


def test_selected_provider_must_be_allowlisted() -> None:
    with pytest.raises(ValidationError, match="not allowlisted"):
        Settings(
            environment="test",
            extraction_provider="openai-compatible",
            allowed_providers="deterministic-local",
            model_id="pinned-model",
        )


def test_local_object_store_rejects_traversal(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ProcessingError) as error:
        store.path_for("../../outside.pdf")
    assert error.value.code == "invalid_object_key"
