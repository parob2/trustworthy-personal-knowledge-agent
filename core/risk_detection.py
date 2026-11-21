from __future__ import annotations

import re
from typing import Iterable, Optional

from core.models import (
    LLMRiskSignal,
    RiskCategory,
    RiskFlag,
    RiskSeverity,
)
from logging_config import get_logger

logger = get_logger("risk_detection")

# --- 1. Personal Information Patterns ---
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_PATTERN = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{3,4}[\s.-]\d{3,4}(?!\w)"
)
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PII_LABEL_PATTERN = re.compile(
    r"(?i)(?:\b(?:customer\s+contact|personal\s+email|phone\s+number|mobile\s+number|home\s+address|passport\s*(?:no|number|#)?|national\s+id|employee\s+id)\s*[:=#-]|\b(?:date\s+of\s+birth|dob|ssn|social\s+security\s+number)\b)"
)

# --- 2. Credentials & Secrets Patterns ---
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:password|passwd|pwd|passphrase|pin|api(?:[\s_-]*key)?|key|token|secret[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|client[_-]?secret|private[_-]?key)\s*[:=]\s*['\"]?[^\s'\"]{4,}"
)
_KNOWN_TOKEN_PATTERN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{16,}|gho_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}|AKIA[0-9A-Z]{16}|xoxb-[0-9A-Za-z-]+|xoxp-[0-9A-Za-z-]+)\b"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}\b")
_PEM_KEY_PATTERN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")

# --- 3. Confidential Information Patterns ---
_CONFIDENTIAL_PATTERN = re.compile(
    r"(?i)\b(?:strictly\s+confidential|confidential|internal[\s-]+only|do\s+not\s+share|must\s+not\s+be\s+shared|not\s+for\s+external|restricted\s+(?:information|data|project|access)|proprietary|under\s+nda|nda\s+only|embargoed|non-public|classified)\b"
)

# --- 4. Unsupported Claims & Prompt Injection Patterns ---
_UNVERIFIED_CLAIM_PATTERN = re.compile(
    r"(?i)\b(?:100%|zero\s+errors|never\s+fails|always\s+prevents|eliminates\s+all|guaranteed\s+to|undoubtedly|without\s+a\s+doubt|everyone\s+knows|obviously\s+proves|10x\s+faster|100x\s+better|dramatically\s+proven)\b"
)
_EVIDENCE_MARKER_PATTERN = re.compile(
    r"(?i)\b(?:measured|benchmark|data\s+from|according\s+to|observed\s+in|test\s+results|study|experiment|logs\s+show|metrics\s+show)\b"
)
_PERCENT_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?%")
_PROMPT_INJECTION_PATTERN = re.compile(
    r"(?i)\b(?:ignore\s+(?:all\s+)?previous\s+(?:rules|instructions)|override\s+security|publish\s+this\s+information\s+to\s+everyone|auto[\s-]?approve|bypass\s+review)\b"
)


