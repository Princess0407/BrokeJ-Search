"""Optional PostgreSQL migration and transaction check."""

import os

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from brokej_search.core.config import get_settings


def test_postgres_migrations_and_transactions(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("BROKEJ_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("set BROKEJ_TEST_POSTGRES_URL to run PostgreSQL integration coverage")
    monkeypatch.setenv("BROKEJ_DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        config = Config("alembic.ini")
        command.upgrade(config, "head")
        engine = create_engine(url)
        inspector = inspect(engine)
        assert {"candidates", "jobs", "github_profiles", "recommendations"} <= set(
            inspector.get_table_names()
        )
        assert len(inspector.get_foreign_keys("candidates")) >= 2
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO candidates (id, created_at, updated_at) "
                    "VALUES ('pg-check', now(), now())"
                )
            )
        with pytest.raises(RuntimeError, match="rollback check"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO candidates (id, created_at, updated_at) "
                        "VALUES ('pg-rollback', now(), now())"
                    )
                )
                raise RuntimeError("rollback check")
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT count(*) FROM candidates WHERE id = 'pg-check'"))
                == 1
            )
            assert (
                connection.scalar(text("SELECT count(*) FROM candidates WHERE id = 'pg-rollback'"))
                == 0
            )
        engine.dispose()
        command.downgrade(config, "base")
    finally:
        get_settings.cache_clear()
