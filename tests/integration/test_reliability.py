import base64
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from routeflow import domain
from routeflow.api import app
from routeflow.consumer import Consumer
from routeflow.db import engine, session
from routeflow.generator import generate, seed
from routeflow.models import Customer, DeadLetter, Order, Outbox, Restaurant, now
from routeflow.operations import dlq_replay
from routeflow.relay import relay_once
from routeflow.storage import Warehouse, delivery_attempts, raw_events

pytestmark = pytest.mark.integration


def test_business_transaction_and_rollback(isolated: None) -> None:
    seed()
    with session() as db:
        customer = db.scalar(select(Customer))
        restaurant = db.scalar(select(Restaurant))
        assert customer and restaurant
        count = db.scalar(select(func.count()).select_from(Outbox))
    with pytest.raises(RuntimeError), session() as db, db.begin():
        domain.create_order(
            db,
            customer.id,
            restaurant.id,
            [{"name": "Meal", "quantity": 1, "unit_price_cents": 100}],
            "rollback",
        )
        raise RuntimeError("Crash before transaction commit")
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Order)) == 0
        assert db.scalar(select(func.count()).select_from(Outbox)) == count


def test_api_lifecycle_validation_idempotency(isolated: None) -> None:
    seed()
    with session() as db:
        customer = db.scalar(select(Customer))
        restaurant = db.scalar(select(Restaurant))
        assert customer and restaurant
    with TestClient(app) as client:
        body = {
            "customer_id": customer.id,
            "restaurant_id": restaurant.id,
            "items": [{"name": "Meal", "quantity": 2, "unit_price_cents": 100}],
            "request_key": "api-key",
        }
        created = client.post("/orders", json=body)
        assert created.status_code == 201
        identifier = created.json()["id"]
        assert client.post("/orders", json=body).json()["id"] == identifier
        assert (
            client.post(
                f"/orders/{identifier}/transitions", json={"status": "DELIVERED"}
            ).status_code
            == 409
        )
        assert (
            client.post(f"/orders/{identifier}/payments", json={"success": True}).status_code == 200
        )
        assert client.post(f"/orders/{identifier}/cancel").status_code == 200
        assert client.post(f"/orders/{identifier}/refund").status_code == 200
        assert client.post(f"/orders/{identifier}/refund").status_code == 409
        body["items"][0]["quantity"] = -1  # type: ignore[index]
        assert client.post("/orders", json=body).status_code == 422


def test_duplicate_and_crash_after_write(isolated: None, event: dict[str, Any]) -> None:
    data = json.dumps(event).encode()
    assert not Consumer().process(data, crash_after_write=True)
    assert Consumer().process(data)
    with engine(True).connect() as conn:
        assert conn.scalar(select(func.count()).select_from(raw_events)) == 1
        assert conn.scalar(select(func.count()).select_from(delivery_attempts)) == 2
    event["payload"]["latitude"] += 1
    assert Consumer().process(json.dumps(event).encode())
    with session() as db:
        assert db.scalar(select(func.count()).select_from(DeadLetter)) == 1


def test_poison_and_dlq_replay(isolated: None) -> None:
    data = b"bad json\xff"
    assert Consumer().process(data)
    with session() as db:
        letter = db.scalar(select(DeadLetter))
        assert letter and base64.b64decode(letter.original_b64) == data
        assert letter.category == "INVALID_CONTRACT"
    assert dlq_replay() == 0
    with session() as db:
        letter = db.scalar(select(DeadLetter))
        assert letter and letter.resolved_at is None and letter.replay_count == 1


def test_retry_exhaustion_and_recovery(isolated: None, event: dict[str, Any]) -> None:
    class FailingWarehouse(Warehouse):
        def write(self, event: dict[str, Any]) -> bool:
            raise OSError("Transient database outage")

    consumer = Consumer(warehouse=FailingWarehouse())
    data = json.dumps(event).encode()
    for _ in range(4):
        assert not consumer.process(data)
    assert consumer.process(data)
    with session() as db:
        letter = db.scalar(select(DeadLetter))
        assert letter and letter.attempts == 5 and letter.category == "RETRY_EXHAUSTED"
    assert dlq_replay() == 1
    with engine(True).connect() as conn:
        assert conn.scalar(select(func.count()).select_from(raw_events)) == 1


def test_relay_crash_retry_and_multiple_workers(isolated: None) -> None:
    generate(2)

    class RecordingPublisher:
        def __init__(self) -> None:
            self.sent: list[str] = []

        def publish(self, data: bytes) -> str:
            self.sent.append(json.loads(data)["event_id"])
            return "confirmed"

    publisher = RecordingPublisher()
    with pytest.raises(RuntimeError):
        relay_once(publisher, limit=1, crash_after_publish=True)
    with session() as db, db.begin():
        db.execute(update(Outbox).values(lease_until=now() - timedelta(seconds=1)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(relay_once, publisher, 100) for _ in range(2)]
        for future in futures:
            future.result()
    with session() as db:
        count = db.scalar(select(func.count()).select_from(Outbox))
        assert not db.scalar(
            select(func.count()).select_from(Outbox).where(Outbox.published_at.is_(None))
        )
    assert len(publisher.sent) == count + 1
    assert len(set(publisher.sent)) == count


def test_outbox_backoff(isolated: None) -> None:
    generate(1)

    class FailingPublisher:
        def publish(self, data: bytes) -> str:
            raise ConnectionError("Broker unavailable")

    assert relay_once(FailingPublisher(), 1) == 0
    with session() as db:
        row = db.scalar(select(Outbox).where(Outbox.attempts == 1))
        assert row and row.error and row.next_attempt_at > now()
