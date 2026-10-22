from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from routeflow import console
from routeflow import console_database as database


@pytest.mark.parametrize(
    "body",
    [
        {"sql": ""},
        {"sql": "x" * 20_001},
        {"sql": "select 1", "limit": 0},
        {"sql": "select 1", "limit": 501},
        {"sql": "select 1", "limit": True},
        {"sql": "select 1", "host": "remote"},
    ],
)
def test_query_request_bounds(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        database.Query(**body)


def test_reader_uses_separate_login_and_readonly_transaction(monkeypatch: Any) -> None:
    calls = []
    url = make_url("postgresql://owner:owner-secret@localhost:55432/routeflow")
    monkeypatch.setattr(database, "local_url", lambda _: url)
    monkeypatch.setattr(database, "provision", lambda *_: "reader-secret")

    def connect(dsn: str, **kwargs: Any) -> Any:
        calls.append((make_url(dsn), kwargs))
        return nullcontext("reader connection")

    monkeypatch.setattr(database.psycopg, "connect", connect)
    with database.reader("source") as connection:
        assert connection == "reader connection"
    assert calls[0][0].username == database.ROLE
    assert calls[0][0].password == "reader-secret"
    assert "default_transaction_read_only=on" in calls[0][1]["options"]
    assert "statement_timeout=5000" in calls[0][1]["options"]


def test_sql_endpoint_requires_csrf_and_known_database() -> None:
    client = TestClient(console.app, base_url="http://localhost:58090", client=("127.0.0.1", 50000))
    assert client.post("/api/database/source/query", json={"sql": "select 1"}).status_code == 403
    response = client.post(
        "/api/database/other/query",
        json={"sql": "select 1"},
        headers={"X-Console-Token": console.TOKEN},
    )
    assert response.status_code == 422


def test_query_preserves_duplicate_columns_empty_results_and_bounds(monkeypatch: Any) -> None:
    rows: list[Any] = [(1, None), (2, "x" * 3000), (3, "not returned")]
    calls = []

    class Connection:
        description = [SimpleNamespace(name="same"), SimpleNamespace(name="same")]

        def cursor(self, *, name: str) -> Any:
            assert name == "routeflow_query"
            return nullcontext(self)

        def execute(self, statement: Any, parameters: Any, **kwargs: Any) -> None:
            calls.append((statement.as_string(), parameters, kwargs))

        def fetchone(self) -> Any:
            return rows.pop(0) if rows else None

        def cancel(self) -> None:
            pass

    monkeypatch.setattr(database, "reader", lambda _: nullcontext(Connection()))
    result = database.query(
        "source", database.Query(sql="select 1 as same, null as same;", limit=2)
    )
    assert result["columns"] == ["same", "same"]
    assert result["rows"][0] == [1, None]
    assert result["truncated"] and result["clipped"]
    assert len(result["rows"][1][1]) == 2001
    assert calls[0][1] == (3,)
    rows.clear()
    result = database.query("source", database.Query(sql="select 1 where false"))
    assert result["columns"] == ["same", "same"] and result["rows"] == []


def test_query_slot_limit_and_release_on_database_error(monkeypatch: Any) -> None:
    @contextmanager
    def unavailable(_: str) -> Any:
        raise psycopg.errors.QueryCanceled("timeout")
        yield

    monkeypatch.setattr(database, "reader", unavailable)
    with pytest.raises(HTTPException) as error:
        database.query("source", database.Query(sql="select 1"))
    assert error.value.status_code == 408
    assert database.query_slots.acquire(False)
    assert database.query_slots.acquire(False)
    try:
        with pytest.raises(HTTPException) as busy:
            database.query("source", database.Query(sql="select 1"))
        assert busy.value.status_code == 429
    finally:
        database.query_slots.release()
        database.query_slots.release()


def test_reader_rejects_remote_or_cloud_connection(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        database,
        "settings",
        lambda: SimpleNamespace(
            environment="local",
            warehouse_mode="postgres",
            source_database_url="postgresql://user:secret@remote.example/db",
        ),
    )
    with pytest.raises(HTTPException) as error:
        database.local_url("source")
    assert error.value.status_code == 409
