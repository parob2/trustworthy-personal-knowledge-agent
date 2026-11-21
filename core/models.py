from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


MAX_NOTE_LENGTH = 4000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def normalize_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for tag in tags:
        norm = " ".join(tag.strip().lower().split())
        if norm and norm not in seen:
            seen.add(norm)
            cleaned.append(norm)
    return cleaned


def compute_content_hash(title: str, content: str, tags: list[str]) -> str:
    """Compute a canonical SHA-256 digest of nugget title, content, and tags."""
    payload = {
        "title": title.strip(),
        "content": content.strip(),
        "tags": sorted(normalize_tags(tags)),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class SharingScope(str, Enum):
    PRIVATE = "PRIVATE"
    PROJECT_TEAM = "PROJECT_TEAM"
    DEPARTMENT = "DEPARTMENT"
    ORGANISATION = "ORGANISATION"

    @property
    def label(self) -> str:
        return {
            SharingScope.PRIVATE: "Private (Only You)",
            SharingScope.PROJECT_TEAM: "Project Team",
            SharingScope.DEPARTMENT: "Department",
            SharingScope.ORGANISATION: "Organisation",
        }[self]

    @property
    def is_shared(self) -> bool:
        return self != SharingScope.PRIVATE


class NuggetStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED_PRIVATE = "APPROVED_PRIVATE"
    APPROVED_SHARED = "APPROVED_SHARED"
    REJECTED = "REJECTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class RiskCategory(str, Enum):
    PERSONAL_INFORMATION = "Personal information"
    CREDENTIALS_AND_SECRETS = "Credentials and secrets"
    CONFIDENTIAL_INFORMATION = "Confidential information"
    UNSUPPORTED_CLAIMS = "Unsupported claims"


class RiskSeverity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AuditEventType(str, Enum):
    NOTE_CAPTURED = "NOTE_CAPTURED"
    NUGGET_GENERATED = "NUGGET_GENERATED"
    RISK_WARNING_RAISED = "RISK_WARNING_RAISED"
    NUGGET_EDITED = "NUGGET_EDITED"
    NUGGET_REJECTED = "NUGGET_REJECTED"
    NUGGET_APPROVED = "NUGGET_APPROVED"
    APPROVAL_INVALIDATED = "APPROVAL_INVALIDATED"
    SHARING_AUTHORIZED = "SHARING_AUTHORIZED"
    SHARING_BLOCKED = "SHARING_BLOCKED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class RiskFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("risk"))
    nugget_id: str
    category: RiskCategory
    severity: RiskSeverity
    explanation: str
    warning: str
    recommended_action: str
    source: Literal["deterministic", "ai"] = "deterministic"
    blocking: bool = True
    resolved: bool = False
    resolution_note: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("note"))
    content: str = Field(..., min_length=1, max_length=MAX_NOTE_LENGTH)
    content_hash: str = ""
    source_label: str = "manual"
    processing_status: Literal["CAPTURED", "PROCESSED", "FAILED_SAFE"] = "CAPTURED"
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Note content cannot be empty.")
        if len(value) > MAX_NOTE_LENGTH:
            raise ValueError(
                f"Note content exceeds maximum length of {MAX_NOTE_LENGTH} characters."
            )
        return value


