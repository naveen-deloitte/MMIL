from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pymupdf

from idp.config import Settings
from idp.errors import AppError


SUPPORTED_MEDIA: dict[str, tuple[str, ...]] = {
    "application/pdf": (".pdf",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/tiff": (".tif", ".tiff"),
}
_IMAGE_FILE_TYPES = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/tiff": "tiff",
}


@dataclass(frozen=True)
class ValidatedFile:
    media_type: str
    page_count: int


def detect_media_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return None


def validate_upload(
    *, content: bytes, filename: str | None, declared_media_type: str | None, settings: Settings
) -> ValidatedFile:
    if not content:
        raise AppError(422, "empty_file", "Invalid document", "The uploaded file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise AppError(
            413,
            "file_too_large",
            "Document is too large",
            f"The document exceeds the configured {settings.max_upload_bytes} byte limit.",
        )

    detected = detect_media_type(content)
    if detected not in SUPPORTED_MEDIA:
        raise AppError(
            415,
            "unsupported_media_type",
            "Unsupported document type",
            "Upload a PDF, JPEG, PNG, or TIFF document.",
        )
    declared = (declared_media_type or "").lower().split(";", 1)[0].strip()
    aliases = {"image/jpg": "image/jpeg", "image/tif": "image/tiff"}
    declared = aliases.get(declared, declared)
    if declared not in {detected, "application/octet-stream"}:
        raise AppError(
            422,
            "file_signature_mismatch",
            "Invalid document",
            "The file content does not match its declared media type.",
        )

    extension = Path(filename or "").suffix.lower()
    if extension not in SUPPORTED_MEDIA[detected]:
        raise AppError(
            422,
            "file_extension_mismatch",
            "Invalid document",
            "The filename extension does not match the document content.",
        )

    if detected == "application/pdf":
        return _validate_pdf(content, settings)
    return _validate_image(content, detected, settings)


def _validate_pdf(content: bytes, settings: Settings) -> ValidatedFile:
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise AppError(
            422, "corrupt_document", "Invalid document", "The PDF cannot be read safely."
        ) from exc
    try:
        if document.needs_pass:
            raise AppError(
                422,
                "encrypted_document",
                "Encrypted document",
                "Password-protected PDFs are not supported.",
            )
        page_count = document.page_count
        _validate_page_count(page_count, settings)
        for page in document:
            rect = page.rect
            # Reject pathological media boxes before rendering or OCR.
            if rect.width <= 0 or rect.height <= 0 or rect.width > 20_000 or rect.height > 20_000:
                raise AppError(
                    422,
                    "invalid_page_dimensions",
                    "Invalid document",
                    "A PDF page has unsupported dimensions.",
                )
        return ValidatedFile(media_type="application/pdf", page_count=page_count)
    finally:
        document.close()


def _validate_image(content: bytes, media_type: str, settings: Settings) -> ValidatedFile:
    try:
        document = pymupdf.open(stream=content, filetype=_IMAGE_FILE_TYPES[media_type])
    except Exception as exc:
        raise AppError(
            422, "corrupt_document", "Invalid document", "The image cannot be read safely."
        ) from exc
    try:
        page_count = document.page_count
        _validate_page_count(page_count, settings)
        for page in document:
            image_info = page.get_image_info()
            if not image_info:
                raise AppError(
                    422,
                    "corrupt_document",
                    "Invalid document",
                    "The image does not contain a readable raster page.",
                )
            for info in image_info:
                width = int(info.get("width", 0))
                height = int(info.get("height", 0))
                if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
                    raise AppError(
                        422,
                        "image_pixel_limit_exceeded",
                        "Image is too large",
                        "The image dimensions exceed the configured safety limit.",
                    )
        return ValidatedFile(media_type=media_type, page_count=page_count)
    except AppError:
        raise
    except Exception as exc:
        raise AppError(
            422, "corrupt_document", "Invalid document", "The image cannot be read safely."
        ) from exc
    finally:
        document.close()


def _validate_page_count(page_count: int, settings: Settings) -> None:
    if page_count < 1:
        raise AppError(422, "empty_document", "Invalid document", "The document has no pages.")
    if page_count > settings.max_pages:
        raise AppError(
            422,
            "page_limit_exceeded",
            "Too many pages",
            f"The document exceeds the configured {settings.max_pages} page limit.",
        )
