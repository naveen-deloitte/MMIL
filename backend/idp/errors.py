from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AppError(Exception):
    status_code: int
    code: str
    title: str
    detail: str

    def __str__(self) -> str:
        return self.code


class ProcessingError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class StaleReviewError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=409,
            code="stale_review",
            title="Review conflict",
            detail=(
                "This field changed after it was loaded. "
                + "Refresh and reconcile the current review."
            ),
        )
