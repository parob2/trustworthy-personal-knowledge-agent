from __future__ import annotations

from typing import Optional

from core.audit import record_audit_event
from core.database import Database
from core.models import (
    AuditEventType,
    KnowledgeNugget,
    NuggetStatus,
    RiskCategory,
    SharingScope,
    compute_content_hash,
    normalize_tags,
    utc_now,
)
from core.risk_detection import detect_deterministic_risks, evaluate_risks
from logging_config import get_logger

logger = get_logger("review")


def edit_nugget(
    nugget_id: str,
    title: str,
    content: str,
    tags: list[str],
    db: Database,
) -> KnowledgeNugget:
    """
    Apply human edits to a nugget, re-run deterministic risk evaluation,
    and invalidate any prior approval if content changed.
    """
    nugget = db.get_nugget(nugget_id)
    if nugget is None:
        raise ValueError(f"Nugget '{nugget_id}' not found.")

    clean_title = title.strip()
    clean_content = content.strip()
    clean_tags = normalize_tags(tags)

    if not clean_title:
        raise ValueError("Nugget title cannot be empty.")
    if not clean_content:
        raise ValueError("Nugget content cannot be empty.")

    previous_hash = nugget.current_content_hash
    new_hash = compute_content_hash(clean_title, clean_content, clean_tags)
    now = utc_now()

    nugget.edited_title = clean_title
    nugget.edited_content = clean_content
    nugget.edited_tags = clean_tags
    nugget.updated_at = now

    # Re-run deterministic security checks on the edited text so fixed PII/secrets can clear,
    # while newly introduced risks are caught immediately.
    note = db.get_note(nugget.note_id)
    fresh_flags = evaluate_risks(
        title=clean_title,
        content=clean_content,
        tags=clean_tags,
        nugget_id=nugget.id,
        source_note_text=None,  # Evaluate edited nugget text directly so human redactions can succeed
        ai_signals=None,
    )
    # Still check for unsupported percentages invented beyond the original note
    if note is not None:
        pct_flags = [
            f
            for f in detect_deterministic_risks(
                text=f"{clean_title}\n{clean_content}",
                nugget_id=nugget.id,
                source_note_text=note.content,
            )
            if f.category == RiskCategory.UNSUPPORTED_CLAIMS
            and not any(ef.category == RiskCategory.UNSUPPORTED_CLAIMS for ef in fresh_flags)
        ]
        fresh_flags.extend(pct_flags)

    nugget.risk_flags = fresh_flags

    approval_was_invalidated = False
    if nugget.approved_content_hash is not None and nugget.approved_content_hash != new_hash:
        approval_was_invalidated = True
    elif db.get_active_approval(nugget.id) is not None and previous_hash != new_hash:
        approval_was_invalidated = True

    if approval_was_invalidated:
        db.invalidate_active_approvals(
            nugget_id=nugget.id,
            reason="Nugget content edited after approval; prior approval invalidated.",
            invalidated_at=now,
        )
        nugget.approved_title = None
        nugget.approved_content = None
        nugget.approved_tags = None
        nugget.approved_content_hash = None
        nugget.approved_scope = SharingScope.PRIVATE

    # Editing always requires fresh human review before approval/sharing
    if previous_hash != new_hash or nugget.status in (
        NuggetStatus.APPROVED_PRIVATE,
        NuggetStatus.APPROVED_SHARED,
        NuggetStatus.REJECTED,
    ):
        nugget.status = (
            NuggetStatus.NEEDS_HUMAN_REVIEW
            if any(f.blocking and not f.resolved for f in fresh_flags)
            else NuggetStatus.PENDING_REVIEW
        )
        nugget.approved_scope = SharingScope.PRIVATE

    db.update_nugget(nugget, replace_risks=True)

    logger.info(
        "REVIEW_EDIT | nugget_id=%s | hash_changed=%s | invalidated_prior=%s | risks=%d",
        nugget.id,
        previous_hash != new_hash,
        approval_was_invalidated,
        len(fresh_flags),
    )

    record_audit_event(
        db=db,
        input_id=nugget.note_id,
        nugget_id=nugget.id,
        event_type=AuditEventType.NUGGET_EDITED,
        decision=nugget.status.value,
        sharing_scope=SharingScope.PRIVATE,
        reason="Human edited nugget content/metadata; deterministic risk check re-run.",
    )

    if approval_was_invalidated:
        record_audit_event(
            db=db,
            input_id=nugget.note_id,
            nugget_id=nugget.id,
            event_type=AuditEventType.APPROVAL_INVALIDATED,
            decision="INVALIDATED_RESET_TO_PRIVATE",
            sharing_scope=SharingScope.PRIVATE,
            reason="Content hash changed after previous approval; reverted to PRIVATE and queued for re-review.",
        )

    for flag in fresh_flags:
        record_audit_event(
            db=db,
            input_id=nugget.note_id,
            nugget_id=nugget.id,
            event_type=AuditEventType.RISK_WARNING_RAISED,
            decision="WARNING_BLOCKING" if flag.blocking else "WARNING_ADVISORY",
            sharing_scope=SharingScope.PRIVATE,
            reason=f"[{flag.category.value}] Re-scan after edit: {flag.explanation}",
        )

    return db.get_nugget(nugget.id) or nugget


def resolve_risk_flag(
    nugget_id: str,
    risk_id: str,
    resolution_note: str,
    db: Database,
) -> KnowledgeNugget:
    """
    Allow human reviewers to acknowledge/resolve non-secret risk warnings (e.g., Unsupported claims)
    after verification. Deterministic PII, Credentials, and Confidential flags CANNOT be manually
    overridden while the sensitive pattern remains in the nugget content.
    """
    nugget = db.get_nugget(nugget_id)
    if nugget is None:
        raise ValueError(f"Nugget '{nugget_id}' not found.")

    target = next((rf for rf in nugget.risk_flags if rf.id == risk_id), None)
    if target is None:
        raise ValueError(f"Risk flag '{risk_id}' not found on nugget '{nugget_id}'.")

    if not resolution_note.strip():
        raise ValueError("Please provide a brief verification note before resolving a warning.")

    if target.source == "deterministic" and target.category in (
        RiskCategory.PERSONAL_INFORMATION,
        RiskCategory.CREDENTIALS_AND_SECRETS,
        RiskCategory.CONFIDENTIAL_INFORMATION,
    ):
        # Verify whether the pattern is still present in current content
        current_det = detect_deterministic_risks(
            f"{nugget.current_title}\n{nugget.current_content}\n{' '.join(nugget.current_tags)}",
            nugget_id=nugget.id,
        )
        if any(f.category == target.category for f in current_det):
            raise PermissionError(
                f"Cannot override deterministic '{target.category.value}' warning while sensitive "
                "content remains in the nugget. Edit the nugget to remove or redact it first."
            )

    db.update_risk_flag_resolution(
        risk_id=risk_id,
        resolved=True,
        resolution_note=resolution_note.strip(),
    )
    updated = db.get_nugget(nugget_id)
    assert updated is not None
    if not updated.unresolved_blocking_risks and updated.status == NuggetStatus.NEEDS_HUMAN_REVIEW:
        updated.status = NuggetStatus.PENDING_REVIEW
        updated.updated_at = utc_now()
        db.update_nugget(updated)
    return db.get_nugget(nugget_id) or updated
