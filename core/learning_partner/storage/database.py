"""Database engine/session setup.

Portable SQLite by default; override the URL with the ``LEARNING_PARTNER_DB_URL``
environment variable. Only SQLite-specific connection args are applied, guarded
by the URL scheme so the same code works with any SQLAlchemy-supported database.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge_graph.db"


def get_database_url() -> str:
    """Default SQLite database URL (data/knowledge_graph.db)."""
    return os.environ.get("LEARNING_PARTNER_DB_URL", f"sqlite:///{DEFAULT_DB_PATH}")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def create_session_factory(url: Optional[str] = None):
    """Build a sessionmaker bound to the given URL (defaults to env/config).

    Ensures the SQLite parent directory exists before connecting.
    """
    url = url or get_database_url()
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
        if url != "sqlite:///:memory:":
            db_path = Path(url.removeprefix("sqlite:///"))
            db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, connect_args=connect_args)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return session_factory, engine


def new_session(url: Optional[str] = None) -> Session:
    """Create a single session bound to a fresh engine."""
    session_factory, _ = create_session_factory(url)
    return session_factory()