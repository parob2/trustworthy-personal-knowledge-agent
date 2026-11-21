from __future__ import annotations

import streamlit as st

from core.audit import get_audit_history
from core.database import Database
from core.models import AuditEventType


def render_audit_history(db: Database) -> None:
    st.subheader("Audit History & Simulated Shared Space")
    st.caption(
        "Immutable, append-only local audit trail. Sensitive raw text is redacted from audit reasons."
    )

    event_options = ["ALL"] + [et.value for et in AuditEventType]
    selected_filter = st.selectbox(
        "Filter by Event Type",
        options=event_options,
        index=0,
        key="audit_event_filter",
    )

    filter_enum = None if selected_filter == "ALL" else AuditEventType(selected_filter)
    events = get_audit_history(db=db, event_type=filter_enum, limit=250)

    if not events:
        st.info("No audit events match the selected filter.")
    else:
        rows = [
            {
                "Timestamp (UTC)": ev.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "Event": ev.event_type.value,
                "Input ID": ev.input_id,
                "Nugget ID": ev.nugget_id or "—",
                "Decision": ev.decision,
                "Sharing Scope": ev.sharing_scope.value,
                "Reason": ev.reason,
            }
            for ev in events
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("**Locally Simulated Shared Knowledge Publications**")
    publications = db.list_shared_publications()
    if not publications:
        st.caption("No nuggets have been shared externally. All unapproved/private nuggets remain strictly local.")
    else:
        for pub in publications:
            with st.container(border=True):
                st.markdown(
                    f"**{pub.published_title}** · Scope: `{pub.scope.value}` · "
                    f"Published: `{pub.published_at.strftime('%Y-%m-%d %H:%M UTC')}`"
                )
                st.write(pub.published_content)
                st.caption(
                    f"Approval ID: `{pub.approval_id}` · Content Digest: `{pub.published_content_hash[:16]}` · "
                    f"Tags: {', '.join(pub.published_tags) or 'none'}"
                )
