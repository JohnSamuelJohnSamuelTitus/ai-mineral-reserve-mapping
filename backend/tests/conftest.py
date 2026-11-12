"""Shared pytest fixtures for isolated SQLite databases and FastAPI TestClient."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.routes import get_cache
from app.core.cache import InMemoryTTLCache
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.seed import seed_default_data_sources
from app.db.session import create_db_engine, get_db
from app.main import create_app


@pytest.fixture()
def test_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_mineral.db"


@pytest.fixture()
def test_engine(test_db_path: Path) -> Generator[Engine, None, None]:
    engine = create_db_engine(f"sqlite:///{test_db_path.as_posix()}")
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False, expire_on_commit=False)
    with factory() as session:
        seed_default_data_sources(session)
        yield session


@pytest.fixture()
def client(
    test_db_path: Path, test_engine: Engine, tmp_path: Path
) -> Generator[TestClient, None, None]:
    factory = sessionmaker(bind=test_engine, autocommit=False, autoflush=False, expire_on_commit=False)
    with factory() as seed_session:
        seed_default_data_sources(seed_session)

    test_settings = Settings(
        database_url=f"sqlite:///{test_db_path.as_posix()}",
        data_dir=tmp_path / "data",
    )
    test_cache = InMemoryTTLCache()

    def _override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_cache] = lambda: test_cache

    with TestClient(app) as tc:
        yield tc

