from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest

from core.audit import get_audit_history
from core.capture import capture_note
from core.consent import approve_nugget, reject_nugget
from core.database import Database
from core.extraction import process_note
from core.models import AuditEventType, SharingScope
from core.review import edit_nugget
from core.sharing import SharingAuthorizationError, authorize_sharing


def test_audit_records_all_lifecycle_events_and_persists(tmp_path: Path) -> None:
    db_file = tmp_path / "audit_test.db"
    db1 = Database(db_file)

    note = capture_note(
        "Involving stakeholders earlier improved coordination between engineering and product teams.",
        db=db1,
    )
    nugget = process_note(note, db=db1, use_ollama=False)[0]

    # Trigger SHARING_BLOCKED
    with pytest.raises(SharingAuthorizationError):
        authorize_sharing(nugget.id, SharingScope.PROJECT_TEAM, db1)

    # Approve & edit (triggers APPROVAL_INVALIDATED)
    approve_nugget(nugget.id, SharingScope.PROJECT_TEAM, True, db1)
    edit_nugget(
        nugget.id,
        "Stakeholder Coordination",
        "Involving stakeholders earlier improved engineering and product alignment.",
        ["stakeholders", "product"],
        db1,
    )

    # Re-approve & share
    approve_nugget(nugget.id, SharingScope.PROJECT_TEAM, True, db1)
    authorize_sharing(nugget.id, SharingScope.PROJECT_TEAM, db1)

    # Create second nugget to test reject
    note2 = capture_note("Short internal draft note.", db=db1)
    nugget2 = process_note(note2, db=db1, use_ollama=False)[0]
    reject_nugget(nugget2.id, db1, reason="Too vague.")

    # Reload DB after restart
    db2 = Database(db_file)
    events = get_audit_history(db2)
    event_types = {e.event_type for e in events}

    assert AuditEventType.NOTE_CAPTURED in event_types
    assert AuditEventType.NUGGET_GENERATED in event_types
    assert AuditEventType.SHARING_BLOCKED in event_types
    assert AuditEventType.NUGGET_APPROVED in event_types
    assert AuditEventType.NUGGET_EDITED in event_types
    assert AuditEventType.APPROVAL_INVALIDATED in event_types
    assert AuditEventType.SHARING_AUTHORIZED in event_types
    assert AuditEventType.NUGGET_REJECTED in event_types


def test_audit_reasons_redact_sensitive_raw_text(db: Database) -> None:
    note = capture_note(
        "Customer contact: john@example.com with token sk-supersecret1234567890",
        db=db,
    )
    process_note(note, db=db, use_ollama=False)

    events = get_audit_history(db)
    serialized = " ".join(e.reason for e in events)
    assert "john@example.com" not in serialized
    assert "sk-supersecret1234567890" not in serialized


def test_audit_records_cannot_be_silently_overwritten_or_deleted(db: Database) -> None:
    capture_note("Audit immutability check note.", db=db)
    events = get_audit_history(db)
    assert len(events) >= 1
    ev_id = events[0].id

    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with db.connect() as conn:
            conn.execute(
                "UPDATE audit_events SET decision = 'TAMPERED' WHERE id = ?",
                (ev_id,),
            )

    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        with db.connect() as conn:
            conn.execute("DELETE FROM audit_events WHERE id = ?", (ev_id,))
