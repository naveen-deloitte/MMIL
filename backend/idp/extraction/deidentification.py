from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from idp.errors import ProcessingError
from idp.extraction.text import PageText

_VALUE_PATTERNS = (
    re.compile(
        r"(?im)^\s*(?:(?:patient|member|insured|applicant|policyholder|claimant|"
        r"beneficiary)\s+)?(?:(?:full\s+)?name|name\s+of\s+(?:patient|member|insured))"
        r"\s*[:#=-]\s*(?P<value>[^\r\n]+)"
    ),
    re.compile(
        r"(?im)^\s*(?:patient|member|insured|applicant|policyholder|claimant|"
        r"beneficiary)\s*[:#=-]\s*(?P<value>[^\r\n]+)"
    ),
    re.compile(
        r"(?im)^\s*(?:date\s+of\s+birth|dob|birth\s+date|age(?:\s*/\s*(?:sex|gender))?|"
        r"phone(?:\s+number)?|"
        r"mobile(?:\s+number)?|email(?:\s+address)?|address|mrn|medical\s+record\s+"
        r"(?:number|no\.?)|patient\s+id|member\s+id|policy\s+(?:number|no\.?)|"
        r"claim\s+(?:number|no\.?)|proposal\s+(?:number|no\.?)|ssn|aadhaar(?:\s+"
        r"(?:number|no\.?))?)\s*[:#=-]\s*(?P<value>[^\r\n]+)"
    ),
    re.compile(
        r"(?i)\b(?:patient|member|insured|applicant|policyholder|claimant|"
        r"beneficiary)\s+(?P<value>[A-Z][A-Za-z'’-]+(?:\s+[A-Z][A-Za-z'’-]+){1,3})"
    ),
    re.compile(
        r"(?i)\b(?:aged\s+)?(?P<value>\d{1,3})"
        r"(?=\s*(?:[- ]?years?[- ]old|[- ]?yrs?[- ]?old|y/o)\b)"
    ),
    re.compile(r"(?i)\bage\s+(?P<value>\d{1,3})\b"),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"),
    re.compile(r"(?<!\w)(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\w)"),
)


def redact_page(page: PageText) -> PageText:
    return replace(
        page,
        text=redact_text(page.text),
        blocks=[replace(block, text=redact_text(block.text)) for block in page.blocks],
    )


def redact_pages(pages: list[PageText]) -> list[PageText]:
    return [redact_page(page) for page in pages]


def redact_text(text: str) -> str:
    spans: list[tuple[int, int]] = []
    for pattern in _VALUE_PATTERNS:
        for match in pattern.finditer(text):
            start, end = match.span("value") if "value" in match.groupdict() else match.span()
            spans.append((start, end))
    redacted = list(text)
    for start, end in _merge_spans(spans):
        for index in range(start, end):
            if not text[index].isspace():
                redacted[index] = "X"
    return "".join(redacted)


