from __future__ import annotations

import streamlit as st

from core.database import Database
from core.models import NuggetStatus
from ui.styles import scope_badge_html, status_badge_html


def _metric_card(label: str, value: int, help_text: str) -> None:
    st.markdown(
        f"""
        <div class="pka-metric-card" title="{help_text}">
            <div class="pka-metric-label">{label}</div>
            <div class="pka-metric-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard(db: Database) -> None:
    st.subheader("Knowledge Overview")
    st.caption(
        "Summary of captured notes, generated nuggets, human review status, and authorized sharing."
    )

    metrics = db.get_dashboard_metrics()

    row1 = st.columns(3)
    with row1[0]:
        _metric_card("Captured Notes", metrics["total_notes"], "Total raw notes captured locally")
    with row1[1]:
        _metric_card("Nuggets Generated", metrics["total_nuggets"], "Total extracted knowledge nuggets")
    with row1[2]:
        _metric_card("Awaiting Review", metrics["awaiting_review"], "Unreviewed or flagged private nuggets")

    st.write("")
    row2 = st.columns(3)
    with row2[0]:
        _metric_card("Approved · Private", metrics["approved_private"], "Approved nuggets kept strictly private")
    with row2[1]:
        _metric_card("Approved · Shared", metrics["approved_shared"], "Backend-authorized shared nuggets")
    with row2[2]:
        _metric_card("Rejected", metrics["rejected"], "Rejected suggestions retained privately")

    st.markdown("---")
    col_recent, col_shared = st.columns([1.3, 1.0])

    with col_recent:
        st.markdown("**Recent Knowledge Activity**")
        nuggets = db.list_nuggets()[:8]
        if not nuggets:
            st.info("No nuggets yet. Capture a note to generate your first knowledge nugget.")
        else:
            for nugget in nuggets:
                with st.container(border=True):
                    st.markdown(
                        f"{status_badge_html(nugget.status)} "
                        f"{scope_badge_html(nugget.approved_scope, prefix='Scope')}",
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"**{nugget.current_title}**")
                    st.caption(
                        f"Updated {nugget.updated_at.strftime('%Y-%m-%d %H:%M UTC')} · "
                        f"Risks: {len(nugget.unresolved_blocking_risks)} unresolved · "
                        f"Source: `{nugget.note_id}`"
                    )

    with col_shared:
        st.markdown("**Recent Audit & Sharing Decisions**")
        events = db.list_audit_events(limit=8)
        if not events:
            st.info("No audit events recorded yet.")
        else:
            for ev in events:
                with st.container(border=True):
                    st.markdown(
                        f"**{ev.event_type.value}** · `{ev.sharing_scope.value}`"
                    )
                    st.caption(
                        f"{ev.timestamp.strftime('%Y-%m-%d %H:%M UTC')} · {ev.decision}"
                    )
                    st.caption(ev.reason)

        publications = db.list_shared_publications()[:4]
        if publications:
            st.markdown("**Simulated Shared Knowledge Space**")
            for pub in publications:
                st.success(
                    f"**{pub.published_title}** shared to `{pub.scope.value}` "
                    f"({pub.published_at.strftime('%Y-%m-%d %H:%M UTC')})"
                )
