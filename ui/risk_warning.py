from __future__ import annotations

import streamlit as st

from core.database import Database
from core.models import KnowledgeNugget, RiskCategory, RiskSeverity
from core.review import resolve_risk_flag


def render_risk_warnings(nugget: KnowledgeNugget, db: Database) -> None:
    """Render all detected risk warnings with category, explanation, warning, and safe action."""
    if not nugget.risk_flags:
        st.success("No security, privacy, or unsupported-claim warnings detected on current content.")
        return

    unresolved_count = len(nugget.unresolved_blocking_risks)
    if unresolved_count > 0:
        st.error(
            f"{unresolved_count} unresolved blocking warning(s): external sharing is blocked "
            "and this nugget will remain PRIVATE until resolved."
        )

    for flag in nugget.risk_flags:
        source_label = "Deterministic Security Rule" if flag.source == "deterministic" else "Local AI Signal"
        state_label = "Resolved" if flag.resolved else ("Blocking" if flag.blocking else "Advisory")
        header = f"[{flag.severity.value}] {flag.category.value} · {source_label} · {state_label}"

        with st.container(border=True):
            if flag.resolved:
                st.caption(f"✅ {header}")
            elif flag.severity == RiskSeverity.HIGH:
                st.markdown(f"**:red[{header}]**")
            else:
                st.markdown(f"**:orange[{header}]**")

            st.markdown(f"**Explanation:** {flag.explanation}")
            st.markdown(f"**Warning:** {flag.warning}")
            st.markdown(f"**Recommended Safe Action:** {flag.recommended_action}")

            if flag.resolved and flag.resolution_note:
                st.info(f"Verification note: {flag.resolution_note}")
            elif flag.blocking and not flag.resolved:
                is_strict_deterministic = flag.source == "deterministic" and flag.category in (
                    RiskCategory.PERSONAL_INFORMATION,
                    RiskCategory.CREDENTIALS_AND_SECRETS,
                    RiskCategory.CONFIDENTIAL_INFORMATION,
                )
                if is_strict_deterministic:
                    st.caption(
                        "This deterministic security check cannot be manually overridden. "
                        "Edit the nugget content above to remove or redact the sensitive information."
                    )
                else:
                    with st.expander("Verify & resolve this warning"):
                        note_key = f"resolve_note_{nugget.id}_{flag.id}"
                        verif_note = st.text_input(
                            "Verification note (explain supporting evidence or manual review):",
                            key=note_key,
                            placeholder="e.g., Confirmed with deployment metrics from Q3 release report.",
                        )
                        if st.button(
                            "Mark Warning Verified",
                            key=f"resolve_btn_{nugget.id}_{flag.id}",
                        ):
                            try:
                                resolve_risk_flag(nugget.id, flag.id, verif_note, db)
                                st.success("Warning verified and resolved.")
                                st.rerun()
                            except Exception as exc:
                                st.error(str(exc))
