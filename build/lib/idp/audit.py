from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from idp.models import AuditEvent

_ALLOWED_METADATA_KEYS = {
    "media_type",
    "size_bytes",
    "status",
    "failure_code",
    "document_type",
    "schema_version",
    "decision",
    "review_version",
    "page_count",
    "provider",
    "attempt",
    "result_count",
}


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if key not in _ALLOWED_METADATA_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    return safe


def append_audit(
    session: Session,
    *,
    tenant_id: str,
    actor_subject: str,
    action: str,
    outcome: str,
    correlation_id: str,
    case_id: str | None = None,
    document_id: str | None = None,
    run_id: str | None = None,
    field_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id,
        case_id=case_id,
        document_id=document_id,
        run_id=run_id,
        field_id=field_id,
        actor_subject=actor_subject,
        action=action,
        outcome=outcome,
        correlation_id=correlation_id,
        metadata_json=_safe_metadata(metadata),
    )
    session.add(event)
    return event
