from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from brokej_search.core.config import Settings, get_settings
from brokej_search.runtime import Runtime, create_runtime

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def runtime(tmp_path: Path) -> Iterator[Runtime]:
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    previous = os.environ.get("BROKEJ_DATABASE_URL")
    os.environ["BROKEJ_DATABASE_URL"] = database_url
    get_settings.cache_clear()
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(config, "head")
    settings = Settings(database_url=database_url, source_storage=tmp_path / "sources")
    value = create_runtime(settings)
    yield value
    value.engine.dispose()
    if previous is None:
        os.environ.pop("BROKEJ_DATABASE_URL", None)
    else:
        os.environ["BROKEJ_DATABASE_URL"] = previous
    get_settings.cache_clear()


@pytest.fixture
def resume_path() -> Path:
    return ROOT / "Resume-5.pdf"


@pytest.fixture
def fixture_dir() -> Path:
    return ROOT / "tests" / "fixtures"
