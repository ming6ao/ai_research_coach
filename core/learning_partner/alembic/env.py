from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the project package importable regardless of CWD.
# Now lives under the parent `core/learning_partner` package; ensure repo root is on path.
ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.learning_partner.storage.database import Base  # noqa: E402
from core.learning_partner.storage import models  # noqa: E402,F401  (register tables)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    return os.environ.get("LEARNING_PARTNER_DB_URL") or config.get_main_option("sqlalchemy.url", "sqlite:///data/knowledge_graph.db")


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///") and url != "sqlite:///:memory:":
        db_path = Path(url.removeprefix("sqlite:///"))
        db_path.parent.mkdir(parents=True, exist_ok=True)


def run_migrations_offline() -> None:
    url = _db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    url = _db_url()
    _ensure_sqlite_dir(url)
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()