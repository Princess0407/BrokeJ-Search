from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from brokej_search.core.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


def make_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    if settings.database_url.startswith("sqlite") and "///" in settings.database_url:
        db_path = settings.database_url.split("///", 1)[1]
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.database_url, future=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, class_=Session)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    with factory() as session:
        with session.begin():
            yield session
