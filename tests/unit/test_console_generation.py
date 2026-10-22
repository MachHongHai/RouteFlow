from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from routeflow import console, domain, generator
from routeflow import console_generation as generation
from routeflow.generation_context import generation_id


@pytest.mark.parametrize(
    "options",
    [
        {"orders": 0},
        {"orders": 501},
        {"orders": True},
        {"orders": "2"},
        {"seed": -1},
        {"seed": 10_000_000},
        {"transform": "false"},
        {"command": "whoami"},
        {"business_date": (datetime.now(UTC).date() + timedelta(days=1)).isoformat()},
        {"business_date": (datetime.now(UTC).date() - timedelta(days=367)).isoformat()},
    ],
)
def test_generation_input_is_bounded(options: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        generation.Generation(**options)


def test_persisted_requests_are_idempotent_and_interrupted_runs_are_honest(tmp_path: Path) -> None:
    manager = generation.Generations(tmp_path)
    body = generation.Generation(orders=2)
    record, created = manager.create(body)
    assert created
    record["phases"]["generate"] = "tampered"
    assert manager.get(record["id"])["phases"]["generate"] == "running"
    assert not manager.create(body)[1]
    with pytest.raises(ValueError):
        manager.create(body.model_copy(update={"orders": 3}))
    with pytest.raises(ValueError):
        manager.create(generation.Generation())
    restarted = generation.Generations(tmp_path)
    result, created = restarted.create(body)
    assert not created and result["status"] == "interrupted"
    assert result["phases"]["generate"] == "unknown"
    assert "giữ nguyên" in result["error"]


def test_unknown_source_does_not_fabricate_zero_facts() -> None:
    def read(database: str, sql: str, parameters: Any) -> list[dict[str, Any]]:
        if database == "source":
            raise OSError("offline")
        if "as gps" in sql:
            return [{"events": 8, "gps": 2}]
        assert "analytics.fact_order" not in sql
        return []

    result = generation.counts(read, str(uuid4()))
    assert result["source"] is None
    assert result["warehouse"] == {"events": 8, "gps": 2, "facts": None}


def test_trace_queries_bind_identifiers_and_use_exact_order_ids() -> None:
    identifier = str(uuid4())
    event_id, order_id = str(uuid4()), str(uuid4())

    def read(database: str, sql: str, parameters: Any) -> list[dict[str, Any]]:
        assert identifier not in sql
        if "array_agg" in sql:
            assert parameters == (identifier,)
            return [
                {
                    "events": 3,
                    "published": 3,
                    "orders": 1,
                    "gps": 2,
                    "retrying": 0,
                    "order_ids": [order_id],
                }
            ]
        if "dead_letters" in sql:
            return [{"count": 0}]
        if "limit 20" in sql:
            return [{"event_id": event_id}]
        if "analytics.fact_order" in sql:
            assert parameters == ([order_id],)
            return [{"count": 1}]
        if "as gps" in sql:
            assert parameters == (identifier,)
            return [{"events": 3, "gps": 2}]
        assert parameters == ([event_id],)
        return [{"event_id": event_id}]

    result = generation.counts(read, identifier)
    assert result["warehouse"]["facts"] == 1
    assert result["events"][0]["received"] is True


@pytest.mark.parametrize("transform", [True, False])
def test_worker_correlates_batch_and_verifies_completion(
    tmp_path: Path, monkeypatch: Any, transform: bool
) -> None:
    manager = generation.Generations(tmp_path)
    record, _ = manager.create(generation.Generation(orders=2, transform=transform))
    generated = False
    transformed: list[bool] = []

    def generate(*_: Any) -> dict[str, int]:
        nonlocal generated
        assert generation_id.get() == record["id"]
        generated = True
        return {"DELIVERED": 2}

    def counts(*_: Any) -> dict[str, Any]:
        return {
            "source": {"events": 24 if generated else 0, "orders": 2, "published": 24},
            "warehouse": {"events": 24, "facts": 2 if transformed else 0},
            "dlq": 0,
        }

    monkeypatch.setattr(generator, "generate", generate)
    monkeypatch.setattr(generation, "counts", counts)
    manager.run(record["id"], lambda *_: [], lambda: transformed.append(True), str)
    result = manager.get(record["id"])
    assert result["status"] == "success"
    assert result["phases"]["dbt"] == ("success" if transform else "skipped")
    assert bool(transformed) == transform
    assert generation_id.get() is None


@pytest.mark.parametrize("failure", ["dlq", "timeout", "facts", "partial"])
def test_worker_does_not_claim_success_on_incomplete_data(
    tmp_path: Path, monkeypatch: Any, failure: str
) -> None:
    manager = generation.Generations(tmp_path)
    record, _ = manager.create(generation.Generation(orders=2))
    generated = False

    def generate(*_: Any) -> dict[str, int]:
        nonlocal generated
        generated = True
        if failure == "partial":
            raise RuntimeError("Partial generation")
        return {"DELIVERED": 2}

    def counts(*_: Any) -> dict[str, Any]:
        return {
            "source": {"events": 24 if generated else 0, "orders": 2, "published": 24},
            "warehouse": {"events": 12 if failure == "timeout" else 24, "facts": 1},
            "dlq": 1 if generated and failure == "dlq" else 0,
        }

    monkeypatch.setattr(generator, "generate", generate)
    monkeypatch.setattr(generation, "counts", counts)
    manager.run(record["id"], lambda *_: [], lambda: None, str, timeout=0)
    assert generated
    assert manager.get(record["id"])["status"] == "failed"
    assert generation_id.get() is None


def test_emit_correlation_context_does_not_change_regular_requests(monkeypatch: Any) -> None:
    monkeypatch.setattr(domain, "validate", lambda _: None)

    class Session:
        def add(self, value: Any) -> None:
            pass

    db: Any = Session()
    aggregate, trace = str(uuid4()), str(uuid4())
    assert domain.emit(db, "TEST", aggregate, 1, {})["correlation_id"] == aggregate
    token = generation_id.set(trace)
    try:
        assert domain.emit(db, "TEST", aggregate, 1, {})["correlation_id"] == trace
        explicit = domain.emit(db, "TEST", aggregate, 1, {}, correlation_id=aggregate)
        assert explicit["correlation_id"] == aggregate
    finally:
        generation_id.reset(token)


def test_generation_api_preflight_csrf_idempotency_and_exclusive_actions(
    tmp_path: Path, monkeypatch: Any
) -> None:
    manager = generation.Generations(tmp_path)
    monkeypatch.setattr(console, "generation_runs", manager)
    monkeypatch.setattr(console, "jobs", {})
    submitted: list[Any] = []

    class Queue:
        def submit(self, *args: Any) -> None:
            submitted.append(args)

    monkeypatch.setattr(console, "pool", Queue())
    current = {
        "docker": {"available": True},
        "storage": {"pinned_to_e": True},
        "services": [{"id": key, "state": "running", "status": "Up"} for key in console.SERVICES],
    }
    monkeypatch.setattr(console, "overview", lambda: current)
    client = TestClient(console.app, base_url="http://localhost:58090", client=("127.0.0.1", 40000))
    headers = {"X-Console-Token": console.TOKEN}
    body = {"request_id": str(uuid4()), "orders": 2}
    assert client.post("/api/generation", json=body).status_code == 403
    current["storage"]["pinned_to_e"] = False
    assert client.post("/api/generation", json=body, headers=headers).status_code == 409
    current["storage"]["pinned_to_e"] = True
    current["services"][0]["state"] = "exited"
    assert client.post("/api/generation", json=body, headers=headers).status_code == 409
    current["services"][0]["state"] = "running"
    assert client.post("/api/generation", json=body, headers=headers).status_code == 202
    assert client.post("/api/generation", json=body, headers=headers).status_code == 202
    assert len(submitted) == 1
    assert (
        client.post("/api/generation", json={**body, "orders": 3}, headers=headers).status_code
        == 409
    )
    assert client.post("/api/generation", json={"orders": 1}, headers=headers).status_code == 409
    monkeypatch.setattr(console, "action_command", lambda *_: ["fixed"])
    assert (
        client.post("/api/actions/api", json={"action": "stop"}, headers=headers).status_code == 409
    )
    assert client.get("/api/generation/missing").status_code == 404
