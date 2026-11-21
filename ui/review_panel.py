from __future__ import annotations

import streamlit as st

from core.database import Database
from core.models import NuggetStatus
from ui.nugget_card import render_nugget_card


def render_review_panel(db: Database) -> None:
    st.subheader("Knowledge Review & Approval Queue")
    st.caption(
        "Every generated nugget starts as PRIVATE. Review risk warnings, edit if needed, "
        "and explicitly approve, share, or reject each suggestion."
    )

    if "last_action_notice" in st.session_state and st.session_state["last_action_notice"]:
        st.success(st.session_state.pop("last_action_notice"))

    all_nuggets = db.list_nuggets()
    if not all_nuggets:
        st.info("No knowledge nuggets generated yet. Capture a note in the Capture Knowledge tab to begin.")
        return

    awaiting = [
        n
        for n in all_nuggets
        if n.status in (NuggetStatus.PENDING_REVIEW, NuggetStatus.NEEDS_HUMAN_REVIEW)
    ]
    approved_private = [n for n in all_nuggets if n.status == NuggetStatus.APPROVED_PRIVATE]
    approved_shared = [n for n in all_nuggets if n.status == NuggetStatus.APPROVED_SHARED]
    rejected = [n for n in all_nuggets if n.status == NuggetStatus.REJECTED]

    counts = {
        "awaiting": len(awaiting),
        "private": len(approved_private),
        "shared": len(approved_shared),
        "rejected": len(rejected),
        "all": len(all_nuggets),
    }
    labels = {
        "awaiting": f"Awaiting Review ({counts['awaiting']})",
        "private": f"Approved Private ({counts['private']})",
        "shared": f"Approved Shared ({counts['shared']})",
        "rejected": f"Rejected ({counts['rejected']})",
        "all": f"All ({counts['all']})",
    }

    selected_bucket = st.radio(
        "Filter Review Queue",
        options=["awaiting", "private", "shared", "rejected", "all"],
        format_func=lambda k: labels[k],
        horizontal=True,
        key="review_queue_filter",
        label_visibility="collapsed",
    )

    bucket_map = {
        "awaiting": (awaiting, "No nuggets awaiting review right now."),
        "private": (approved_private, "No approved private nuggets yet."),
        "shared": (approved_shared, "No nuggets have been authorized for sharing yet."),
        "rejected": (rejected, "No rejected suggestions."),
        "all": (all_nuggets, "No nuggets found."),
    }

    items, empty_msg = bucket_map[selected_bucket]
    if not items:
        st.info(empty_msg)
        return

    for nugget in items:
        render_nugget_card(nugget, db)