def detect_deterministic_risks(
    text: str,
    nugget_id: str = "",
    source_note_text: Optional[str] = None,
) -> list[RiskFlag]:
    """Run deterministic security and quality checks. AI models cannot suppress or override these."""
    flags: list[RiskFlag] = []

    # 1. Personal information
    pii_reasons: list[str] = []
    if _EMAIL_PATTERN.search(text):
        pii_reasons.append("email address")
    if _PHONE_PATTERN.search(text):
        pii_reasons.append("phone number")
    if _SSN_PATTERN.search(text):
        pii_reasons.append("government/SSN-like identifier")
    if _PII_LABEL_PATTERN.search(text):
        pii_reasons.append("personal contact or identifier reference")

    if pii_reasons:
        flags.append(
            RiskFlag(
                nugget_id=nugget_id,
                category=RiskCategory.PERSONAL_INFORMATION,
                severity=RiskSeverity.HIGH,
                explanation=f"Detected potential personal information ({', '.join(pii_reasons)}).",
                warning="Contains personal identifiers or contact details that must not be exposed broadly.",
                recommended_action="Remove or anonymize personal details and keep scope PRIVATE until redacted.",
                source="deterministic",
                blocking=True,
                resolved=False,
            )
        )

    # 2. Credentials and secrets
    secret_reasons: list[str] = []
    if _SECRET_ASSIGNMENT_PATTERN.search(text):
        secret_reasons.append("password or credential assignment")
    if _KNOWN_TOKEN_PATTERN.search(text):
        secret_reasons.append("API key or access token")
    if _BEARER_PATTERN.search(text):
        secret_reasons.append("Bearer token")
    if _PEM_KEY_PATTERN.search(text):
        secret_reasons.append("private cryptographic key")

    if secret_reasons:
        flags.append(
            RiskFlag(
                nugget_id=nugget_id,
                category=RiskCategory.CREDENTIALS_AND_SECRETS,
                severity=RiskSeverity.HIGH,
                explanation=f"Detected potential credentials or secrets ({', '.join(secret_reasons)}).",
                warning="Secrets, passwords, or API tokens must never be shared in knowledge nuggets.",
                recommended_action="Delete all credentials immediately, rotate compromised secrets, and keep PRIVATE.",
                source="deterministic",
                blocking=True,
                resolved=False,
            )
        )

    # 3. Confidential information
    conf_matches = sorted({m.group(0).lower() for m in _CONFIDENTIAL_PATTERN.finditer(text)})
    if conf_matches:
        flags.append(
            RiskFlag(
                nugget_id=nugget_id,
                category=RiskCategory.CONFIDENTIAL_INFORMATION,
                severity=RiskSeverity.HIGH,
                explanation=f"Detected confidentiality or restriction wording ({', '.join(conf_matches[:4])}).",
                warning="Source or nugget explicitly indicates confidential, internal-only, or restricted content.",
                recommended_action="Keep PRIVATE or remove restricted material before reconsidering internal sharing.",
                source="deterministic",
                blocking=True,
                resolved=False,
            )
        )

    # Prompt injection attempt inside untrusted note text -> treat as confidentiality/integrity warning
    if _PROMPT_INJECTION_PATTERN.search(text):
        flags.append(
            RiskFlag(
                nugget_id=nugget_id,
                category=RiskCategory.CONFIDENTIAL_INFORMATION,
                severity=RiskSeverity.HIGH,
                explanation="Detected instruction-like text attempting to override privacy or sharing rules.",
                warning="Untrusted note text attempted to alter sharing authorization; instruction ignored.",
                recommended_action="Keep PRIVATE and verify that extracted content reflects factual knowledge only.",
                source="deterministic",
                blocking=True,
                resolved=False,
            )
        )

    # 4. Unsupported claims
    claim_reasons: list[str] = []
    if _UNVERIFIED_CLAIM_PATTERN.search(text) and not _EVIDENCE_MARKER_PATTERN.search(text):
        claim_reasons.append("strong absolute or unverified improvement phrasing without cited evidence")

    if source_note_text is not None:
        source_percents = set(_PERCENT_NUMBER_PATTERN.findall(source_note_text))
        nugget_percents = set(_PERCENT_NUMBER_PATTERN.findall(text))
        invented_percents = nugget_percents - source_percents
        if invented_percents:
            claim_reasons.append(
                f"numeric percentage(s) ({', '.join(sorted(invented_percents))}) not found in the original note"
            )

    if claim_reasons:
        flags.append(
            RiskFlag(
                nugget_id=nugget_id,
                category=RiskCategory.UNSUPPORTED_CLAIMS,
                severity=RiskSeverity.MEDIUM,
                explanation=f"Detected potential unsupported claim ({'; '.join(claim_reasons)}).",
                warning="Knowledge statement may overstate impact or go beyond supplied source evidence.",
                recommended_action="Qualify the statement to match observed evidence or attach supporting context before sharing.",
                source="deterministic",
                blocking=True,
                resolved=False,
            )
        )

    return flags


def _map_ai_category(raw_category: str) -> RiskCategory:
    norm = raw_category.strip().lower()
    if any(k in norm for k in ("personal", "pii", "email", "phone", "identity")):
        return RiskCategory.PERSONAL_INFORMATION
    if any(k in norm for k in ("credential", "secret", "password", "token", "key")):
        return RiskCategory.CREDENTIALS_AND_SECRETS
    if any(k in norm for k in ("confidential", "restricted", "internal", "nda", "proprietary")):
        return RiskCategory.CONFIDENTIAL_INFORMATION
    return RiskCategory.UNSUPPORTED_CLAIMS


