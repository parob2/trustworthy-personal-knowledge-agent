from __future__ import annotations

import json
import re
from typing import Optional

from core.audit import record_audit_event
from core.database import Database
from core.models import (
    AuditEventType,
    KnowledgeNugget,
    LLMExtractedNugget,
    LLMExtractionResponse,
    Note,
    NuggetStatus,
    SharingScope,
    normalize_tags,
)
from core.ollama_client import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    check_ollama_status,
    extract_with_ollama,
)
from core.risk_detection import detect_deterministic_risks, evaluate_risks
from logging_config import get_logger

logger = get_logger("extraction")

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "between", "but", "by",
    "discovered", "during", "for", "from", "had", "has", "have", "in", "into",
    "is", "it", "learned", "of", "on", "or", "our", "out", "over", "project",
    "that", "the", "their", "this", "to", "was", "we", "were", "with",
}

_TOPIC_KEYWORDS = {
    "deployment": "deployment",
    "validation": "validation",
    "automated": "automation",
    "configuration": "configuration",
    "migration": "migration",
    "retrospective": "retrospective",
    "stakeholder": "stakeholders",
    "engineering": "engineering",
    "product": "product",
    "coordination": "collaboration",
    "security": "security",
    "password": "security",
    "token": "security",
    "confidential": "confidential",
    "customer": "customer-data",
    "testing": "testing",
    "database": "database",
    "incident": "incident-response",
    "architecture": "architecture",
    "process": "process",
}

_INJECTION_SENTENCE_RE = re.compile(
    r"(?i)\b(?:ignore\s+(?:all\s+)?previous\s+(?:rules|instructions)|override\s+security|publish\s+this\s+information\s+to\s+everyone|auto[\s-]?approve|bypass\s+review)\b"
)


def _derive_title(statement: str) -> str:
    cleaned = re.sub(r"\s+", " ", statement).strip(" .!?;:")
    words = cleaned.split()
    if len(words) <= 8:
        return cleaned[:120].capitalize() if cleaned else "Extracted Knowledge Nugget"

    # Prefer a concise headline from key words while keeping readability
    significant = [w.strip(",.:;()[]\"'") for w in words]
    headline = " ".join(significant[:9])
    if len(headline) > 85:
        headline = headline[:82].rsplit(" ", 1)[0] + "..."
    return headline[0].upper() + headline[1:]


def _derive_tags(text: str) -> list[str]:
    lower = text.lower()
    tags: list[str] = []
    for kw, tag in _TOPIC_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", lower):
            tags.append(tag)
    if not tags:
        tokens = re.findall(r"[a-zA-Z]{4,}", lower)
        for tok in tokens:
            if tok not in _STOPWORDS:
                tags.append(tok)
            if len(tags) >= 3:
                break
    return normalize_tags(tags)[:5] or ["knowledge"]


def _split_sentences(note_text: str) -> list[str]:
    # Split on sentence boundaries and newlines without breaking emails/decimals
    raw_chunks = re.split(r"(?:\n+|(?<=[.!?])\s+(?=[A-Z0-9]))", note_text.strip())
    sentences = [chunk.strip() for chunk in raw_chunks if chunk.strip()]
    return sentences if sentences else [note_text.strip()]


def deterministic_extract(note_text: str, note_id: str) -> LLMExtractionResponse:
    """
    Deterministic, offline extraction fallback when Ollama is unavailable or returns invalid JSON.
    Logs complete simulated structured output for terminal observability.
    """
    logger.info(
        "[FALLBACK EXTRACTION START] note_id=%s | chars=%d | note_content=%s",
        note_id,
        len(note_text),
        json.dumps(note_text, ensure_ascii=False),
    )

    sentences = _split_sentences(note_text)
    pre_risks = detect_deterministic_risks(note_text, nugget_id="")
    has_sensitive = len(pre_risks) > 0

    # Group sentences safely: if 1-2 short sentences, produce 1 nugget; if longer multi-point note, up to 3 nuggets
    if len(sentences) <= 2:
        groups = [" ".join(sentences)]
    else:
        groups = []
        current: list[str] = []
        for s in sentences:
            current.append(s)
            if len(" ".join(current)) >= 140 or len(current) >= 2:
                groups.append(" ".join(current))
                current = []
        if current:
            if groups and len(current[0]) < 60:
                groups[-1] = f"{groups[-1]} {' '.join(current)}"
            else:
                groups.append(" ".join(current))
        groups = groups[:3]

    extracted: list[LLMExtractedNugget] = []
    for chunk in groups:
        chunk_risks = detect_deterministic_risks(chunk, nugget_id="")
        is_injection = bool(_INJECTION_SENTENCE_RE.search(chunk))

        if has_sensitive or chunk_risks or is_injection:
            suggested_scope = SharingScope.PRIVATE
            scope_explanation = (
                "Recommended PRIVATE because deterministic security checks detected potential "
                "sensitive data, confidentiality wording, unverified claims, or instruction-like text."
            )
        elif any(w in chunk.lower() for w in ("engineering", "product", "stakeholder", "team", "retrospective")):
            suggested_scope = SharingScope.DEPARTMENT
            scope_explanation = (
                "Suggested DEPARTMENT: appears to capture cross-team engineering/product process "
                "learning without sensitive identifiers. Human approval still required."
            )
        elif any(w in chunk.lower() for w in ("deployment", "validation", "configuration", "workflow")):
            suggested_scope = SharingScope.PROJECT_TEAM
            scope_explanation = (
                "Suggested PROJECT_TEAM: operational engineering lesson useful to project peers "
                "with no detected sensitive details. Human approval still required."
            )
        else:
            suggested_scope = SharingScope.PRIVATE
            scope_explanation = (
                "Suggested PRIVATE by default until a human reviewer determines broader relevance."
            )

        extracted.append(
            LLMExtractedNugget(
                title=_derive_title(chunk),
                content=chunk,
                tags=_derive_tags(chunk),
                suggested_scope=suggested_scope,
                scope_explanation=scope_explanation,
                risks=[],
            )
        )

    response = LLMExtractionResponse(nuggets=extracted)
    logger.info(
        "[FALLBACK EXTRACTION JSON] note_id=%s | output=%s",
        note_id,
        response.model_dump_json(),
    )
    return response


