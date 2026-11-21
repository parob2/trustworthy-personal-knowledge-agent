from __future__ import annotations

import streamlit as st

from core.consent import approve_nugget, reject_nugget
from core.database import Database
from core.models import KnowledgeNugget, NuggetStatus, SharingScope
from core.review import edit_nugget
from ui.consent_dialog import open_sharing_consent_dialog
from ui.provenance_view import render_provenance_hints, render_provenance_view
from ui.risk_warning import render_risk_warnings
from ui.styles import scope_badge_html, status_badge_html, tags_html


def render_nugget_card(nugget: KnowledgeNugget, db: Database) -> None:
    """Render an individual reviewable knowledge nugget card with editing, consent, and provenance."""
    with st.container(border=True):
        # Header & status badges
        top_left, top_right = st.columns([3, 1])
        with top_left:
            st.markdown(
                f"{status_badge_html(nugget.status)} "
                f"{scope_badge_html(nugget.approved_scope, prefix='Active Scope')} "
                f'<span class="pka-badge badge-scope">AI Suggested: {nugget.suggested_scope.value}</span>',
                unsafe_allow_html=True,
            )
            st.subheader(nugget.current_title)
        with top_right:
            st.caption(f"Nugget `{nugget.id}`")
            st.caption(f"Source Note `{nugget.note_id}`")

        render_provenance_hints(nugget)

        # Knowledge statement & tags
        st.write(nugget.current_content)
        st.markdown(tags_html(nugget.current_tags), unsafe_allow_html=True)

        # Scope recommendation explanation & original source reference
        with st.container(border=True):
            st.markdown(
                f"**AI Scope Recommendation:** `{nugget.suggested_scope.value}` "
                "*(advisory only — never auto-applied)*"
            )
            st.caption(f"**Recommendation Explanation:** {nugget.scope_explanation}")
            st.caption(f"**Original Source Reference (`{nugget.note_id}`):** \"{nugget.original_note_excerpt}\"")

        # Risk warnings
        render_risk_warnings(nugget, db)

        # Edit section
        with st.expander("Edit Knowledge Nugget (Title, Content, Tags)", expanded=False):
            if nugget.status in (NuggetStatus.APPROVED_PRIVATE, NuggetStatus.APPROVED_SHARED):
                st.info(
                    "Editing an already-approved nugget will invalidate its existing approval, "
                    "revert its scope to PRIVATE, and require a fresh review."
                )

            with st.form(key=f"edit_form_{nugget.id}"):
                new_title = st.text_input(
                    "Title",
                    value=nugget.current_title,
                    max_chars=240,
                )
                new_content = st.text_area(
                    "Knowledge Statement",
                    value=nugget.current_content,
                    height=110,
                    max_chars=4000,
                )
                new_tags_str = st.text_input(
                    "Topic Tags (comma-separated)",
                    value=", ".join(nugget.current_tags),
                )
                save_edit = st.form_submit_button("Save Edits & Re-Run Risk Check")
                if save_edit:
                    try:
                        parsed_tags = [t.strip() for t in new_tags_str.split(",") if t.strip()]
                        edit_nugget(
                            nugget_id=nugget.id,
                            title=new_title,
                            content=new_content,
                            tags=parsed_tags,
                            db=db,
                        )
                        st.session_state["last_action_notice"] = (
                            f"Saved edits to '{new_title.strip()}'. Security checks re-evaluated."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

        # Provenance timeline
        render_provenance_view(nugget, db)

        # Review & Explicit Sharing Scope Selection Controls
        st.markdown("---")
        st.markdown("**Human Review & Sharing Authorization**")

        scope_options = [
            SharingScope.PRIVATE,
            SharingScope.PROJECT_TEAM,
            SharingScope.DEPARTMENT,
            SharingScope.ORGANISATION,
        ]
        # Default ALWAYS to PRIVATE when awaiting review so AI suggestion never becomes default
        default_index = 0
        if nugget.status == NuggetStatus.APPROVED_SHARED:
            default_index = scope_options.index(nugget.approved_scope)

        has_unresolved = len(nugget.unresolved_blocking_risks) > 0

        col_scope, col_approve, col_reject = st.columns([2.2, 1.4, 1.0])
        with col_scope:
            selected_scope = st.selectbox(
                "Select Final Sharing Scope (defaults to PRIVATE)",
                options=scope_options,
                index=default_index,
                format_func=lambda s: f"{s.value} — {s.label}",
                key=f"scope_select_{nugget.id}",
            )
            if selected_scope.is_shared and has_unresolved:
                st.caption(
                    ":red[Unresolved blocking warnings prevent non-PRIVATE sharing. "
                    "Only PRIVATE approval or rejection is permitted until resolved.]"
                )

        with col_approve:
            st.write("")
            st.write("")
            approve_label = (
                "Approve (Keep Private)"
                if selected_scope == SharingScope.PRIVATE
                else f"Review & Share ({selected_scope.value})"
            )
            disable_share_btn = selected_scope.is_shared and has_unresolved
            if st.button(
                approve_label,
                type="primary",
                disabled=disable_share_btn,
                use_container_width=True,
                key=f"approve_btn_{nugget.id}",
            ):
                if selected_scope == SharingScope.PRIVATE:
                    try:
                        approve_nugget(
                            nugget_id=nugget.id,
                            selected_scope=SharingScope.PRIVATE,
                            confirmed_consequences=True,
                            db=db,
                            reason="Explicitly approved by human reviewer as PRIVATE.",
                        )
                        st.session_state["last_action_notice"] = (
                            f"Approved '{nugget.current_title}' as PRIVATE."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
                else:
                    open_sharing_consent_dialog(nugget.id, selected_scope, db)

        with col_reject:
            st.write("")
            st.write("")
            if st.button(
                "Reject",
                use_container_width=True,
                disabled=nugget.status == NuggetStatus.REJECTED,
                key=f"reject_btn_{nugget.id}",
            ):
                try:
                    reject_nugget(
                        nugget_id=nugget.id,
                        db=db,
                        reason="Rejected by human reviewer in Review Panel.",
                    )
                    st.session_state["last_action_notice"] = (
                        f"Rejected '{nugget.current_title}'. Retained privately as rejected."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))
