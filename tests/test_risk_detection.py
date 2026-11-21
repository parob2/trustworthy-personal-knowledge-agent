from __future__ import annotations

from core.models import LLMRiskSignal, RiskCategory
from core.risk_detection import detect_deterministic_risks, evaluate_risks


def test_detects_personal_information() -> None:
    flags = detect_deterministic_risks(
        "Customer contact: john@example.com or +1 415-555-0199. SSN 123-45-6789."
    )
    categories = {f.category for f in flags}
    assert RiskCategory.PERSONAL_INFORMATION in categories
    assert all(f.blocking for f in flags)


def test_detects_credentials_and_secrets() -> None:
    flags = detect_deterministic_risks(
        "Staging api_key=sk-test1234567890abcdef and password=MySecretPass99!"
    )
    categories = {f.category for f in flags}
    assert RiskCategory.CREDENTIALS_AND_SECRETS in categories


def test_detects_common_credential_assignment_labels() -> None:
    for assignment in (
        "API=abcd1234",
        "API key=abcd1234",
        "key=abcd1234",
        "token=abcd1234",
        "PIN=1234",
        "password=abcd1234",
    ):
        flags = detect_deterministic_risks(assignment)
        assert RiskCategory.CREDENTIALS_AND_SECRETS in {f.category for f in flags}


def test_detects_confidential_information() -> None:
    flags = detect_deterministic_risks(
        "The internal migration project is strictly confidential and must not be shared externally."
    )
    categories = {f.category for f in flags}
    assert RiskCategory.CONFIDENTIAL_INFORMATION in categories


def test_detects_unsupported_claims_and_invented_metrics() -> None:
    flags = detect_deterministic_risks(
        "Automated checks are guaranteed to deliver 100% reliability and 45% cost savings.",
        source_note_text="Automated checks helped catch configuration errors before deployment.",
    )
    categories = {f.category for f in flags}
    assert RiskCategory.UNSUPPORTED_CLAIMS in categories


def test_ai_cannot_override_deterministic_security_checks() -> None:
    # Even if AI reports zero risks (or only an unrelated unsupported-claim note),
    # deterministic PII & confidentiality checks remain active and blocking.
    flags = evaluate_risks(
        title="Customer Migration Summary",
        content="Customer contact: alice@example.com for confidential migration.",
        tags=["migration"],
        nugget_id="nug_test",
        source_note_text="Customer contact: alice@example.com. Confidential.",
        ai_signals=[],
    )
    cats = {f.category for f in flags}
    assert RiskCategory.PERSONAL_INFORMATION in cats
    assert RiskCategory.CONFIDENTIAL_INFORMATION in cats
    assert all(f.blocking and not f.resolved for f in flags)


def test_ai_risk_signal_augments_without_duplicating_deterministic() -> None:
    flags = evaluate_risks(
        title="Team Learning",
        content="Early reviews helped engineering and product collaborate.",
        tags=["retrospective"],
        nugget_id="nug_test2",
        ai_signals=[
            LLMRiskSignal(
                category="Unsupported claims",
                explanation="Small sample size.",
                warning="Verify across additional teams.",
                recommended_action="Add context before sharing.",
            )
        ],
    )
    assert len(flags) == 1
    assert flags[0].category == RiskCategory.UNSUPPORTED_CLAIMS
    assert flags[0].source == "ai"
