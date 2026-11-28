"""Reading-order repair for OCR'd identity card images.

Card images often show the front and back side by side. OCR engines emit text rows across the
whole image, which interleaves the two sides and separates a label from its value. When a clear
vertical gap splits the OCR blocks into two columns, each column is read top to bottom on its own.
Only the order of lines changes; no text is added, removed or edited.
"""

from __future__ import annotations

from dataclasses import replace

from idp.extraction.text import PageText, TextBlock

_MIN_GAP_RATIO = 0.01
_SEARCH_START, _SEARCH_END = 0.3, 0.7


def _column_split(blocks: list[TextBlock], width: float) -> float | None:
    """Return the x position of the widest empty vertical band in the middle of the page."""
    if width <= 0 or len(blocks) < 4:
        return None
    lo, hi = width * _SEARCH_START, width * _SEARCH_END
    intervals = sorted((max(b.x0, lo), min(b.x1, hi)) for b in blocks if b.x1 > lo and b.x0 < hi)
    best_gap, best_mid, cursor = 0.0, None, lo
    for start, end in intervals:
        if start > cursor and start - cursor > best_gap:
            best_gap, best_mid = start - cursor, (cursor + start) / 2
        cursor = max(cursor, end)
    if hi > cursor and hi - cursor > best_gap:
        best_gap, best_mid = hi - cursor, (cursor + hi) / 2
    if best_mid is None or best_gap < width * _MIN_GAP_RATIO:
        return None
    left = [b for b in blocks if b.x1 <= best_mid]
    right = [b for b in blocks if b.x0 >= best_mid]
    # Both sides must carry real text, otherwise this is just a ragged single column.
    if len(left) < 2 or len(right) < 2:
        return None
    return best_mid


def _reading_order(blocks: list[TextBlock]) -> list[TextBlock]:
    if not blocks:
        return []
    heights = sorted(max(1.0, b.y1 - b.y0) for b in blocks)
    tolerance = heights[len(heights) // 2] * 0.5
    ordered = sorted(blocks, key=lambda b: (b.y0 + b.y1) / 2)
    lines: list[list[TextBlock]] = []
    for block in ordered:
        centre = (block.y0 + block.y1) / 2
        if lines and abs(centre - (lines[-1][0].y0 + lines[-1][0].y1) / 2) <= tolerance:
            lines[-1].append(block)
        else:
            lines.append([block])
    return [block for line in lines for block in sorted(line, key=lambda b: b.x0)]


def reorder_card_columns(pages: list[PageText]) -> list[PageText]:
    result: list[PageText] = []
    for page in pages:
        if not page.ocr_used or not page.blocks:
            result.append(page)
            continue
        split = _column_split(page.blocks, page.width)
        if split is None:
            result.append(page)
            continue
        left = [b for b in page.blocks if (b.x0 + b.x1) / 2 < split]
        right = [b for b in page.blocks if (b.x0 + b.x1) / 2 >= split]
        blocks = _reading_order(left) + _reading_order(right)
        result.append(replace(page, text="\n".join(b.text for b in blocks), blocks=blocks))
    return result
