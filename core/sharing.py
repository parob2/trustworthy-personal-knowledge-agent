from __future__ import annotations

from core.audit import record_audit_event
from core.database import Database
from core.models import (
    AuditEventType,
    NuggetStatus,
    SharedPublication,
    SharingScope,
    utc_now,
)
from core.risk_detection import detect_deterministic_risks
from logging_config import get_logger

logger = get_logger("sharing")


class SharingAuthorizationError(PermissionError):
    """Raised when backend sharing authorization denies a sharing attempt."""


def _deny_sharing(
    db: Database,
    input_id: str,
    nugget_id: str,
    requested_scope: SharingScope,
    reason: str,
) -> None:
    """Fail-safe denial: ensure nugget stays PRIVATE, audit the block, and raise error."""
    nugget = db.get_nugget(nugget_id)
    if nugget is not None and nugget.approved_scope != SharingScope.PRIVATE:
        nugget.approved_scope = SharingScope.PRIVATE
        if nugget.status == NuggetStatus.APPROVED_SHARED:
            nugget.status = NuggetStatus.PENDING_REVIEW
        nugget.updated_at = utc_now()
        db.update_nugget(nugget)

    logger.warning(
        "SHARING_BLOCKED | nugget_id=%s | requested_scope=%s | reason=%s",
        nugget_id,
        requested_scope.value if isinstance(requested_scope, SharingScope) else str(requested_scope),
        reason,
    )
    record_audit_event(
        db=db,
        input_id=input_id,
        nugget_id=nugget_id,
        event_type=AuditEventType.SHARING_BLOCKED,
        decision="DENIED_KEPT_PRIVATE",
        sharing_scope=SharingScope.PRIVATE,
        reason=reason,
    )
    raise SharingAuthorizationError(reason)


def authorize_sharing(
    nugget_id: str,
    requested_scope: SharingScope,
    db: Database,
) -> SharedPublication:
    """
    Independent backend authorization gate for sharing knowledge nuggets.
    Verifies ALL four mandatory conditions before persisting simulated sharing:
      1. Explicit human approval exists (and consequences were confirmed).
      2. Approved content has not changed since approval (SHA-256 hash match).
      3. User explicitly selected a valid non-PRIVATE sharing scope matching approval.
      4. No blocking security condition exists (including fresh deterministic re-scan).
    """
    nugget = db.get_nugget(nugget_id)
    if nugget is None:
        raise ValueError(f"Nugget '{nugget_id}' not found.")

    # Condition 3 (scope validity)
    if not isinstance(requested_scope, SharingScope) or not requested_scope.is_shared:
        _deny_sharing(
            db,
            nugget.note_id,
            nugget.id,
            SharingScope.PRIVATE,
            "Sharing requires an explicit non-PRIVATE scope (PROJECT_TEAM, DEPARTMENT, or ORGANISATION).",
        )

    if nugget.status in (NuggetStatus.REJECTED, NuggetStatus.NEEDS_HUMAN_REVIEW, NuggetStatus.PENDING_REVIEW):
        _deny_sharing(
            db,
            nugget.note_id,
            nugget.id,
            requested_scope,
            f"Nugget status '{nugget.status.value}' is not approved for sharing.",
        )

    # Condition 1: Explicit human approval exists
    active_approval = db.get_active_approval(nugget.id)
    if active_approval is None or active_approval.decision != "APPROVED" or active_approval.invalidated_at is not None:
        _deny_sharing(
            db,
            nugget.note_id,
            nugget.id,
            requested_scope,
            "No valid active human approval exists for this nugget.",
        )

    if not active_approval.confirmed_consequences:
        _deny_sharing(
            db,
            nugget.note_id,
            nugget.id,
            requested_scope,
            "Sharing consequences were not explicitly confirmed.",
        )

    if active_approval.selected_scope != requested_scope:
        _deny_sharing(
            db,
            nugget.note_id,
            nugget.id,
            requested_scope,
            f"Requested scope '{requested_scope.value}' does not match human-approved scope '{active_approval.selected_scope.value}'.",
        )

    # Condition 2: Approved content has not changed
    current_hash = nugget.current_content_hash
    if (
        nugget.approved_content_hash is None
        or current_hash != active_approval.approved_content_hash
        or current_hash != nugget.approved_content_hash
    ):
        _deny_sharing(
            db,
            nugget.note_id,
            nugget.id,
            requested_scope,
            "Nugget content changed after approval; prior approval is invalid and requires fresh human review.",
        )

    # Condition 4: No blocking security condition exists
    if nugget.unresolved_blocking_risks:
        _deny_sharing(
            db,
            nugget.note_id,
            nugget.id,
            requested_scope,
            "Nugget has unresolved blocking risk warnings and must remain PRIVATE.",
        )

    # Independent fresh deterministic scan on the exact content being shared
    fresh_risks = detect_deterministic_risks(
        text=f"{nugget.current_title}\n{nugget.current_content}\n{' '.join(nugget.current_tags)}",
        nugget_id=nugget.id,
    )
    if fresh_risks:
        _deny_sharing(
            db,
            nugget.note_id,
            nugget.id,
            requested_scope,
            "Deterministic security re-scan detected sensitive or risky content; sharing blocked.",
        )

    # All four checks passed -> persist simulated local sharing first, then mark APPROVED_SHARED
    now = utc_now()
    publication = SharedPublication(
        nugget_id=nugget.id,
        approval_id=active_approval.id,
        scope=requested_scope,
        published_content_hash=current_hash,
        published_title=nugget.current_title,
        published_content=nugget.current_content,
        published_tags=list(nugget.current_tags),
        published_at=now,
    )
    db.save_shared_publication(publication)

    nugget.approved_scope = requested_scope
    nugget.status = NuggetStatus.APPROVED_SHARED
    nugget.updated_at = now
    db.update_nugget(nugget)

    logger.info(
        "SHARING_AUTHORIZED | nugget_id=%s | pub_id=%s | scope=%s | hash=%s",
        nugget.id,
        publication.id,
        requested_scope.value,
        current_hash[:12],
    )

    record_audit_event(
        db=db,
        input_id=nugget.note_id,
        nugget_id=nugget.id,
        event_type=AuditEventType.SHARING_AUTHORIZED,
        decision=f"SHARED_TO_{requested_scope.value}",
        sharing_scope=requested_scope,
        reason=(
            f"Backend verified approval ({active_approval.id}), content hash match, "
            f"and zero blocking security warnings."
        ),
    )
    return publication
