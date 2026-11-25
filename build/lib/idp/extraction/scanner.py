from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from idp.errors import ProcessingError

# Standard harmless anti-malware test marker. Never include it in ordinary logs.
_EICAR_FRAGMENT = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"


@dataclass(frozen=True)
class ScanResult:
    clean: bool
    engine: str
    version: str


class Scanner(Protocol):
    def scan(self, path: Path) -> ScanResult: ...


class DevelopmentBasicScanner:
    """A development guard, not a production malware scanner."""

    def scan(self, path: Path) -> ScanResult:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                if _EICAR_FRAGMENT in chunk:
                    raise ProcessingError("malware_detected", retryable=False)
        return ScanResult(clean=True, engine="development-basic-scan", version="1")
