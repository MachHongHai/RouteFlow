import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def event() -> dict[str, Any]:
    from routeflow.models import now, uid

    identifier = uid()
    return {
        "event_id": uid(),
        "event_type": "DRIVER_LOCATION",
        "event_version": 1,
        "aggregate_id": identifier,
        "aggregate_version": 1,
        "event_time": now().isoformat(),
        "produced_at": now().isoformat(),
        "producer": "tests",
        "correlation_id": uid(),
        "payload": {"driver_id": uid(), "latitude": 10.77, "longitude": 106.67},
    }


@pytest.fixture(scope="session")
def integration_databases() -> Iterator[None]:
    if os.environ.get("RUN_INTEGRATION") != "1":
        pytest.skip("Set RUN_INTEGRATION=1 to use isolated PostgreSQL databases and emulator")
    import psycopg
    from sqlalchemy.engine import make_url

    from routeflow.config import settings
    from routeflow.db import engine
    from routeflow.storage import Warehouse

    originals = {}
    for variable, default in [
        (
            "SOURCE_DATABASE_URL",
            "postgresql+psycopg://routeflow:routeflow@127.0.0.1:55432/routeflow",
        ),
        (
            "WAREHOUSE_DATABASE_URL",
            "postgresql+psycopg://routeflow:routeflow@127.0.0.1:55433/warehouse",
        ),
    ]:
        originals[variable] = os.environ.get(variable)
        url = make_url(os.environ.get(variable, default))
        database = str(url.database) + "_test"
        admin_url = url.set(drivername="postgresql", database="postgres")
        with psycopg.connect(
            admin_url.render_as_string(hide_password=False), autocommit=True
        ) as conn:
            from psycopg import sql

            if not conn.execute(
                "select 1 from pg_database where datname=%s", (database,)
            ).fetchone():
                conn.execute(sql.SQL("create database {}").format(sql.Identifier(database)))
        os.environ[variable] = url.set(database=database).render_as_string(hide_password=False)
    os.environ["DBT_DATABASE"] = str(make_url(os.environ["WAREHOUSE_DATABASE_URL"]).database)
    for key, attr in [
        ("DBT_HOST", "host"),
        ("DBT_PORT", "port"),
        ("DBT_USER", "username"),
        ("DBT_PASSWORD", "password"),
    ]:
        os.environ[key] = str(getattr(make_url(os.environ["WAREHOUSE_DATABASE_URL"]), attr))
    for current_engine in (engine(), engine(True)):
        current_engine.dispose()
    settings.cache_clear()
    engine.cache_clear()
    # Fresh schema only in explicitly named test databases; exercise actual Alembic revisions.
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    assert str(engine().url.database).endswith("_test")
    with engine().begin() as conn:
        conn.execute(text("drop schema public cascade"))
        conn.execute(text("create schema public"))
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    Warehouse().init()
    yield
    for variable, value in originals.items():
        if value is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = value
    engine().dispose()
    engine(True).dispose()
    engine.cache_clear()
    settings.cache_clear()


@pytest.fixture
def isolated(integration_databases: None, tmp_path: Path, monkeypatch: Any) -> Iterator[None]:
    from sqlalchemy import text

    from routeflow.config import settings
    from routeflow.db import engine
    from routeflow.models import Base
    from routeflow.storage import metadata

    assert str(engine().url.database).endswith("_test")
    assert str(engine(True).url.database).endswith("_test")
    with engine().begin() as conn:
        conn.execute(text("truncate " + ",".join(Base.metadata.tables) + " cascade"))
    with engine(True).begin() as conn:
        conn.execute(text("truncate " + ",".join(metadata.tables)))
        for schema in ("analytics", "intermediate", "staging"):
            conn.execute(text(f"drop schema if exists {schema} cascade"))
    monkeypatch.setenv("ARCHIVE_PATH", str(tmp_path / "archive"))
    settings.cache_clear()
    yield
    settings.cache_clear()