def process_note(
    note: Note,
    db: Database,
    use_ollama: bool = True,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
) -> list[KnowledgeNugget]:
    """
    Transform a captured note into persisted KnowledgeNuggets with risk evaluation,
    private-by-default enforcement, provenance initialization, and audit events.
    """
    extraction_source = "deterministic_fallback"
    uncertain_classification = False
    llm_response: Optional[LLMExtractionResponse] = None

    try:
        if use_ollama:
            status = check_ollama_status(base_url=ollama_url, model_name=ollama_model)
            if status.available and status.model_ready:
                try:
                    llm_response = extract_with_ollama(
                        note_text=note.content,
                        note_id=note.id,
                        base_url=ollama_url,
                        model_name=ollama_model,
                    )
                    extraction_source = f"ollama:{ollama_model}"
                except Exception as exc:
                    logger.warning(
                        "[AI FALLBACK TRIGGERED] note_id=%s | reason=%s: %s",
                        note.id,
                        type(exc).__name__,
                        exc,
                    )
                    uncertain_classification = True
                    record_audit_event(
                        db=db,
                        input_id=note.id,
                        event_type=AuditEventType.EXTRACTION_FAILED,
                        decision="FALLBACK_PRIVATE",
                        sharing_scope=SharingScope.PRIVATE,
                        reason=f"Ollama extraction failed ({type(exc).__name__}); used deterministic fallback and kept private.",
                    )
            else:
                logger.info(
                    "[AI SKIPPED -> FALLBACK] note_id=%s | reason=%s",
                    note.id,
                    status.message,
                )

        if llm_response is None:
            llm_response = deterministic_extract(note.content, note.id)

        created_nuggets: list[KnowledgeNugget] = []
        excerpt = note.content[:240] + ("..." if len(note.content) > 240 else "")

        for item in llm_response.nuggets:
            # Force private-by-default regardless of any model output.
            # Model suggested_scope is kept strictly as a recommendation!
            prelim_status = (
                NuggetStatus.NEEDS_HUMAN_REVIEW
                if uncertain_classification
                else NuggetStatus.PENDING_REVIEW
            )
            nugget = KnowledgeNugget(
                note_id=note.id,
                original_note_excerpt=excerpt,
                ai_title=item.title.strip(),
                ai_content=item.content.strip(),
                ai_tags=normalize_tags(item.tags),
                suggested_scope=item.suggested_scope,
                scope_explanation=item.scope_explanation.strip(),
                approved_scope=SharingScope.PRIVATE,  # Non-negotiable private-by-default
                status=prelim_status,
                extraction_source=extraction_source,
            )

            flags = evaluate_risks(
                title=nugget.ai_title,
                content=nugget.ai_content,
                tags=nugget.ai_tags,
                nugget_id=nugget.id,
                source_note_text=note.content,
                ai_signals=item.risks,
                uncertain_classification=uncertain_classification,
            )
            nugget.risk_flags = flags
            if any(f.blocking and not f.resolved for f in flags):
                nugget.status = NuggetStatus.NEEDS_HUMAN_REVIEW

            db.save_nugget(nugget)
            created_nuggets.append(nugget)

            record_audit_event(
                db=db,
                input_id=note.id,
                nugget_id=nugget.id,
                event_type=AuditEventType.NUGGET_GENERATED,
                decision=nugget.status.value,
                sharing_scope=SharingScope.PRIVATE,
                reason=(
                    f"Generated nugget '{nugget.ai_title[:60]}' via {extraction_source}; "
                    f"AI suggested={nugget.suggested_scope.value}, enforced=PRIVATE."
                ),
            )

            for flag in flags:
                record_audit_event(
                    db=db,
                    input_id=note.id,
                    nugget_id=nugget.id,
                    event_type=AuditEventType.RISK_WARNING_RAISED,
                    decision="WARNING_BLOCKING" if flag.blocking else "WARNING_ADVISORY",
                    sharing_scope=SharingScope.PRIVATE,
                    reason=f"[{flag.category.value}] ({flag.source}) {flag.explanation}",
                )

        db.update_note_status(note.id, "PROCESSED")
        logger.info(
            "[EXTRACTION COMPLETE] note_id=%s | source=%s | nuggets=%d",
            note.id,
            extraction_source,
            len(created_nuggets),
        )
        return created_nuggets

    except Exception as exc:
        # Fail safely: retain original note as private, mark FAILED_SAFE, audit failure
        db.update_note_status(note.id, "FAILED_SAFE")
        logger.exception("[EXTRACTION FAILED SAFE] note_id=%s | error=%s", note.id, exc)
        record_audit_event(
            db=db,
            input_id=note.id,
            event_type=AuditEventType.EXTRACTION_FAILED,
            decision="FAILED_SAFE_PRIVATE",
            sharing_scope=SharingScope.PRIVATE,
            reason=f"Extraction failed safely ({type(exc).__name__}); original note retained as PRIVATE.",
        )
        raise
