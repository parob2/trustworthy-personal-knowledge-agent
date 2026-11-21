from __future__ import annotations

import re
from typing import Optional

from core.database import Database
from core.models import AuditEvent, AuditEventType, SharingScope
from logging_config import get_logger

logger = get_logger("audit")

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\s*[:=]\s*\S+"
)
_KNOWN_TOKEN_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|AKIA[0-9A-Z]{16}|xoxb-[0-9A-Za-z-]+)\b"
)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")


def sanitize_audit_reason(reason: str) -> str:
    """Redact potential sensitive raw text before storing in persistent audit records."""
    sanitized = _EMAIL_RE.sub("[REDACTED_EMAIL]", reason)
    sanitized = _KNOWN_TOKEN_RE.sub("[REDACTED_TOKEN]", sanitized)
    sanitized = _SECRET_ASSIGN_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", sanitized)
    sanitized = _PHONE_RE.sub("[REDACTED_PHONE]", sanitized)
    if len(sanitized) > 320:
        sanitized = sanitized[:317] + "..."
    return sanitized


def record_audit_event(
    db: Database,
    input_id: str,
    event_type: AuditEventType,
    decision: str,
    reason: str,
    sharing_scope: SharingScope = SharingScope.PRIVATE,
    nugget_id: Optional[str] = None,
) -> AuditEvent:
    """Create and persist an immutable, sanitized audit event."""
    event = AuditEvent(
        input_id=input_id,
        nugget_id=nugget_id,
        event_type=event_type,
        decision=decision,
        sharing_scope=sharing_scope,
        reason=sanitize_audit_reason(reason),
    )
    db.append_audit_event(event)
    logger.info(
        "AUDIT | event=%s | input_id=%s | nugget_id=%s | scope=%s | decision=%s | reason=%s",
        event.event_type.value,
        event.input_id,
        event.nugget_id or "-",
        event.sharing_scope.value,
        event.decision,
        event.reason,
    )
    return event


def get_audit_history(
    db: Database,
    event_type: Optional[AuditEventType] = None,
    limit: int = 200,
) -> list[AuditEvent]:
    return db.list_audit_events(event_type=event_type, limit=limit)
