from __future__ import annotations

from pathlib import Path
import pytest

from core.capture import capture_note
from core.consent import approve_nugget
from core.database import Database
from core.extraction import process_note
from core.models import NuggetStatus, SharingScope
from core.review import edit_nugget
from core.sharing import SharingAuthorizationError, authorize_sharing


def test_sharing_blocked_without_approval(db: Database) -> None:
    note = capture_note(
        "Automated validation before deployment reduced recurring configuration errors.",
        db=db,
    )
    nugget = process_note(note, db=db, use_ollama=False)[0]

    with pytest.raises(SharingAuthorizationError, match="not approved"):
        authorize_sharing(nugget.id, SharingScope.PROJECT_TEAM, db)

    reloaded = db.get_nugget(nugget.id)
    assert reloaded is not None
    assert reloaded.approved_scope == SharingScope.PRIVATE
    assert db.list_shared_publications(nugget.id) == []


def test_sharing_blocked_if_scope_mismatch_or_private(db: Database) -> None:
    note = capture_note(
        "Automated validation before deployment reduced recurring configuration errors.",
        db=db,
    )
    nugget = process_note(note, db=db, use_ollama=False)[0]
    approve_nugget(nugget.id, SharingScope.PROJECT_TEAM, True, db)

    with pytest.raises(SharingAuthorizationError, match="does not match"):
        authorize_sharing(nugget.id, SharingScope.ORGANISATION, db)

    with pytest.raises(SharingAuthorizationError, match="non-PRIVATE"):
        authorize_sharing(nugget.id, SharingScope.PRIVATE, db)


def test_sharing_blocked_when_content_edited_after_approval(db: Database) -> None:
    note = capture_note(
        "Automated validation before deployment reduced recurring configuration errors.",
        db=db,
    )
    nugget = process_note(note, db=db, use_ollama=False)[0]
    approve_nugget(nugget.id, SharingScope.DEPARTMENT, True, db)

    edit_nugget(
        nugget_id=nugget.id,
        title="Updated Title",
        content="Updated content after approval.",
        tags=["validation"],
        db=db,
    )

    with pytest.raises(SharingAuthorizationError):
        authorize_sharing(nugget.id, SharingScope.DEPARTMENT, db)

    reloaded = db.get_nugget(nugget.id)
    assert reloaded is not None
    assert reloaded.approved_scope == SharingScope.PRIVATE


def test_backend_rescan_blocks_tampered_sensitive_content(db: Database) -> None:
    note = capture_note(
        "Automated validation before deployment reduced recurring configuration errors.",
        db=db,
    )
    nugget = process_note(note, db=db, use_ollama=False)[0]
    approve_nugget(nugget.id, SharingScope.PROJECT_TEAM, True, db)

    # Simulate direct DB tampering inserting an email after approval without invalidating hash
    with db.connect() as conn:
        conn.execute(
            "UPDATE nuggets SET edited_content = ? WHERE id = ?",
            ("Leak contact: leak@example.com", nugget.id),
        )

    with pytest.raises(SharingAuthorizationError):
        authorize_sharing(nugget.id, SharingScope.PROJECT_TEAM, db)


def test_authorized_sharing_persists_across_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "restart_test.db"
    db1 = Database(db_file)
    note = capture_note(
        "Involving stakeholders earlier improved coordination between engineering and product teams.",
        db=db1,
    )
    nugget = process_note(note, db=db1, use_ollama=False)[0]
    approve_nugget(nugget.id, SharingScope.DEPARTMENT, True, db1)
    pub = authorize_sharing(nugget.id, SharingScope.DEPARTMENT, db1)

    # Re-open database simulating application restart
    db2 = Database(db_file)
    restored = db2.get_nugget(nugget.id)
    assert restored is not None
    assert restored.status == NuggetStatus.APPROVED_SHARED
    assert restored.approved_scope == SharingScope.DEPARTMENT
    pubs = db2.list_shared_publications(nugget.id)
    assert len(pubs) == 1
    assert pubs[0].id == pub.id
