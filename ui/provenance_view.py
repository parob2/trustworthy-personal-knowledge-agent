from __future__ import annotations

import html
import streamlit as st

from core.database import Database
from core.models import KnowledgeNugget, NuggetStatus


def render_provenance_hints(nugget: KnowledgeNugget) -> None:
    """Render compact 4-stage provenance hint badges directly inside a nugget card."""
    s1 = '<span class="prov-step-done">1. Original Input</span>'
    s2 = '<span class="prov-step-done">2. AI Suggestion</span>'
    s3 = (
        '<span class="prov-step-done">3. Human Edited</span>'
        if nugget.has_human_edits
        else '<span class="prov-step-idle">3. Not Edited</span>'
    )
    if nugget.approved_content_hash is not None and nugget.approved_content_hash == nugget.current_content_hash:
        s4 = f'<span class="prov-step-done">4. Human Approved ({html.escape(nugget.approved_scope.value)})</span>'
    elif nugget.status == NuggetStatus.REJECTED:
        s4 = '<span class="prov-step-idle">4. Rejected</span>'
    else:
        s4 = '<span class="prov-step-idle">4. Awaiting Approval</span>'

    st.markdown(
        f'<div class="pka-provenance-strip">{s1}{s2}{s3}{s4}</div>',
        unsafe_allow_html=True,
    )


def render_provenance_view(nugget: KnowledgeNugget, db: Database) -> None:
    """Render full 4-stage transparent content provenance."""
    source_note = db.get_note(nugget.note_id)
    approvals = db.list_approvals(nugget.id)

    with st.expander("Content Provenance & Lineage (4 Stages)", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**1. Original Input (Preserved Source Note)**")
            st.caption(f"Source Note ID: `{nugget.note_id}`")
            if source_note is not None:
                st.info(source_note.content)
            else:
                st.info(nugget.original_note_excerpt)

            st.markdown("**3. Human-Edited Version**")
            if nugget.has_human_edits:
                st.write(f"**Title:** {nugget.edited_title}")
                st.write(f"**Content:** {nugget.edited_content}")
                st.caption(f"Tags: {', '.join(nugget.edited_tags or [])}")
            else:
                st.caption("No human edits made yet; currently matching AI suggestion.")

        with col2:
            st.markdown("**2. AI-Generated Suggestion (Immutable)**")
            st.caption(f"Extractor: `{nugget.extraction_source}`")
            st.write(f"**Title:** {nugget.ai_title}")
            st.write(f"**Content:** {nugget.ai_content}")
            st.caption(
                f"Tags: {', '.join(nugget.ai_tags)} · Suggested Scope: {nugget.suggested_scope.value}"
            )

            st.markdown("**4. Human-Approved Version**")
            if nugget.approved_content_hash is not None:
                matches = nugget.approved_content_hash == nugget.current_content_hash
                st.write(f"**Title:** {nugget.approved_title}")
                st.write(f"**Content:** {nugget.approved_content}")
                st.caption(
                    f"Scope: `{nugget.approved_scope.value}` · Digest: `{nugget.approved_content_hash[:12]}` · "
                    f"Integrity: {'Valid' if matches else 'Invalidated by later edit'}"
                )
            else:
                st.caption("Not currently approved (or prior approval was invalidated after editing).")

        if approvals:
            st.markdown("**Decision History for This Nugget**")
            for appr in approvals[:5]:
                inv = f" (Invalidated: {appr.invalidated_at.strftime('%Y-%m-%d %H:%M UTC')})" if appr.invalidated_at else ""
                st.caption(
                    f"• `{appr.created_at.strftime('%Y-%m-%d %H:%M UTC')}` — "
                    f"**{appr.decision}** · Scope: `{appr.selected_scope.value}` · "
                    f"Hash: `{appr.approved_content_hash[:10]}`{inv}"
                )
