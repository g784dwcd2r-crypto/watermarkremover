"""Database engine, session factory and portable column types.

Sessions are synchronous. FastAPI runs ``def`` endpoints in a threadpool, and
Celery tasks are synchronous anyway, so one session style serves both the API
and the worker without duplicating the model layer.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import JSON, Engine, String, TypeDecorator, create_engine, event
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class GUID(TypeDecorator):
    """A UUID column that is native on PostgreSQL and CHAR(36) elsewhere.

    Keeping SQLite working matters: the whole test suite runs against it, which
    is what makes the authorization-boundary tests cheap enough to run on every
    commit.
    """

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=False))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect) -> str | None:
        if value is None:
            return None
        return str(uuid.UUID(str(value)))

    def process_result_value(self, value: Any, dialect) -> str | None:
        if value is None:
            return None
        return str(value)


#: JSON that uses JSONB on PostgreSQL for indexability.
JSONType = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _create_engine(url: str) -> Engine:
    connect_args: dict = {}
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        kwargs.pop("pool_pre_ping")
    engine = create_engine(url, connect_args=connect_args, **kwargs)

    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):  # pragma: no cover - trivial
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _create_engine(get_settings().database_url)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _session_factory


def configure_engine(url: str) -> None:
    """Point the process at a different database (used by tests)."""
    global _engine, _session_factory
    _engine = _create_engine(url)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for worker tasks and scripts."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def new_id() -> str:
    return str(uuid.uuid4())
