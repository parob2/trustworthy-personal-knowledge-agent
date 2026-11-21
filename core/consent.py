from __future__ import annotations

from typing import Optional

from core.audit import record_audit_event
from core.database import Database
from core.models import (
    Approval,
    AuditEventType,
    KnowledgeNugget,
    NuggetStatus,
    SharingScope,
    utc_now,
)
from core.risk_detection import detect_deterministic_risks
from logging_config import get_logger

logger = get_logger("consent")


class ConsentError(PermissionError):
    """Raised when human consent requirements or security preconditions are not met."""


def approve_nugget(
    nugget_id: str,
    selected_scope: SharingScope,
    confirmed_consequences: bool,
    db: Database,
    reason: Optional[str] = None,
) -> tuple[KnowledgeNugget, Approval]:
    """
    Record explicit human approval bound to the exact current nugget content hash and chosen scope.
    Does NOT automatically publish/share externally — backend sharing authorization verifies
    all preconditions separately when sharing non-PRIVATE scopes.
    """
    nugget = db.get_nugget(nugget_id)
    if nugget is None:
        raise ValueError(f"Nugget '{nugget_id}' not found.")

    if not isinstance(selected_scope, SharingScope):
        raise ValueError("A valid SharingScope must be explicitly selected.")

    # Security rule: unresolved security warnings keep the nugget PRIVATE
    unresolved = nugget.unresolved_blocking_risks
    fresh_det = detect_deterministic_risks(
        f"{nugget.current_title}\n{nugget.current_content}\n{' '.join(nugget.current_tags)}",
        nugget_id=nugget.id,
    )

    if selected_scope.is_shared:
        if unresolved or fresh_det:
            record_audit_event(
                db=db,
                input_id=nugget.note_id,
                nugget_id=nugget.id,
                event_type=AuditEventType.SHARING_BLOCKED,
                decision="APPROVAL_FOR_SHARING_DENIED",
                sharing_scope=SharingScope.PRIVATE,
                reason=(
                    f"Blocked non-private approval ({selected_scope.value}) due to unresolved "
                    "security or quality risk warnings."
                ),
            )
            raise ConsentError(
                "Cannot approve for sharing while unresolved security or risk warnings exist. "
                "Edit/resolve warnings first or select PRIVATE."
            )

        if not confirmed_consequences:
            record_audit_event(
                db=db,
                input_id=nugget.note_id,
                nugget_id=nugget.id,
                event_type=AuditEventType.SHARING_BLOCKED,
                decision="MISSING_CONSEQUENCE_CONFIRMATION",
                sharing_scope=SharingScope.PRIVATE,
                reason=f"User did not confirm sharing consequences for scope {selected_scope.value}.",
            )
            raise ConsentError(
                "You must explicitly confirm the sharing consequences dialog before approving a non-private scope."
            )

    now = utc_now()
    # Supersede any prior active approval cleanly
    db.invalidate_active_approvals(
        nugget_id=nugget.id,
        reason="Superseded by new explicit human approval.",
        invalidated_at=now,
    )

    content_hash = nugget.current_content_hash
    approval = Approval(
        nugget_id=nugget.id,
        approved_content_hash=content_hash,
        selected_scope=selected_scope,
        decision="APPROVED",
        confirmed_consequences=confirmed_consequences if selected_scope.is_shared else True,
        reason=reason or f"Explicit human approval for scope {selected_scope.value}.",
        created_at=now,
    )
    db.save_approval(approval)

    # Snapshot exact approved content; keep approved_scope PRIVATE until backend sharing authorization runs
    nugget.approved_title = nugget.current_title
    nugget.approved_content = nugget.current_content
    nugget.approved_tags = list(nugget.current_tags)
    nugget.approved_content_hash = content_hash
    nugget.approved_scope = SharingScope.PRIVATE
    nugget.status = NuggetStatus.APPROVED_PRIVATE
    nugget.updated_at = now
    db.update_nugget(nugget)

    logger.info(
        "CONSENT_APPROVED | nugget_id=%s | approval_id=%s | selected_scope=%s | hash=%s",
        nugget.id,
        approval.id,
        selected_scope.value,
        content_hash[:12],
    )

    record_audit_event(
        db=db,
        input_id=nugget.note_id,
        nugget_id=nugget.id,
        event_type=AuditEventType.NUGGET_APPROVED,
        decision=f"APPROVED_FOR_{selected_scope.value}",
        sharing_scope=SharingScope.PRIVATE,  # Remains PRIVATE until authorize_sharing succeeds
        reason=approval.reason or "Explicit human approval recorded.",
    )

    return db.get_nugget(nugget.id) or nugget, approval


def reject_nugget(
    nugget_id: str,
    db: Database,
    reason: str = "Rejected by human reviewer.",
) -> KnowledgeNugget:
    """Reject a generated nugget, invalidate prior approvals, and enforce PRIVATE state."""
    nugget = db.get_nugget(nugget_id)
    if nugget is None:
        raise ValueError(f"Nugget '{nugget_id}' not found.")

    now = utc_now()
    db.invalidate_active_approvals(
        nugget_id=nugget.id,
        reason="Nugget rejected by human reviewer.",
        invalidated_at=now,
    )

    rejection_record = Approval(
        nugget_id=nugget.id,
        approved_content_hash=nugget.current_content_hash,
        selected_scope=SharingScope.PRIVATE,
        decision="REJECTED",
        confirmed_consequences=False,
        reason=reason.strip() or "Rejected by human reviewer.",
        created_at=now,
    )
    db.save_approval(rejection_record)

    nugget.approved_title = None
    nugget.approved_content = None
    nugget.approved_tags = None
    nugget.approved_content_hash = None
    nugget.approved_scope = SharingScope.PRIVATE
    nugget.status = NuggetStatus.REJECTED
    nugget.updated_at = now
    db.update_nugget(nugget)

    logger.info("CONSENT_REJECTED | nugget_id=%s | reason=%s", nugget.id, reason)

    record_audit_event(
        db=db,
        input_id=nugget.note_id,
        nugget_id=nugget.id,
        event_type=AuditEventType.NUGGET_REJECTED,
        decision="REJECTED_PRIVATE",
        sharing_scope=SharingScope.PRIVATE,
        reason=rejection_record.reason or "Rejected by human reviewer.",
    )

    return db.get_nugget(nugget.id) or nugget
