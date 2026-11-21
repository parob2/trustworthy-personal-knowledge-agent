from __future__ import annotations

from pathlib import Path
import pytest

from core.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Provide an isolated temporary SQLite database for each test."""
    return Database(db_path=tmp_path / "test_knowledge_agent.db")
