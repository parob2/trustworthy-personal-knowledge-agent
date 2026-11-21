from __future__ import annotations

import hashlib

from core.audit import record_audit_event
from core.database import Database
from core.models import AuditEventType, MAX_NOTE_LENGTH, Note, SharingScope
from logging_config import get_logger

logger = get_logger("capture")


def capture_note(
    content: str,
    db: Database,
    source_label: str = "manual",
) -> Note:
    """Validate, persist, and audit a newly captured raw note (backend-enforced 4000-char limit)."""
    if not isinstance(content, str):
        raise ValueError("Note content must be a text string.")

    if len(content) > MAX_NOTE_LENGTH:
        raise ValueError(
            f"Note content exceeds the maximum allowed {MAX_NOTE_LENGTH} characters "
            f"(received {len(content)})."
        )

    stripped = content.strip()
    if not stripped:
        raise ValueError("Note content cannot be empty or whitespace only.")

    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    note = Note(
        content=content,
        content_hash=content_hash,
        source_label=source_label,
        processing_status="CAPTURED",
    )
    db.save_note(note)

    logger.info(
        "CAPTURE | note_id=%s | chars=%d | source=%s | hash=%s",
        note.id,
        len(note.content),
        note.source_label,
        note.content_hash[:12],
    )

    record_audit_event(
        db=db,
        input_id=note.id,
        event_type=AuditEventType.NOTE_CAPTURED,
        decision="CAPTURED_PRIVATE",
        sharing_scope=SharingScope.PRIVATE,
        reason=f"Captured note ({len(note.content)} chars, source={source_label}). Kept private pending processing.",
    )
    return note
