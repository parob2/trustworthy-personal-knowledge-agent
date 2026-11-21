from __future__ import annotations

import streamlit as st

from core.database import Database
from core.ollama_client import check_ollama_status
from logging_config import configure_logging
from ui.audit_history import render_audit_history
from ui.dashboard import render_dashboard
from ui.note_input import render_note_input
from ui.review_panel import render_review_panel
from ui.styles import inject_custom_styles


def get_database() -> Database:
    if "pka_db" not in st.session_state:
        st.session_state["pka_db"] = Database()
    return st.session_state["pka_db"]


def main() -> None:
    configure_logging()
    st.set_page_config(
        page_title="Trustworthy Personal Knowledge Agent",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_custom_styles()

    db = get_database()
    metrics = db.get_dashboard_metrics()
    ollama_status = check_ollama_status()

    # Sidebar navigation & local runtime status
    with st.sidebar:
        st.markdown("### Knowledge Agent")
        st.caption("Local · Privacy-First · Human-Approved")

        page = st.radio(
            "Workspace",
            options=[
                "Dashboard",
                "Capture Knowledge",
                "Review Nuggets",
                "Audit History",
            ],
            format_func=lambda opt: (
                f"Review Nuggets ({metrics['awaiting_review']})"
                if opt == "Review Nuggets"
                else opt
            ),
            key="nav_page",
            label_visibility="collapsed",
        )

        st.markdown("---")
        st.markdown("**Local AI Engine**")
        use_ollama = st.toggle(
            "Prefer Ollama (qwen3:0.6b)",
            value=True,
            help="Uses local Ollama when available; automatically falls back to deterministic extraction when offline.",
        )
        if ollama_status.available and ollama_status.model_ready:
            st.success(f"Ollama online · `{ollama_status.model_name}`")
        elif ollama_status.available:
            st.warning(f"Ollama online · pull `{ollama_status.model_name}`")
        else:
            st.info("Ollama offline · Deterministic fallback active")

        st.markdown("---")
        st.markdown("**Security Invariants**")
        st.caption(
            "• Every nugget defaults to `PRIVATE`\n"
            "• AI suggestions never authorize sharing\n"
            "• Edits invalidate prior approvals\n"
            "• Backend blocks unresolved risks"
        )

    st.markdown(
        """
        <div class="pka-header">
            <h1>Trustworthy Personal Knowledge Agent</h1>
            <p>Transform work notes into reusable knowledge nuggets while keeping full control over privacy, review, and sharing.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if page == "Dashboard":
        render_dashboard(db)
    elif page == "Capture Knowledge":
        render_note_input(db, use_ollama=use_ollama)
    elif page.startswith("Review Nuggets"):
        render_review_panel(db)
    elif page == "Audit History":
        render_audit_history(db)


if __name__ == "__main__":
    main()
