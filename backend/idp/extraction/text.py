from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol

import pymupdf
from pypdf import PdfReader

from idp.config import Settings
from idp.errors import ProcessingError


@dataclass(frozen=True)
class TextBlock:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "x0": self.x0,
            "y0": self.y0,
            "x1": self.x1,
            "y1": self.y1,
        }


@dataclass(frozen=True)
class RasterImage:
    width: int
    height: int
    channels: int
    samples: bytes
    encoded_png: bytes


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    width: float
    height: float
    blocks: list[TextBlock] = field(default_factory=list)
    engine: str = "unknown"
    engine_version: str = "unknown"
    ocr_used: bool = False
    confidence: float | None = None


class OcrAdapter(Protocol):
    name: str
    version: str

    def extract(self, image: RasterImage) -> tuple[str, list[TextBlock], float | None]: ...


class NoOcrAdapter:
    name = "none"
    version = "none"

    def extract(self, image: RasterImage) -> tuple[str, list[TextBlock], float | None]:
        del image
        raise ProcessingError("ocr_unavailable", retryable=True)


class RapidOcrAdapter:
    name = "rapidocr"
    version = "unknown"

    def __init__(self) -> None:
        try:
            from importlib.metadata import version

            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise ProcessingError("ocr_adapter_not_installed", retryable=False) from exc
        self.version = version("rapidocr-onnxruntime")
        self._engine = RapidOCR()

    def extract(self, image: RasterImage) -> tuple[str, list[TextBlock], float | None]:
        try:
            import numpy as np

            array = np.frombuffer(image.samples, dtype=np.uint8).reshape(
                image.height, image.width, image.channels
            )
            if image.channels == 1:
                array = np.repeat(array, 3, axis=2)
            elif image.channels > 3:
                array = array[:, :, :3]
            result, _timing = self._engine(array)
        except Exception as exc:
            raise ProcessingError("ocr_failed", retryable=True) from exc
        if not result:
            return "", [], None
        blocks: list[TextBlock] = []
        confidences: list[float] = []
        for item in result:
            box, text, confidence = item
            points = list(box)
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            cleaned = str(text).strip()
            if not cleaned:
                continue
            blocks.append(TextBlock(cleaned, min(xs), min(ys), max(xs), max(ys)))
            confidences.append(float(confidence))
        return (
            "\n".join(block.text for block in blocks),
            blocks,
            (sum(confidences) / len(confidences) if confidences else None),
        )


class TextractOcrAdapter:
    name = "aws-textract"
    version = "detect-document-text-v1"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        if not settings.ocr_region:
            raise ProcessingError("textract_region_not_configured", retryable=False)
        if settings.approved_region_set and settings.ocr_region not in settings.approved_region_set:
            raise ProcessingError("ocr_region_not_approved", retryable=False)
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ProcessingError("ocr_adapter_not_installed", retryable=False) from exc
            client = boto3.client("textract", region_name=settings.ocr_region)
        self._client = client

    def extract(self, image: RasterImage) -> tuple[str, list[TextBlock], float | None]:
        if len(image.encoded_png) > 5 * 1024 * 1024:
            raise ProcessingError("ocr_page_too_large", retryable=False)
        try:
            response = self._client.detect_document_text(Document={"Bytes": image.encoded_png})
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
            retryable = code in {
                "ProvisionedThroughputExceededException",
                "ThrottlingException",
                "InternalServerError",
            }
            raise ProcessingError(
                "ocr_provider_unavailable" if retryable else "ocr_failed",
                retryable=retryable,
            ) from exc
        blocks: list[TextBlock] = []
        confidences: list[float] = []
        for item in response.get("Blocks", []):
            if item.get("BlockType") != "LINE" or not str(item.get("Text", "")).strip():
                continue
            geometry = item.get("Geometry", {}).get("BoundingBox", {})
            left = float(geometry.get("Left", 0.0)) * image.width
            top = float(geometry.get("Top", 0.0)) * image.height
            width = float(geometry.get("Width", 0.0)) * image.width
            height = float(geometry.get("Height", 0.0)) * image.height
            text = str(item["Text"]).strip()
            blocks.append(TextBlock(text, left, top, left + width, top + height))
            confidences.append(float(item.get("Confidence", 0.0)) / 100.0)
        return (
            "\n".join(block.text for block in blocks),
            blocks,
            sum(confidences) / len(confidences) if confidences else None,
        )


def build_ocr_adapter(settings: Settings) -> OcrAdapter:
    if settings.ocr_provider == "rapidocr":
        return RapidOcrAdapter()
    if settings.ocr_provider == "textract":
        return TextractOcrAdapter(settings)
    return NoOcrAdapter()


