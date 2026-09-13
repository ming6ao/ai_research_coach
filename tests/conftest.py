"""Ensure the project root is importable when running tests from anywhere."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from coach.db import Base
from coach import tasks as _tasks  # noqa: F401  (register tables)
import coach.db as db


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Never let tests touch the real data/coach.db.

    Every test gets its own throwaway SQLite file; tests that need a specific
    path (or a fresh file per case) can still override DB_PATH afterwards.
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test-coach.db")
    monkeypatch.delenv("LEARNING_PARTNER_DB_URL", raising=False)


@pytest.fixture()
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine):
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as s:
        yield s