class KnowledgeNugget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("nug"))
    note_id: str
    original_note_excerpt: str

    # Stage 2: AI-generated suggestion (immutable once created)
    ai_title: str = Field(..., min_length=1, max_length=240)
    ai_content: str = Field(..., min_length=1, max_length=4000)
    ai_tags: list[str] = Field(default_factory=list)

    # Stage 3: Human-edited version (None until human edits)
    edited_title: Optional[str] = None
    edited_content: Optional[str] = None
    edited_tags: Optional[list[str]] = None

    # Stage 4: Human-approved version snapshot (bound to exact approved content)
    approved_title: Optional[str] = None
    approved_content: Optional[str] = None
    approved_tags: Optional[list[str]] = None
    approved_content_hash: Optional[str] = None

    # Recommendations vs enforced decision
    suggested_scope: SharingScope = SharingScope.PRIVATE
    scope_explanation: str = ""
    approved_scope: SharingScope = SharingScope.PRIVATE
    status: NuggetStatus = NuggetStatus.PENDING_REVIEW
    extraction_source: str = "deterministic_fallback"
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def current_title(self) -> str:
        return self.edited_title if self.edited_title is not None else self.ai_title

    @property
    def current_content(self) -> str:
        return self.edited_content if self.edited_content is not None else self.ai_content

    @property
    def current_tags(self) -> list[str]:
        return self.edited_tags if self.edited_tags is not None else self.ai_tags

    @property
    def current_content_hash(self) -> str:
        return compute_content_hash(
            self.current_title,
            self.current_content,
            self.current_tags,
        )

    @property
    def has_human_edits(self) -> bool:
        return (
            self.edited_title is not None
            or self.edited_content is not None
            or self.edited_tags is not None
        )

    @property
    def unresolved_blocking_risks(self) -> list[RiskFlag]:
        return [rf for rf in self.risk_flags if rf.blocking and not rf.resolved]


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("appr"))
    nugget_id: str
    approved_content_hash: str
    selected_scope: SharingScope
    decision: Literal["APPROVED", "REJECTED", "INVALIDATED"]
    confirmed_consequences: bool = False
    reason: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    invalidated_at: Optional[datetime] = None


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("aud"))
    input_id: str
    nugget_id: Optional[str] = None
    event_type: AuditEventType
    decision: str
    sharing_scope: SharingScope = SharingScope.PRIVATE
    timestamp: datetime = Field(default_factory=utc_now)
    reason: str


class SharedPublication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("pub"))
    nugget_id: str
    approval_id: str
    scope: SharingScope
    published_content_hash: str
    published_title: str
    published_content: str
    published_tags: list[str]
    published_at: datetime = Field(default_factory=utc_now)


# --- Untrusted LLM Output Schemas (never include authorization/approval fields) ---


class LLMRiskSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str
    explanation: str = ""
    warning: str = ""
    recommended_action: str = "Keep private and review manually."


class LLMExtractedNugget(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=1, max_length=240)
    content: str = Field(..., min_length=1, max_length=2500)
    tags: list[str] = Field(default_factory=list)
    suggested_scope: SharingScope = SharingScope.PRIVATE
    scope_explanation: str = Field(
        default="Suggested scope from local extraction; requires human review."
    )
    risks: list[LLMRiskSignal] = Field(default_factory=list)

    @field_validator("tags", mode="before")
    @classmethod
    def coerce_tags(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return normalize_tags([part for part in value.split(",")])
        if isinstance(value, list):
            return normalize_tags([str(item) for item in value])
        return []

    @field_validator("risks", mode="before")
    @classmethod
    def coerce_risk_categories(cls, value: object) -> object:
        if isinstance(value, list):
            risks: list[object] = []
            for item in value:
                if isinstance(item, str):
                    category = item
                    normalized_item: object = {"category": item}
                elif isinstance(item, dict):
                    category = item.get("category")
                    normalized_item = item
                elif isinstance(item, LLMRiskSignal):
                    category = item.category
                    normalized_item = item
                else:
                    category = None
                    normalized_item = item
                if isinstance(category, str) and category.strip().upper() == "NONE":
                    continue
                risks.append(normalized_item)
            return risks
        return value

    @field_validator("suggested_scope", mode="before")
    @classmethod
    def coerce_scope(cls, value: object) -> SharingScope:
        if isinstance(value, SharingScope):
            return value
        if isinstance(value, str):
            normalized = value.strip().upper().replace(" ", "_")
            aliases = {
                "TEAM": "PROJECT_TEAM",
                "PROJECT": "PROJECT_TEAM",
                "ORG": "ORGANISATION",
                "ORGANIZATION": "ORGANISATION",
                "PUBLIC": "PRIVATE",  # Never allow unrequested external/public scope
                "EVERYONE": "PRIVATE",
            }
            normalized = aliases.get(normalized, normalized)
            if normalized in SharingScope._value2member_map_:
                return SharingScope(normalized)
        return SharingScope.PRIVATE


class LLMExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nuggets: list[LLMExtractedNugget] = Field(default_factory=list, min_length=1, max_length=5)
