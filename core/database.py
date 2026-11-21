from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from core.models import (
    Approval,
    AuditEvent,
    AuditEventType,
    KnowledgeNugget,
    Note,
    NuggetStatus,
    RiskCategory,
    RiskFlag,
    RiskSeverity,
    SharedPublication,
    SharingScope,
)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge_agent.db"


def _dt_to_str(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _str_to_dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value is not None else None


class Database:
    """SQLite persistence layer with parameterized queries and append-only audit triggers."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_label TEXT NOT NULL,
                    processing_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nuggets (
                    id TEXT PRIMARY KEY,
                    note_id TEXT NOT NULL,
                    original_note_excerpt TEXT NOT NULL,
                    ai_title TEXT NOT NULL,
                    ai_content TEXT NOT NULL,
                    ai_tags_json TEXT NOT NULL,
                    edited_title TEXT,
                    edited_content TEXT,
                    edited_tags_json TEXT,
                    approved_title TEXT,
                    approved_content TEXT,
                    approved_tags_json TEXT,
                    approved_content_hash TEXT,
                    suggested_scope TEXT NOT NULL,
                    scope_explanation TEXT NOT NULL,
                    approved_scope TEXT NOT NULL DEFAULT 'PRIVATE',
                    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                    extraction_source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS risk_flags (
                    id TEXT PRIMARY KEY,
                    nugget_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    explanation TEXT NOT NULL,
                    warning TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    source TEXT NOT NULL,
                    blocking INTEGER NOT NULL DEFAULT 1,
                    resolved INTEGER NOT NULL DEFAULT 0,
                    resolution_note TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (nugget_id) REFERENCES nuggets(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    nugget_id TEXT NOT NULL,
                    approved_content_hash TEXT NOT NULL,
                    selected_scope TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    confirmed_consequences INTEGER NOT NULL DEFAULT 0,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    invalidated_at TEXT,
                    FOREIGN KEY (nugget_id) REFERENCES nuggets(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS shared_publications (
                    id TEXT PRIMARY KEY,
                    nugget_id TEXT NOT NULL,
                    approval_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    published_content_hash TEXT NOT NULL,
                    published_title TEXT NOT NULL,
                    published_content TEXT NOT NULL,
                    published_tags_json TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    FOREIGN KEY (nugget_id) REFERENCES nuggets(id) ON DELETE CASCADE,
                    FOREIGN KEY (approval_id) REFERENCES approvals(id) ON DELETE RESTRICT
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    input_id TEXT NOT NULL,
                    nugget_id TEXT,
                    event_type TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    sharing_scope TEXT NOT NULL DEFAULT 'PRIVATE',
                    timestamp TEXT NOT NULL,
                    reason TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS prevent_audit_update
                BEFORE UPDATE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'Audit records are append-only and cannot be overwritten.');
                END;

                CREATE TRIGGER IF NOT EXISTS prevent_audit_delete
                BEFORE DELETE ON audit_events
                BEGIN
                    SELECT RAISE(ABORT, 'Audit records are append-only and cannot be deleted.');
                END;
                """
            )

    # --- Notes ---

    def save_note(self, note: Note) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO notes (id, content, content_hash, source_label, processing_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    note.id,
                    note.content,
                    note.content_hash,
                    note.source_label,
                    note.processing_status,
                    note.created_at.isoformat(),
                ),
            )

    def update_note_status(self, note_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE notes SET processing_status = ? WHERE id = ?",
                (status, note_id),
            )

    def get_note(self, note_id: str) -> Optional[Note]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        return Note(
            id=row["id"],
            content=row["content"],
            content_hash=row["content_hash"],
            source_label=row["source_label"],
            processing_status=row["processing_status"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_notes(self) -> list[Note]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notes ORDER BY created_at DESC"
            ).fetchall()
        return [
            Note(
                id=row["id"],
                content=row["content"],
                content_hash=row["content_hash"],
                source_label=row["source_label"],
                processing_status=row["processing_status"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    # --- Nuggets & Risk Flags ---

    def save_nugget(self, nugget: KnowledgeNugget) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO nuggets (
                    id, note_id, original_note_excerpt,
                    ai_title, ai_content, ai_tags_json,
                    edited_title, edited_content, edited_tags_json,
                    approved_title, approved_content, approved_tags_json, approved_content_hash,
                    suggested_scope, scope_explanation, approved_scope,
                    status, extraction_source, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nugget.id,
                    nugget.note_id,
                    nugget.original_note_excerpt,
                    nugget.ai_title,
                    nugget.ai_content,
                    json.dumps(nugget.ai_tags),
                    nugget.edited_title,
                    nugget.edited_content,
                    json.dumps(nugget.edited_tags) if nugget.edited_tags is not None else None,
                    nugget.approved_title,
                    nugget.approved_content,
                    json.dumps(nugget.approved_tags) if nugget.approved_tags is not None else None,
                    nugget.approved_content_hash,
                    nugget.suggested_scope.value,
                    nugget.scope_explanation,
                    nugget.approved_scope.value,
                    nugget.status.value,
                    nugget.extraction_source,
                    nugget.created_at.isoformat(),
                    nugget.updated_at.isoformat(),
                ),
            )
            self._insert_risk_flags(conn, nugget.risk_flags)

    def update_nugget(self, nugget: KnowledgeNugget, replace_risks: bool = False) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE nuggets SET
                    edited_title = ?,
                    edited_content = ?,
                    edited_tags_json = ?,
                    approved_title = ?,
                    approved_content = ?,
                    approved_tags_json = ?,
                    approved_content_hash = ?,
                    approved_scope = ?,
                    status = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    nugget.edited_title,
                    nugget.edited_content,
                    json.dumps(nugget.edited_tags) if nugget.edited_tags is not None else None,
                    nugget.approved_title,
                    nugget.approved_content,
                    json.dumps(nugget.approved_tags) if nugget.approved_tags is not None else None,
                    nugget.approved_content_hash,
                    nugget.approved_scope.value,
                    nugget.status.value,
                    nugget.updated_at.isoformat(),
                    nugget.id,
                ),
            )
            if replace_risks:
                conn.execute("DELETE FROM risk_flags WHERE nugget_id = ?", (nugget.id,))
                self._insert_risk_flags(conn, nugget.risk_flags)

    def _insert_risk_flags(self, conn: sqlite3.Connection, flags: list[RiskFlag]) -> None:
        for flag in flags:
            conn.execute(
                """
                INSERT INTO risk_flags (
                    id, nugget_id, category, severity, explanation, warning,
                    recommended_action, source, blocking, resolved, resolution_note, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    flag.id,
                    flag.nugget_id,
                    flag.category.value,
                    flag.severity.value,
                    flag.explanation,
                    flag.warning,
                    flag.recommended_action,
                    flag.source,
                    1 if flag.blocking else 0,
                    1 if flag.resolved else 0,
                    flag.resolution_note,
                    flag.created_at.isoformat(),
                ),
            )

    def update_risk_flag_resolution(
        self, risk_id: str, resolved: bool, resolution_note: Optional[str] = None
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE risk_flags SET resolved = ?, resolution_note = ? WHERE id = ?",
                (1 if resolved else 0, resolution_note, risk_id),
            )

    def _row_to_nugget(self, conn: sqlite3.Connection, row: sqlite3.Row) -> KnowledgeNugget:
        flag_rows = conn.execute(
            "SELECT * FROM risk_flags WHERE nugget_id = ? ORDER BY created_at ASC",
            (row["id"],),
        ).fetchall()
        flags = [
            RiskFlag(
                id=fr["id"],
                nugget_id=fr["nugget_id"],
                category=RiskCategory(fr["category"]),
                severity=RiskSeverity(fr["severity"]),
                explanation=fr["explanation"],
                warning=fr["warning"],
                recommended_action=fr["recommended_action"],
                source=fr["source"],
                blocking=bool(fr["blocking"]),
                resolved=bool(fr["resolved"]),
                resolution_note=fr["resolution_note"],
                created_at=datetime.fromisoformat(fr["created_at"]),
            )
            for fr in flag_rows
        ]
        return KnowledgeNugget(
            id=row["id"],
            note_id=row["note_id"],
            original_note_excerpt=row["original_note_excerpt"],
            ai_title=row["ai_title"],
            ai_content=row["ai_content"],
            ai_tags=json.loads(row["ai_tags_json"]),
            edited_title=row["edited_title"],
            edited_content=row["edited_content"],
            edited_tags=json.loads(row["edited_tags_json"]) if row["edited_tags_json"] is not None else None,
            approved_title=row["approved_title"],
            approved_content=row["approved_content"],
            approved_tags=json.loads(row["approved_tags_json"]) if row["approved_tags_json"] is not None else None,
            approved_content_hash=row["approved_content_hash"],
            suggested_scope=SharingScope(row["suggested_scope"]),
            scope_explanation=row["scope_explanation"],
            approved_scope=SharingScope(row["approved_scope"]),
            status=NuggetStatus(row["status"]),
            extraction_source=row["extraction_source"],
            risk_flags=flags,
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def get_nugget(self, nugget_id: str) -> Optional[KnowledgeNugget]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM nuggets WHERE id = ?", (nugget_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_nugget(conn, row)

    def list_nuggets(self, status: Optional[NuggetStatus] = None) -> list[KnowledgeNugget]:
        with self.connect() as conn:
            if status is not None:
                rows = conn.execute(
                    "SELECT * FROM nuggets WHERE status = ? ORDER BY updated_at DESC",
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nuggets ORDER BY updated_at DESC"
                ).fetchall()
            return [self._row_to_nugget(conn, row) for row in rows]

    # --- Approvals ---

    def save_approval(self, approval: Approval) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                    id, nugget_id, approved_content_hash, selected_scope,
                    decision, confirmed_consequences, reason, created_at, invalidated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.id,
                    approval.nugget_id,
                    approval.approved_content_hash,
                    approval.selected_scope.value,
                    approval.decision,
                    1 if approval.confirmed_consequences else 0,
                    approval.reason,
                    approval.created_at.isoformat(),
                    _dt_to_str(approval.invalidated_at),
                ),
            )

    def get_active_approval(self, nugget_id: str) -> Optional[Approval]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM approvals
                WHERE nugget_id = ? AND decision = 'APPROVED' AND invalidated_at IS NULL
                ORDER BY created_at DESC LIMIT 1
                """,
                (nugget_id,),
            ).fetchone()
        if row is None:
            return None
        return Approval(
            id=row["id"],
            nugget_id=row["nugget_id"],
            approved_content_hash=row["approved_content_hash"],
            selected_scope=SharingScope(row["selected_scope"]),
            decision=row["decision"],
            confirmed_consequences=bool(row["confirmed_consequences"]),
            reason=row["reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            invalidated_at=_str_to_dt(row["invalidated_at"]),
        )

    def invalidate_active_approvals(
        self, nugget_id: str, reason: str, invalidated_at: datetime
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET decision = 'INVALIDATED',
                    reason = ?,
                    invalidated_at = ?
                WHERE nugget_id = ? AND decision = 'APPROVED' AND invalidated_at IS NULL
                """,
                (reason, invalidated_at.isoformat(), nugget_id),
            )
            return cursor.rowcount

    def list_approvals(self, nugget_id: Optional[str] = None) -> list[Approval]:
        with self.connect() as conn:
            if nugget_id is not None:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE nugget_id = ? ORDER BY created_at DESC",
                    (nugget_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM approvals ORDER BY created_at DESC"
                ).fetchall()
        return [
            Approval(
                id=row["id"],
                nugget_id=row["nugget_id"],
                approved_content_hash=row["approved_content_hash"],
                selected_scope=SharingScope(row["selected_scope"]),
                decision=row["decision"],
                confirmed_consequences=bool(row["confirmed_consequences"]),
                reason=row["reason"],
                created_at=datetime.fromisoformat(row["created_at"]),
                invalidated_at=_str_to_dt(row["invalidated_at"]),
            )
            for row in rows
        ]

    # --- Shared Publications ---

    def save_shared_publication(self, pub: SharedPublication) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO shared_publications (
                    id, nugget_id, approval_id, scope, published_content_hash,
                    published_title, published_content, published_tags_json, published_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pub.id,
                    pub.nugget_id,
                    pub.approval_id,
                    pub.scope.value,
                    pub.published_content_hash,
                    pub.published_title,
                    pub.published_content,
                    json.dumps(pub.published_tags),
                    pub.published_at.isoformat(),
                ),
            )

    def list_shared_publications(self, nugget_id: Optional[str] = None) -> list[SharedPublication]:
        with self.connect() as conn:
            if nugget_id is not None:
                rows = conn.execute(
                    "SELECT * FROM shared_publications WHERE nugget_id = ? ORDER BY published_at DESC",
                    (nugget_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM shared_publications ORDER BY published_at DESC"
                ).fetchall()
        return [
            SharedPublication(
                id=row["id"],
                nugget_id=row["nugget_id"],
                approval_id=row["approval_id"],
                scope=SharingScope(row["scope"]),
                published_content_hash=row["published_content_hash"],
                published_title=row["published_title"],
                published_content=row["published_content"],
                published_tags=json.loads(row["published_tags_json"]),
                published_at=datetime.fromisoformat(row["published_at"]),
            )
            for row in rows
        ]

    # --- Audit Events (append-only) ---

    def append_audit_event(self, event: AuditEvent) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    id, input_id, nugget_id, event_type, decision, sharing_scope, timestamp, reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.input_id,
                    event.nugget_id,
                    event.event_type.value,
                    event.decision,
                    event.sharing_scope.value,
                    event.timestamp.isoformat(),
                    event.reason,
                ),
            )

    def list_audit_events(
        self,
        event_type: Optional[AuditEventType] = None,
        limit: int = 200,
    ) -> list[AuditEvent]:
        with self.connect() as conn:
            if event_type is not None:
                rows = conn.execute(
                    "SELECT * FROM audit_events WHERE event_type = ? ORDER BY timestamp DESC LIMIT ?",
                    (event_type.value, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            AuditEvent(
                id=row["id"],
                input_id=row["input_id"],
                nugget_id=row["nugget_id"],
                event_type=AuditEventType(row["event_type"]),
                decision=row["decision"],
                sharing_scope=SharingScope(row["sharing_scope"]),
                timestamp=datetime.fromisoformat(row["timestamp"]),
                reason=row["reason"],
            )
            for row in rows
        ]

    # --- Dashboard Metrics ---

    def get_dashboard_metrics(self) -> dict[str, int]:
        with self.connect() as conn:
            total_notes = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            total_nuggets = conn.execute("SELECT COUNT(*) FROM nuggets").fetchone()[0]
            awaiting_review = conn.execute(
                "SELECT COUNT(*) FROM nuggets WHERE status IN (?, ?)",
                (NuggetStatus.PENDING_REVIEW.value, NuggetStatus.NEEDS_HUMAN_REVIEW.value),
            ).fetchone()[0]
            approved_private = conn.execute(
                "SELECT COUNT(*) FROM nuggets WHERE status = ?",
                (NuggetStatus.APPROVED_PRIVATE.value,),
            ).fetchone()[0]
            approved_shared = conn.execute(
                "SELECT COUNT(*) FROM nuggets WHERE status = ?",
                (NuggetStatus.APPROVED_SHARED.value,),
            ).fetchone()[0]
            rejected = conn.execute(
                "SELECT COUNT(*) FROM nuggets WHERE status = ?",
                (NuggetStatus.REJECTED.value,),
            ).fetchone()[0]
        return {
            "total_notes": total_notes,
            "total_nuggets": total_nuggets,
            "awaiting_review": awaiting_review,
            "approved_private": approved_private,
            "approved_shared": approved_shared,
            "rejected": rejected,
        }
