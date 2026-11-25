from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from idp.errors import ProcessingError

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(filename: str | None, media_type: str) -> str:
    fallback_extensions = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/tiff": ".tiff",
    }
    raw = Path(filename or "document").name
    cleaned = _SAFE_FILENAME.sub("_", raw).strip("._")[:180] or "document"
    expected = fallback_extensions.get(media_type, "")
    if expected and Path(cleaned).suffix.lower() not in {
        expected,
        ".jpeg" if expected == ".jpg" else expected,
        ".tif" if expected == ".tiff" else expected,
    }:
        cleaned = f"{cleaned}{expected}"
    return cleaned


class LocalObjectStore:
    """Local development object adapter with rooted, atomic, immutable writes."""

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_quarantine(
        self,
        *,
        tenant_id: str,
        case_id: str,
        document_id: str,
        safe_filename: str,
        content: bytes,
    ) -> tuple[str, str]:
        extension = Path(safe_filename).suffix.lower()
        # Tenant/case claims are hashed before path construction; source filenames never form keys.
        tenant_segment = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
        case_segment = hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:24]
        key = f"quarantine/{tenant_segment}/{case_segment}/{document_id}/v1/original{extension}"
        destination = self._resolve_key(key)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Recreate the parent immediately before opening the temp file: Windows
        # temporary pytest directories can disappear while async test clients unwind.
        if not destination.parent.is_dir():
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.exists():
            raise ProcessingError("object_already_exists")
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        return key, "local-v1"

    def path_for(self, object_key: str) -> Path:
        path = self._resolve_key(object_key)
        if not path.is_file():
            raise ProcessingError("object_missing", retryable=False)
        return path

    def verify_sha256(self, object_key: str, expected_sha256: str) -> Path:
        path = self.path_for(object_key)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ProcessingError("object_integrity_mismatch", retryable=False)
        return path

    def _resolve_key(self, object_key: str) -> Path:
        candidate = (self.root / object_key).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ProcessingError("invalid_object_key") from exc
        return candidate
