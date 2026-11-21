from __future__ import annotations

import streamlit as st

from core.consent import approve_nugget
from core.database import Database
from core.models import KnowledgeNugget, SharingScope
from core.sharing import authorize_sharing

_SCOPE_CONSEQUENCES = {
    SharingScope.PROJECT_TEAM: (
        "Members of your immediate **Project Team** will be able to view and reuse this "
        "knowledge nugget inside the shared team knowledge space."
    ),
    SharingScope.DEPARTMENT: (
        "Everyone across your **Department** (including multiple teams and leads) will gain "
        "read access to this knowledge nugget."
    ),
    SharingScope.ORGANISATION: (
        "All members across the entire **Organisation** will be able to search, read, and "
        "reference this knowledge nugget."
    ),
}


@st.dialog("Confirm Sharing Scope & Consequences")
def open_sharing_consent_dialog(
    nugget_id: str,
    target_scope: SharingScope,
    db: Database,
) -> None:
    """Modal confirmation explaining sharing consequences before authorizing non-PRIVATE sharing."""
    nugget: KnowledgeNugget | None = db.get_nugget(nugget_id)
    if nugget is None:
        st.error("This nugget could not be found.")
        return

    st.warning(
        f"You are about to authorize sharing this knowledge nugget under **{target_scope.label}**."
    )
    st.markdown(f"**Audience & Impact:** {_SCOPE_CONSEQUENCES.get(target_scope, '')}")
    st.markdown(
        "**Privacy Reminder:** Any future edit to the title, content, or tags will automatically "
        "invalidate this approval and revert the nugget to `PRIVATE`."
    )

    with st.container(border=True):
        st.markdown(f"**Title:** {nugget.current_title}")
        st.write(nugget.current_content)
        st.caption(f"Tags: {', '.join(nugget.current_tags) or 'none'}")
        st.caption(f"Content Integrity Digest: `{nugget.current_content_hash[:16]}`")

    confirmed = st.checkbox(
        f"I confirm there is no confidential or personal data here and authorize sharing to {target_scope.value}.",
        key=f"confirm_chk_{nugget_id}_{target_scope.value}",
    )

    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button(
            "Confirm & Authorize Sharing",
            type="primary",
            disabled=not confirmed,
            use_container_width=True,
            key=f"confirm_share_btn_{nugget_id}",
        ):
            try:
                approve_nugget(
                    nugget_id=nugget.id,
                    selected_scope=target_scope,
                    confirmed_consequences=True,
                    db=db,
                    reason=f"Human confirmed consequences and approved for {target_scope.value}.",
                )
                publication = authorize_sharing(
                    nugget_id=nugget.id,
                    requested_scope=target_scope,
                    db=db,
                )
                st.session_state["last_action_notice"] = (
                    f"Sharing authorized for '{publication.published_title}' ({publication.scope.value})."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Sharing blocked by backend security check: {exc}")

    with col_cancel:
        if st.button(
            "Cancel (Keep Private)",
            use_container_width=True,
            key=f"cancel_share_btn_{nugget_id}",
        ):
            st.rerun()
