from collections.abc import Callable
from pathlib import Path

from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from lifeos.domain import Base


def create_engine(database_url: str | Path) -> Engine:
    url = str(database_url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return sqlalchemy_create_engine(url, connect_args=connect_args, future=True)


def create_session_factory(engine: Engine) -> Callable[[], Session]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory


def initialize_database(engine: Engine) -> None:
    if engine.url.get_backend_name() == "sqlite":
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    Base.metadata.create_all(engine)
