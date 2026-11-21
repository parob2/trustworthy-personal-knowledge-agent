from __future__ import annotations

from pathlib import Path
from streamlit.testing.v1 import AppTest

from core.database import Database

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def test_streamlit_end_to_end_ui_workflow(tmp_path: Path, monkeypatch) -> None:
    """Verify note capture, clearing after submission, review queue, dashboard, and audit views."""
    test_db_path = tmp_path / "ui_test.db"
    monkeypatch.setattr("core.database.DEFAULT_DB_PATH", test_db_path)

    at = AppTest.from_file(str(APP_PATH), default_timeout=20)
    at.run()
    assert not at.exception

    # 1. Navigate to Capture Knowledge via sidebar radio
    at.sidebar.radio[0].set_value("Capture Knowledge").run()
    assert not at.exception

    # 2. Load Example 1 and process it
    at.button(key="example_btn_0").click().run()
    assert not at.exception
    assert "automated validation before deployment" in at.text_area(key="note_content_input").value

    at.button(key="process_note_btn").click().run()
    assert not at.exception

    # Input MUST be automatically cleared after successful submission
    assert at.text_area(key="note_content_input").value == ""

    # 3. Verify database state
    db = Database(test_db_path)
    metrics = db.get_dashboard_metrics()
    assert metrics["total_notes"] == 1
    assert metrics["total_nuggets"] >= 1
    assert metrics["awaiting_review"] >= 1
    assert metrics["approved_shared"] == 0

    # A subsequent click with the cleared input must not create another note.
    at.button(key="process_note_btn").click().run()
    assert not at.exception
    assert db.get_dashboard_metrics()["total_notes"] == 1

    nugget = db.list_nuggets()[0]

    # 4. Navigate to Review Nuggets and approve as PRIVATE
    at.sidebar.radio[0].set_value("Review Nuggets").run()
    assert not at.exception

    at.button(key=f"approve_btn_{nugget.id}").click().run()
    assert not at.exception

    metrics_after = db.get_dashboard_metrics()
    assert metrics_after["approved_private"] == 1
    assert metrics_after["approved_shared"] == 0

    # 5. Navigate to Dashboard and Audit History to verify zero runtime exceptions
    at.sidebar.radio[0].set_value("Dashboard").run()
    assert not at.exception

    at.sidebar.radio[0].set_value("Audit History").run()
    assert not at.exception
