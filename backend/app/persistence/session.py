"""SQLAlchemy session factory. The engine is created at startup, not import."""

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_engine(url: str) -> Engine:
    global engine, SessionLocal
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if url.startswith("sqlite"):
        # Wait for SQLite's file lock instead of failing when requests overlap.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        if ":memory:" in url or url.rstrip("/").endswith("sqlite+pysqlite:"):
            # An in-memory database exists per connection, so every session must share one.
            kwargs["poolclass"] = StaticPool
        # A file database gets a normal pool: one connection per concurrent request.
        # Sharing a single connection across threads interleaves transactions.
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine


def assert_schema_current(bound: Engine) -> None:
    """Refuse to serve a migrated database that is behind this code.

    Databases built with ``create_all`` (tests, throwaway dev) have no Alembic table and
    are accepted. A stale migrated database would otherwise fail later with confusing
    column errors, so it is rejected at startup with the fix spelled out.
    """

    from app.persistence import SCHEMA_REVISION

    if "alembic_version" not in inspect(bound).get_table_names():
        return
    with bound.connect() as connection:
        current = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if current != SCHEMA_REVISION:
        raise RuntimeError(
            f"Hub database schema is at revision {current}, expected {SCHEMA_REVISION}. "
            "Run `uv run alembic upgrade head` in backend/ (back up the database first)."
        )


def open_session() -> Session:
    """Return a session from the engine created by the latest init_engine call."""

    if SessionLocal is None:
        raise RuntimeError("Database engine is not initialized")
    return SessionLocal()


def get_db() -> Generator[Session, None, None]:
    db = open_session()
    try:
        yield db
    finally:
        db.close()
