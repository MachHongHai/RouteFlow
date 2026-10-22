import struct
from contextlib import nullcontext
from typing import Any

import pytest
from fastapi import HTTPException

from routeflow import console
from routeflow import console_broker as broker
from scripts import container_entrypoint


@pytest.mark.parametrize("target", ["console", "init", "unrelated-dashboard", "source/stop"])
def test_broker_cannot_control_other_targets(target: str) -> None:
    with pytest.raises(ValueError):
        broker.operate(target, "start")


def test_broker_rejects_arbitrary_engine_api() -> None:
    for method, path in [("POST", "/containers/create"), ("GET", "/containers/foo/json")]:
        with pytest.raises(ValueError):
            broker.dispatch(method, path, {})
    with pytest.raises(ValueError):
        broker.operate("source", "delete")


def test_broker_checks_project_and_service_labels(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        broker, "engine", lambda *_: {"Config": {"Labels": {"com.docker.compose.project": "other"}}}
    )
    with pytest.raises(ValueError):
        broker.container("source")


def test_broker_start_orders_dependencies_and_initialization(monkeypatch: Any) -> None:
    running: set[str] = set()
    events: list[str] = []

    def record(service: str) -> dict[str, Any]:
        return {"Id": service, "State": {"Running": service in running, "ExitCode": 0}}

    def engine(method: str, path: str) -> None:
        assert method == "POST" and path.endswith("/start")
        service = path.split("/")[2]
        events.append(service)
        running.add(service)

    monkeypatch.setattr(broker, "container", record)
    monkeypatch.setattr(broker, "engine", engine)
    monkeypatch.setattr(broker, "wait_ready", lambda *_: None)
    broker.operate("stack", "start")
    assert events == [
        "source",
        "warehouse",
        "pubsub",
        "init",
        "api",
        "relay",
        "consumer",
        "spark-master",
        "spark-worker",
    ]
    assert set(broker.MANAGED) == set(console.SERVICES)


def test_logs_decode_both_docker_streams() -> None:
    content = b"\x01\0\0\0" + struct.pack(">I", 4) + b"out\n"
    content += b"\x02\0\0\0" + struct.pack(">I", 4) + b"err\n"
    assert broker.demultiplex(content) == "out\nerr\n"
    assert broker.demultiplex(b"plain tty\n") == "plain tty\n"


@pytest.mark.parametrize("exit_code", [0, 1])
def test_dbt_exec_is_fixed_and_checks_exit_code(monkeypatch: Any, exit_code: int) -> None:
    calls = []

    def engine(method: str, path: str, body: Any = None) -> dict[str, Any]:
        calls.append((method, path, body))
        return {"Id": "exec-id", "Running": False, "ExitCode": exit_code}

    monkeypatch.setattr(
        broker,
        "container",
        lambda service: {"Id": "api-id", "State": {"Running": service == "api"}},
    )
    monkeypatch.setattr(broker, "engine", engine)
    with pytest.raises(ValueError):
        broker.dispatch("POST", "/workloads/dbt", {"Cmd": ["whoami"]})
    if exit_code:
        with pytest.raises(RuntimeError):
            broker.dispatch("POST", "/workloads/dbt", {})
    else:
        assert broker.dispatch("POST", "/workloads/dbt", {}) == {"exit_code": 0}
    assert calls[0] == (
        "POST",
        "/containers/api-id/exec",
        {
            "Cmd": ["python", "-m", "routeflow.cli", "dbt"],
            "User": "10001",
            "WorkingDir": "/app",
            "AttachStdout": False,
            "AttachStderr": False,
        },
    )
    assert calls[1] == ("POST", "/exec/exec-id/start", {"Detach": True, "Tty": False})


def test_container_list_handles_no_published_ports(monkeypatch: Any) -> None:
    records = [
        {"Names": ["/routeflow-init-1"], "State": "exited", "Status": "Exited (0)", "Ports": None}
    ]
    monkeypatch.setattr(broker, "engine", lambda *_: records)
    assert broker.dispatch("GET", "/containers", {})[0]["Ports"] == ""


def test_container_controls_require_current_e_storage_setting(monkeypatch: Any) -> None:
    monkeypatch.setattr(console, "CONTAINER_MODE", True)
    monkeypatch.setattr(console, "storage_summary", lambda: {"pinned_to_e": False})
    with pytest.raises(HTTPException) as error:
        console.action_command("api", "start")
    assert error.value.status_code == 409
    monkeypatch.setattr(console, "storage_summary", lambda: {"pinned_to_e": True})
    assert console.action_command("api", "start") == ["console-broker", "api", "start"]


def test_local_wait_is_opt_in_for_cloud_images(monkeypatch: Any) -> None:
    monkeypatch.delenv("ROUTEFLOW_WAIT_MODE", raising=False)
    monkeypatch.setattr(
        container_entrypoint.psycopg, "connect", lambda *_a, **_k: pytest.fail("Unexpected DB wait")
    )
    container_entrypoint.wait()


def test_local_app_retries_database_and_waits_for_subscription(monkeypatch: Any) -> None:
    monkeypatch.setenv("ROUTEFLOW_WAIT_MODE", "app")
    monkeypatch.setenv("SOURCE_DATABASE_URL", "postgresql://routeflow@source/routeflow")
    monkeypatch.setenv("WAREHOUSE_DATABASE_URL", "postgresql://routeflow@warehouse/warehouse")
    monkeypatch.setenv("PUBSUB_EMULATOR_HOST", "pubsub:8085")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "routeflow-local")
    attempts = 0
    sleeps = []
    statements = []
    requests = []

    class Connection:
        def execute(self, sql: str, *params: Any) -> Any:
            statements.append((sql, params))
            return self

        def fetchone(self) -> tuple[str]:
            return ("ready",)

    def connect(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("Database still starting")
        return nullcontext(Connection())

    def http(url: str, **kwargs: Any) -> Any:
        requests.append(url)
        return nullcontext()

    monkeypatch.setattr(container_entrypoint.psycopg, "connect", connect)
    monkeypatch.setattr(container_entrypoint.urllib.request, "urlopen", http)
    monkeypatch.setattr(container_entrypoint.time, "sleep", sleeps.append)
    container_entrypoint.wait()
    assert sleeps == [1] and attempts == 3
    assert len(statements) == 4
    assert requests == [
        "http://pubsub:8085/v1/projects/routeflow-local/subscriptions/delivery-events-local"
    ]
