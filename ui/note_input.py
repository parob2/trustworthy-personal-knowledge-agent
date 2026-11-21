from __future__ import annotations

import streamlit as st

from core.capture import capture_note
from core.database import Database
from core.extraction import process_note
from core.models import MAX_NOTE_LENGTH
from core.ollama_client import check_ollama_status

EXAMPLE_NOTES: list[tuple[str, str]] = [
    (
        "Example 1 · Engineering Lesson",
        "Our team discovered that running automated validation before deployment reduced recurring configuration errors.",
    ),
    (
        "Example 2 · Sensitive / Confidential",
        "Customer contact: john@example.com. The internal migration project is confidential and must not be shared externally.",
    ),
    (
        "Example 3 · Team Retrospective",
        "During the project retrospective, we learned that involving stakeholders earlier improved coordination between engineering and product teams.",
    ),
]


def _load_example(example_text: str, label: str) -> None:
    st.session_state["note_content_input"] = example_text
    st.session_state["note_source_label"] = label


def _queue_note_submission() -> None:
    st.session_state["pending_note_submission"] = st.session_state.get("note_content_input", "")
    st.session_state["pending_note_source_label"] = st.session_state.get("note_source_label", "manual")
    st.session_state["note_content_input"] = ""
    st.session_state["note_source_label"] = "manual"


def render_note_input(db: Database, use_ollama: bool = True) -> None:
    st.subheader("Capture Knowledge")
    st.caption(
        "Capture short work notes or lessons learned. Notes are treated as untrusted data, "
        "scanned for privacy and security risks, and extracted into private-by-default nuggets."
    )

    if "note_content_input" not in st.session_state:
        st.session_state["note_content_input"] = ""
    if "note_source_label" not in st.session_state:
        st.session_state["note_source_label"] = "manual"

    st.markdown("**Synthetic Examples** *(click to load into Note Content)*")
    ex_cols = st.columns(len(EXAMPLE_NOTES))
    for idx, (label, text) in enumerate(EXAMPLE_NOTES):
        with ex_cols[idx]:
            st.button(
                label,
                key=f"example_btn_{idx}",
                use_container_width=True,
                on_click=_load_example,
                args=(text, label),
            )

    note_text = st.text_area(
        "Note Content",
        key="note_content_input",
        height=160,
        max_chars=MAX_NOTE_LENGTH,
        placeholder=(
            "Enter a note, meeting takeaway, postmortem lesson, or operational observation "
            "(max 4000 characters)..."
        ),
    )

    char_count = len(note_text)
    counter_col, mode_col = st.columns([1, 2])
    with counter_col:
        if char_count > MAX_NOTE_LENGTH:
            st.markdown(f":red[**{char_count} / {MAX_NOTE_LENGTH}** characters]")
        else:
            st.caption(f"**{char_count} / {MAX_NOTE_LENGTH}** characters")
    with mode_col:
        ollama_status = check_ollama_status()
        if use_ollama and ollama_status.available and ollama_status.model_ready:
            st.caption(f"Local AI Ready: `{ollama_status.model_name}` via Ollama")
        else:
            st.caption("Local AI Fallback Active: deterministic offline extractor (no external network required)")

    st.button(
        "Process Note",
        type="primary",
        use_container_width=False,
        key="process_note_btn",
        on_click=_queue_note_submission,
    )
    if "pending_note_submission" in st.session_state:
        note_text = st.session_state.pop("pending_note_submission")
        source_label = st.session_state.pop("pending_note_source_label")
        if not note_text.strip():
            st.session_state["note_content_input"] = note_text
            st.session_state["note_source_label"] = source_label
            st.warning("Please enter a note or select an example before processing.")
            return
        if len(note_text) > MAX_NOTE_LENGTH:
            st.session_state["note_content_input"] = note_text
            st.session_state["note_source_label"] = source_label
            st.error(f"Note exceeds {MAX_NOTE_LENGTH} characters ({len(note_text)} entered).")
            return

        with st.spinner("Processing note locally: extracting nuggets and running security checks..."):
            try:
                note = capture_note(note_text, db=db, source_label=source_label)
            except Exception as exc:
                st.error(
                    "Note submission failed. The input was cleared to avoid a duplicate; "
                    f"check local storage before retrying: {exc}"
                )
                return
            try:
                nuggets = process_note(note, db=db, use_ollama=use_ollama)
            except Exception as exc:
                st.error(f"Note captured privately, but AI processing failed: {exc}")
                return

        risk_count = sum(len(n.risk_flags) for n in nuggets)
        source_used = nuggets[0].extraction_source if nuggets else "deterministic_fallback"
        st.success(
            f"Note processed (`{note.id}` via `{source_used}`): generated **{len(nuggets)}** "
            f"private-by-default nugget(s) with **{risk_count}** risk warning(s). "
            "Open **Review Nuggets** to review, edit, approve, or share."
        )
