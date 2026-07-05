"""Motor SQLAlchemy e sessão. SQLite em dev, Postgres em prod (troca de URL)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import app.config as config

_connect_args = {"check_same_thread": False} if config.DB_URL.startswith("sqlite") else {}
engine = create_engine(config.DB_URL, echo=False, future=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Cria as tabelas (idempotente). Em prod usa-se migrações; aqui basta isto."""
    import app.models  # noqa: F401  (regista os modelos)
    Base.metadata.create_all(engine)


@contextmanager
def get_session() -> Iterator[Session]:
    """Sessão transacional: commit no sucesso, rollback na exceção."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
