from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from idp.config import Settings
from idp.errors import AppError, ProcessingError
from idp.extraction.engine import normalize_value
from idp.extraction.scanner import DevelopmentBasicScanner
from idp.file_validation import detect_media_type, validate_upload
from idp.services.processing import ALLOWED_TRANSITIONS, assert_transition


@given(
    prefix=st.binary(min_size=0, max_size=20).filter(lambda value: not value.startswith(b"%PDF-"))
)
def test_arbitrary_filename_cannot_turn_non_pdf_bytes_into_pdf(prefix: bytes) -> None:
    settings = Settings(environment="test", auth_mode="demo", seed_demo_case=False)
    assert detect_media_type(prefix) != "application/pdf"
    with pytest.raises(AppError) as error:
        validate_upload(
            content=prefix or b"not a file",
            filename="trusted.pdf",
            declared_media_type="application/pdf",
            settings=settings,
        )
    assert error.value.code in {"unsupported_media_type", "empty_file"}


@given(
    systolic=st.integers(min_value=1, max_value=999),
    diastolic=st.integers(min_value=1, max_value=999),
)
def test_measurement_pair_normalization_preserves_values(systolic: int, diastolic: int) -> None:
    assert normalize_value("measurement_pair", f"{systolic}/{diastolic}") == {
        "systolic": systolic,
        "diastolic": diastolic,
    }


@pytest.mark.parametrize("source", ALLOWED_TRANSITIONS)
@pytest.mark.parametrize(
    "target",
    [
        "uploaded",
        "scanning",
        "ocr",
        "extracting",
        "review_required",
        "completed",
        "failed",
        "cancelled",
    ],
)
def test_status_transition_table_accepts_exact_edges(source: str, target: str) -> None:
    if target in ALLOWED_TRANSITIONS[source]:
        assert_transition(source, target)
    else:
        with pytest.raises(AppError) as error:
            assert_transition(source, target)
        assert error.value.code == "invalid_status_transition"


def test_development_scanner_rejects_eicar_marker(tmp_path: Path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_bytes(
        b"%PDF-1.4\nX5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"
    )
    with pytest.raises(ProcessingError) as error:
        DevelopmentBasicScanner().scan(sample)
    assert error.value.code == "malware_detected"