def evaluate_risks(
    title: str,
    content: str,
    tags: Iterable[str],
    nugget_id: str = "",
    source_note_text: Optional[str] = None,
    ai_signals: Optional[list[LLMRiskSignal]] = None,
    uncertain_classification: bool = False,
) -> list[RiskFlag]:
    """
    Combine deterministic security checks with optional AI risk signals.
    Deterministic flags ALWAYS take precedence and cannot be removed or downgraded by AI.
    """
    combined_nugget_text = f"{title}\n{content}\n{' '.join(tags)}"

    # Always scan the nugget content deterministically; also scan source note for PII/secrets/confidentiality
    # if we are evaluating initial extraction so context leaks don't slip through.
    deterministic_flags = detect_deterministic_risks(
        text=combined_nugget_text,
        nugget_id=nugget_id,
        source_note_text=source_note_text,
    )

    if source_note_text:
        source_det = detect_deterministic_risks(
            text=source_note_text,
            nugget_id=nugget_id,
            source_note_text=None,
        )
        # If source note contains high-severity confidentiality/credentials/PII or prompt injection,
        # propagate if not already flagged on the nugget text.
        existing_cats = {f.category for f in deterministic_flags}
        for sf in source_det:
            if sf.category in (
                RiskCategory.PERSONAL_INFORMATION,
                RiskCategory.CREDENTIALS_AND_SECRETS,
                RiskCategory.CONFIDENTIAL_INFORMATION,
            ) and sf.category not in existing_cats:
                deterministic_flags.append(
                    RiskFlag(
                        nugget_id=nugget_id,
                        category=sf.category,
                        severity=sf.severity,
                        explanation=f"Inherited from source note: {sf.explanation}",
                        warning=sf.warning,
                        recommended_action=sf.recommended_action,
                        source="deterministic",
                        blocking=True,
                        resolved=False,
                    )
                )
                existing_cats.add(sf.category)

    all_flags = list(deterministic_flags)
    seen_categories = {(f.category, f.source) for f in all_flags}

    if ai_signals:
        for sig in ai_signals:
            cat = _map_ai_category(sig.category)
            # AI can only add new warnings, never remove deterministic ones.
            if any(f.category == cat and f.source == "deterministic" for f in all_flags):
                continue
            if (cat, "ai") in seen_categories:
                continue
            severity = (
                RiskSeverity.HIGH
                if cat in (
                    RiskCategory.PERSONAL_INFORMATION,
                    RiskCategory.CREDENTIALS_AND_SECRETS,
                    RiskCategory.CONFIDENTIAL_INFORMATION,
                )
                else RiskSeverity.MEDIUM
            )
            all_flags.append(
                RiskFlag(
                    nugget_id=nugget_id,
                    category=cat,
                    severity=severity,
                    explanation=sig.explanation.strip() or f"AI flagged potential {cat.value.lower()}.",
                    warning=sig.warning.strip() or f"Model detected potential {cat.value.lower()} risk.",
                    recommended_action=sig.recommended_action.strip() or "Review manually and keep PRIVATE if unsure.",
                    source="ai",
                    blocking=True,
                    resolved=False,
                )
            )
            seen_categories.add((cat, "ai"))

    if uncertain_classification:
        all_flags.append(
            RiskFlag(
                nugget_id=nugget_id,
                category=RiskCategory.UNSUPPORTED_CLAIMS,
                severity=RiskSeverity.MEDIUM,
                explanation="AI extraction failed or produced uncertain classification; deterministic fallback used.",
                warning="Requires careful human review before any sharing consideration.",
                recommended_action="Verify accuracy, privacy, and claims manually before approving.",
                source="deterministic",
                blocking=True,
                resolved=False,
            )
        )

    logger.info(
        "RISK_EVAL | nugget_id=%s | total_flags=%d | blocking=%d | categories=%s",
        nugget_id or "pending",
        len(all_flags),
        sum(1 for f in all_flags if f.blocking and not f.resolved),
        [f.category.value for f in all_flags],
    )
    return all_flags
