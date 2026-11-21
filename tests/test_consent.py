from __future__ import annotations

import pytest

from core.capture import capture_note
from core.consent import ConsentError, approve_nugget, reject_nugget
from core.database import Database
from core.extraction import process_note
from core.models import NuggetStatus, SharingScope
from core.review import edit_nugget, resolve_risk_flag


def test_editing_after_approval_invalidates_prior_approval(db: Database) -> None:
    note = capture_note(
        "Running automated validation before deployment reduced recurring configuration errors.",
        db=db,
    )
    nugget = process_note(note, db=db, use_ollama=False)[0]
    assert nugget.approved_scope == SharingScope.PRIVATE

    approved_nugget, approval = approve_nugget(
        nugget_id=nugget.id,
        selected_scope=SharingScope.PROJECT_TEAM,
        confirmed_consequences=True,
        db=db,
    )
    assert approval.decision == "APPROVED"
    assert approved_nugget.approved_content_hash == approved_nugget.current_content_hash

    # Now human edits content -> prior approval MUST be invalidated and scope reverted to PRIVATE
    edited = edit_nugget(
        nugget_id=nugget.id,
        title="Pre-Deployment Validation Checks",
        content="Automated validation before deployment reduces configuration drift across environments.",
        tags=["deployment", "validation"],
        db=db,
    )
    assert edited.status == NuggetStatus.PENDING_REVIEW
    assert edited.approved_scope == SharingScope.PRIVATE
    assert edited.approved_content_hash is None
    assert db.get_active_approval(nugget.id) is None

    # Original source note must remain untouched for provenance
    preserved_note = db.get_note(note.id)
    assert preserved_note is not None
    assert "reduced recurring configuration errors" in preserved_note.content


def test_blocking_risks_prevent_non_private_approval_until_redacted(db: Database) -> None:
    note = capture_note(
        "Customer contact: john@example.com. The internal migration project is confidential and must not be shared externally.",
        db=db,
    )
    nugget = process_note(note, db=db, use_ollama=False)[0]
    assert len(nugget.unresolved_blocking_risks) >= 2

    # Attempting to share while PII/confidentiality warnings remain must fail
    with pytest.raises(ConsentError):
        approve_nugget(
            nugget_id=nugget.id,
            selected_scope=SharingScope.DEPARTMENT,
            confirmed_consequences=True,
            db=db,
        )

    # Attempting to manually resolve deterministic PII warning without redacting must fail
    pii_flag = nugget.unresolved_blocking_risks[0]
    with pytest.raises(PermissionError):
        resolve_risk_flag(nugget.id, pii_flag.id, "Trying to bypass", db)

    # Redact sensitive details via edit_nugget -> deterministic re-scan clears risks
    cleaned = edit_nugget(
        nugget_id=nugget.id,
        title="Migration Communication Hygiene",
        content="Keep customer contact details and internal project milestones out of shared knowledge bases.",
        tags=["migration", "privacy"],
        db=db,
    )
    assert cleaned.unresolved_blocking_risks == []

    # Now private or team approval can succeed with consequence confirmation
    _, approval = approve_nugget(
        nugget_id=cleaned.id,
        selected_scope=SharingScope.PROJECT_TEAM,
        confirmed_consequences=True,
        db=db,
    )
    assert approval.decision == "APPROVED"


def test_non_private_approval_requires_consequence_confirmation(db: Database) -> None:
    note = capture_note(
        "Involving stakeholders earlier improved coordination between engineering and product teams.",
        db=db,
    )
    nugget = process_note(note, db=db, use_ollama=False)[0]

    with pytest.raises(ConsentError, match="confirm"):
        approve_nugget(
            nugget_id=nugget.id,
            selected_scope=SharingScope.ORGANISATION,
            confirmed_consequences=False,
            db=db,
        )


def test_reject_nugget_reverts_to_private_and_clears_approval(db: Database) -> None:
    note = capture_note(
        "Involving stakeholders earlier improved coordination between engineering and product teams.",
        db=db,
    )
    nugget = process_note(note, db=db, use_ollama=False)[0]
    approve_nugget(nugget.id, SharingScope.PRIVATE, True, db)

    rejected = reject_nugget(nugget.id, db, reason="Not broadly useful.")
    assert rejected.status == NuggetStatus.REJECTED
    assert rejected.approved_scope == SharingScope.PRIVATE
    assert db.get_active_approval(nugget.id) is None
