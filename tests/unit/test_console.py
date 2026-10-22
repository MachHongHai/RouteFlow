import subprocess
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from routeflow import console


@pytest.fixture
def client(monkeypatch: Any) -> TestClient:
    monkeypatch.setattr(console, "jobs", {})
    return TestClient(console.app, base_url="http://localhost:58090", client=("127.0.0.1", 40000))


def test_console_shell_and_local_security(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert console.TOKEN in response.text
    assert "__CONSOLE_TOKEN__" not in response.text
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/tables", headers={"Host": "malicious.example"}).status_code == 403
    remote = TestClient(
        console.app, base_url="http://localhost:58090", client=("192.168.1.2", 1234)
    )
    assert remote.get("/").status_code == 403


def test_mutations_require_same_origin_and_session_token(client: TestClient) -> None:
    assert client.post("/api/actions/api", json={"action": "stop"}).status_code == 403
    response = client.post(
        "/api/actions/api",
        json={"action": "stop"},
        headers={"X-Console-Token": console.TOKEN, "Origin": "https://bad.example"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("target", ["unrelated-dashboard", "init", "spark-job", "source;whoami"])
def test_only_approved_services_can_be_controlled(client: TestClient, target: str) -> None:
    response = client.post(
        f"/api/actions/{target}",
        json={"action": "start"},
        headers={"X-Console-Token": console.TOKEN},
    )
    assert response.status_code == 404


def test_no_arbitrary_action_or_sql_table(client: TestClient) -> None:
    response = client.post(
        "/api/actions/source",
        json={"action": "down -v"},
        headers={"X-Console-Token": console.TOKEN},
    )
    assert response.status_code == 422
    assert client.get("/api/tables/pg_authid").status_code == 404
    assert client.get("/api/tables/orders?page=0").status_code == 422
    assert client.get("/api/logs/init").status_code == 404


def test_database_failure_is_unknown_not_fabricated_zero(
    client: TestClient, monkeypatch: Any
) -> None:
    def unavailable(*_: Any, **__: Any) -> None:
        raise RuntimeError("postgresql://admin:SECRET@localhost/db")

    monkeypatch.setattr(console, "docker", unavailable)
    monkeypatch.setattr(console, "read_sql", unavailable)
    result = client.get("/api/overview").json()
    assert result["docker"]["available"] is False
    assert all(service["state"] == "unknown" for service in result["services"])
    assert result["data"]["source"] is None
    assert result["data"]["warehouse"] is None
    assert "SECRET" not in str(result)


def test_start_is_bounded_and_preserves_volumes(monkeypatch: Any) -> None:
    monkeypatch.setattr(console, "guarded", lambda args, **_: args)
    start = console.action_command("stack", "start")
    assert "--no-build" in start
    assert start[start.index("--pull") + 1] == "never"
    assert start[-8:] == list(console.SERVICES)
    assert console.action_command("source", "stop") == [
        "compose",
        "--profile",
        "spark",
        "stop",
        "source",
    ]
    with pytest.raises(HTTPException):
        console.action_command("another-project", "restart")


def test_concurrent_actions_are_rejected(client: TestClient, monkeypatch: Any) -> None:
    monkeypatch.setattr(console, "jobs", {"existing": {"status": "running"}})
    response = client.post(
        "/api/actions/api", json={"action": "restart"}, headers={"X-Console-Token": console.TOKEN}
    )
    assert response.status_code == 409


def test_authorized_action_can_be_tracked_to_completion(
    client: TestClient, monkeypatch: Any
) -> None:
    commands: list[list[str]] = []

    def execute(command: list[str], **_: Any) -> str:
        commands.append(command)
        return "Container routeflow-relay-1 started"

    class ImmediatePool:
        def submit(self, function: Any, *args: Any) -> None:
            function(*args)

    monkeypatch.setattr(console, "guarded", lambda args, **_: args)
    monkeypatch.setattr(console, "execute", execute)
    monkeypatch.setattr(console, "pool", ImmediatePool())
    response = client.post(
        "/api/actions/relay",
        json={"action": "restart"},
        headers={"X-Console-Token": console.TOKEN, "Origin": "http://localhost:58090"},
    )
    assert response.status_code == 202
    job = client.get(f"/api/jobs/{response.json()['id']}").json()
    assert job["status"] == "success" and job["target"] == "relay"
    assert commands == [["compose", "--profile", "spark", "restart", "relay"]]
    assert client.get("/api/jobs/missing").status_code == 404


def test_failed_action_output_is_redacted(monkeypatch: Any) -> None:
    def fail(*_: Any, **__: Any) -> None:
        raise RuntimeError("postgresql://admin:HIDDEN@localhost/db Authorization: Bearer SECRET")

    monkeypatch.setattr(console, "execute", fail)
    monkeypatch.setattr(console, "jobs", {"test": {"status": "running"}})
    console.perform("test", ["unused"])
    result = console.jobs["test"]
    assert result["status"] == "failed"
    assert "HIDDEN" not in result["output"] and "SECRET" not in result["output"]


def test_process_execution_works_without_windows_only_constants(monkeypatch: Any) -> None:
    calls = []

    def run(arguments: list[str], **kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(console, "CONTAINER_MODE", False)
    monkeypatch.delattr(subprocess, "CREATE_NO_WINDOW", raising=False)
    monkeypatch.setattr(subprocess, "run", run)
    assert console.execute(["fixed-command"]) == "ok"
    assert calls[0]["creationflags"] == 0


def test_timeout_does_not_claim_the_service_stopped(monkeypatch: Any) -> None:
    def timeout(*_: Any, **__: Any) -> None:
        raise subprocess.TimeoutExpired("docker", 180)

    monkeypatch.setattr(console, "execute", timeout)
    monkeypatch.setattr(console, "jobs", {"test": {"status": "running"}})
    console.perform("test", ["unused"])
    assert console.jobs["test"]["status"] == "failed"
    assert "kiểm tra trạng thái" in console.jobs["test"]["output"]


def test_table_pagination_is_parameterized(client: TestClient, monkeypatch: Any) -> None:
    calls = []

    def read(database: str, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        calls.append((database, sql, parameters))
        return [{"count": 34}] if "count(*)" in sql else [{"id": "sample"}]

    monkeypatch.setattr(console, "read_sql", read)
    result = client.get("/api/tables/orders?page=2").json()
    assert result["total"] == 34 and result["page"] == 2
    assert calls[1][2] == (20,)
    assert "offset %s" in calls[1][1]