class PageTextService:
    def __init__(self, settings: Settings, ocr: OcrAdapter | None = None):
        self.settings = settings
        self.ocr = ocr or build_ocr_adapter(settings)

    def extract(
        self,
        path: Path,
        media_type: str,
        *,
        form_field_aliases: dict[str, tuple[str, str | None]] | None = None,
    ) -> list[PageText]:
        if media_type == "application/pdf":
            return self._extract_pdf(path, form_field_aliases=form_field_aliases)
        if media_type in {"image/jpeg", "image/png", "image/tiff"}:
            return self._extract_image(path, media_type)
        raise ProcessingError("unsupported_media_type", retryable=False)

    def _extract_pdf(
        self,
        path: Path,
        *,
        form_field_aliases: dict[str, tuple[str, str | None]] | None = None,
    ) -> list[PageText]:
        try:
            document = pymupdf.open(path)
        except Exception as exc:
            raise ProcessingError("parser_failed", retryable=False) from exc
        pages: list[PageText] = []
        try:
            if document.needs_pass:
                raise ProcessingError("encrypted_document", retryable=False)
            with path.open("rb") as pdf_file:
                reader = PdfReader(pdf_file, strict=False)
                if reader.is_encrypted:
                    raise ProcessingError("encrypted_document", retryable=False)
                if len(reader.pages) != len(document):
                    raise ProcessingError("page_count_mismatch", retryable=False)
                for index, (pdf_page, page) in enumerate(zip(reader.pages, document, strict=True)):
                    text = pdf_page.extract_text() or ""
                    raw_blocks = page.get_text("blocks", sort=True)
                    blocks = [
                        TextBlock(
                            text=str(block[4]).strip(),
                            x0=float(block[0]),
                            y0=float(block[1]),
                            x1=float(block[2]),
                            y1=float(block[3]),
                        )
                        for block in raw_blocks
                        if str(block[4]).strip()
                    ]
                    form_lines: list[str] = []
                    for widget in page.widgets() or []:
                        value = str(widget.field_value or "").strip()
                        name = str(widget.field_name or "").strip()
                        alias, checked_value = (form_field_aliases or {}).get(name, (name, None))
                        if widget.field_type == pymupdf.PDF_WIDGET_TYPE_TEXT and name and value:
                            line = f"{alias}: {value}"
                            if line not in text:
                                form_lines.append(line)
                                rect = widget.rect
                                blocks.append(
                                    TextBlock(
                                        line,
                                        float(rect.x0),
                                        float(rect.y0),
                                        float(rect.x1),
                                        float(rect.y1),
                                    )
                                )
                        elif (
                            widget.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX
                            and name in (form_field_aliases or {})
                            and value.casefold() not in {"off", "false", "0", "none"}
                        ):
                            selected_value = checked_value or "Selected"
                            line = f"{alias}: {selected_value}"
                            if line not in text:
                                form_lines.append(line)
                    if form_lines:
                        text = f"{text.rstrip()}\n" + "\n".join(form_lines)
                    rect = page.rect
                    if len(text.strip()) >= self.settings.native_text_min_chars:
                        pages.append(
                            PageText(
                                page_number=index + 1,
                                text=text,
                                width=float(rect.width),
                                height=float(rect.height),
                                blocks=blocks,
                                engine="pypdf-native",
                                engine_version=version("pypdf"),
                                ocr_used=False,
                                confidence=1.0,
                            )
                        )
                        continue

                    scale = 2.0
                    if rect.width * scale * rect.height * scale > self.settings.max_image_pixels:
                        raise ProcessingError("image_pixel_limit_exceeded", retryable=False)
                    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                    ocr_text, ocr_blocks, confidence = self.ocr.extract(_raster(pixmap))
                    converted = [
                        TextBlock(
                            block.text,
                            block.x0 / scale,
                            block.y0 / scale,
                            block.x1 / scale,
                            block.y1 / scale,
                        )
                        for block in ocr_blocks
                    ]
                    pages.append(
                        PageText(
                            page_number=index + 1,
                            text=ocr_text,
                            width=float(rect.width),
                            height=float(rect.height),
                            blocks=converted,
                            engine=self.ocr.name,
                            engine_version=self.ocr.version,
                            ocr_used=True,
                            confidence=confidence,
                        )
                    )
        except ProcessingError:
            raise
        except Exception as exc:
            raise ProcessingError("parser_failed", retryable=False) from exc
        finally:
            document.close()
        return pages

    def _extract_image(self, path: Path, media_type: str) -> list[PageText]:
        file_types = {"image/jpeg": "jpeg", "image/png": "png", "image/tiff": "tiff"}
        try:
            document = pymupdf.open(path, filetype=file_types[media_type])
        except Exception as exc:
            raise ProcessingError("parser_failed", retryable=False) from exc
        pages: list[PageText] = []
        try:
            for index, page in enumerate(document):
                pixmap = page.get_pixmap(alpha=False)
                if pixmap.width * pixmap.height > self.settings.max_image_pixels:
                    raise ProcessingError("image_pixel_limit_exceeded", retryable=False)
                text, blocks, confidence = self.ocr.extract(_raster(pixmap))
                pages.append(
                    PageText(
                        page_number=index + 1,
                        text=text,
                        width=float(pixmap.width),
                        height=float(pixmap.height),
                        blocks=blocks,
                        engine=self.ocr.name,
                        engine_version=self.ocr.version,
                        ocr_used=True,
                        confidence=confidence,
                    )
                )
        finally:
            document.close()
        return pages


def _raster(pixmap: pymupdf.Pixmap) -> RasterImage:
    return RasterImage(
        width=pixmap.width,
        height=pixmap.height,
        channels=pixmap.n,
        samples=bytes(pixmap.samples),
        encoded_png=pixmap.tobytes("png"),
    )
