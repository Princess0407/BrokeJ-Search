import os
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from brokej_search.core.config import get_settings


def test_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    os.environ["BROKEJ_DATABASE_URL"] = f"sqlite:///{database}"
    get_settings.cache_clear()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database}")
    tables = set(inspect(engine).get_table_names())
    assert {
        "candidates",
        "profile_versions",
        "evidence_edges",
        "jobs",
        "source_checkpoints",
    } <= tables
    candidate_foreign_keys = {
        tuple(value["constrained_columns"])
        for value in inspect(engine).get_foreign_keys("candidates")
    }
    assert candidate_foreign_keys == {
        ("current_profile_version_id",),
        ("current_preference_version_id",),
    }
    engine.dispose()
    command.downgrade(config, "base")
    downgraded_engine = create_engine(f"sqlite:///{database}")
    assert inspect(downgraded_engine).get_table_names() == ["alembic_version"]
    downgraded_engine.dispose()
    os.environ.pop("BROKEJ_DATABASE_URL", None)
    get_settings.cache_clear()
