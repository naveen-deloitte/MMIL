from __future__ import annotations

from pathlib import Path

import pymupdf

from idp.config import Settings
from idp.extraction.text import (
    PageTextService,
    RasterImage,
    TextBlock,
    TextractOcrAdapter,
)
from idp.file_validation import validate_upload


class FakeOcr:
    name = "fake-approved-ocr"
    version = "test-1"

    def extract(self, image: RasterImage):
        assert image.width > 0
        assert len(image.samples) == image.width * image.height * image.channels
        return (
            "BMI: 26.1 kg/m2",
            [TextBlock("BMI: 26.1 kg/m2", 1.0, 2.0, 90.0, 20.0)],
            0.91,
        )


def test_image_uses_configured_ocr_adapter(tmp_path: Path) -> None:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    pixmap.clear_with(255)
    path = tmp_path / "scan.png"
    content = pixmap.tobytes("png")
    path.write_bytes(content)
    settings = Settings(
        environment="test",
        auth_mode="demo",
        seed_demo_case=False,
        ocr_provider="none",
    )

    validated = validate_upload(
        content=content,
        filename="scan.png",
        declared_media_type="image/png",
        settings=settings,
    )
    assert validated.page_count == 1

    pages = PageTextService(settings, ocr=FakeOcr()).extract(path, "image/png")

    assert len(pages) == 1
    assert pages[0].ocr_used is True
    assert pages[0].engine == "fake-approved-ocr"
    assert pages[0].text == "BMI: 26.1 kg/m2"
    assert pages[0].confidence == 0.91


class FakeTextractClient:
    def detect_document_text(self, *, Document):
        assert Document["Bytes"].startswith(b"png")
        return {
            "Blocks": [
                {
                    "BlockType": "LINE",
                    "Text": "BMI: 26.1 kg/m2",
                    "Confidence": 97.0,
                    "Geometry": {
                        "BoundingBox": {
                            "Left": 0.1,
                            "Top": 0.2,
                            "Width": 0.5,
                            "Height": 0.1,
                        }
                    },
                }
            ]
        }


def test_textract_adapter_records_exact_lines_and_pixel_bbox() -> None:
    settings = Settings(
        environment="test",
        auth_mode="demo",
        seed_demo_case=False,
        ocr_provider="textract",
        ocr_region="ap-south-1",
        approved_provider_regions="ap-south-1",
    )
    adapter = TextractOcrAdapter(settings, client=FakeTextractClient())
    text, blocks, confidence = adapter.extract(
        RasterImage(
            width=200,
            height=100,
            channels=3,
            samples=b"\xff" * (200 * 100 * 3),
            encoded_png=b"png-test-bytes",
        )
    )
    assert text == "BMI: 26.1 kg/m2"
    assert confidence == 0.97
    assert blocks[0] == TextBlock("BMI: 26.1 kg/m2", 20.0, 20.0, 120.0, 30.0)