def restore_provider_citations(
    fields: list[dict[str, Any]],
    additional_facts: list[dict[str, Any]],
    original_pages: list[PageText],
    redacted_pages: list[PageText],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    original_by_number = {page.page_number: page for page in original_pages}
    redacted_by_number = {page.page_number: page for page in redacted_pages}
    return (
        [
            _restore_item(item, original_by_number, redacted_by_number)
            for item in fields
        ],
        [
            _restore_item(item, original_by_number, redacted_by_number)
            for item in additional_facts
        ],
    )


def restore_provider_analysis(
    analysis: dict[str, Any],
    original_pages: list[PageText],
    redacted_pages: list[PageText],
    *,
    document_id: str,
    document_version: int,
) -> tuple[dict[str, Any], int]:
    original_by_number = {page.page_number: page for page in original_pages}
    redacted_by_number = {page.page_number: page for page in redacted_pages}
    restored = dict(analysis)
    rejected = 0
    for key in ("summary", "vitals_summary"):
        statement = analysis[key]
        if statement is not None:
            try:
                restored[key] = _restore_statement(
                    statement,
                    original_by_number,
                    redacted_by_number,
                    document_id=document_id,
                    document_version=document_version,
                )
            except ProcessingError:
                restored[key] = None
                rejected += 1
    for key in (
        "key_medical_findings",
        "recommendations",
        "major_vital_factors",
    ):
        restored[key] = []
        for statement in analysis[key]:
            try:
                restored[key].append(
                    _restore_statement(
                        statement,
                        original_by_number,
                        redacted_by_number,
                        document_id=document_id,
                        document_version=document_version,
                    )
                )
            except ProcessingError:
                rejected += 1
    for key in ("lab_results", "knockout_checks"):
        restored[key] = []
        for item in analysis[key]:
            try:
                restored[key].append(
                    _restore_cited_item(
                        item,
                        original_by_number,
                        redacted_by_number,
                        document_id=document_id,
                        document_version=document_version,
                    )
                )
            except ProcessingError:
                rejected += 1
    return restored, rejected


def _restore_statement(
    statement: dict[str, Any],
    original_by_number: dict[int, PageText],
    redacted_by_number: dict[int, PageText],
    *,
    document_id: str,
    document_version: int,
) -> dict[str, Any]:
    return {
        "text": statement["text"],
        "citations": _restore_citations(
            statement["citations"],
            original_by_number,
            redacted_by_number,
            document_id=document_id,
            document_version=document_version,
        ),
    }


def _restore_cited_item(
    item: dict[str, Any],
    original_by_number: dict[int, PageText],
    redacted_by_number: dict[int, PageText],
    *,
    document_id: str,
    document_version: int,
) -> dict[str, Any]:
    return {
        **item,
        "citations": _restore_citations(
            item["citations"],
            original_by_number,
            redacted_by_number,
            document_id=document_id,
            document_version=document_version,
        ),
    }


def _restore_citations(
    source_citations: list[dict[str, Any]],
    original_by_number: dict[int, PageText],
    redacted_by_number: dict[int, PageText],
    *,
    document_id: str,
    document_version: int,
) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for citation in source_citations:
        page_number = citation["page"]
        excerpt = citation["excerpt"]
        original_page = original_by_number.get(page_number)
        redacted_page = redacted_by_number.get(page_number)
        if original_page is None or redacted_page is None:
            raise ProcessingError("provider_citation_invalid", retryable=False)
        start = redacted_page.text.find(excerpt)
        if start < 0:
            raise ProcessingError("provider_citation_invalid", retryable=False)
        original_excerpt = original_page.text[start : start + len(excerpt)]
        if len(original_excerpt) != len(excerpt):
            raise ProcessingError("provider_citation_invalid", retryable=False)
        citations.append(
            {
                "document_id": document_id,
                "document_version": document_version,
                "page": page_number,
                "excerpt": original_excerpt,
                "bbox": None,
            }
        )
    return citations


def _restore_item(
    item: dict[str, Any],
    original_by_number: dict[int, PageText],
    redacted_by_number: dict[int, PageText],
) -> dict[str, Any]:
    page_number = item.get("page")
    excerpt = item.get("excerpt")
    literal = item.get("source_literal")
    original_page = original_by_number.get(page_number)
    redacted_page = redacted_by_number.get(page_number)
    if (
        original_page is None
        or redacted_page is None
        or not isinstance(excerpt, str)
        or not isinstance(literal, str)
    ):
        raise ProcessingError("provider_citation_invalid", retryable=False)
    start = redacted_page.text.find(excerpt)
    if start < 0:
        raise ProcessingError("provider_citation_invalid", retryable=False)
    original_excerpt = original_page.text[start : start + len(excerpt)]
    if len(original_excerpt) != len(excerpt):
        raise ProcessingError("provider_citation_invalid", retryable=False)
    literal_start = excerpt.find(literal)
    if literal_start < 0:
        raise ProcessingError("provider_citation_invalid", retryable=False)
    original_literal = original_excerpt[literal_start : literal_start + len(literal)]
    redacted_literal = excerpt[literal_start : literal_start + len(literal)]
    if len(original_literal) != len(literal) or original_literal != redacted_literal:
        raise ProcessingError("provider_citation_invalid", retryable=False)
    restored = dict(item)
    restored["excerpt"] = original_excerpt
    restored["source_literal"] = original_literal
    return restored


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged
