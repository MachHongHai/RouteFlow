"""Controlled local fault probes. Every scenario asserts real persisted outcomes."""

import argparse
import copy
import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text

from routeflow.config import settings
from routeflow.consumer import Consumer
from routeflow.db import engine, session
from routeflow.models import DeadLetter, Outbox, now
from routeflow.storage import Warehouse

SCENARIOS = [
    "duplicate-events",
    "late-events",
    "out-of-order-events",
    "invalid-schema",
    "missing-required-fields",
    "consumer-failure",
    "consumer-failures",
    "outbox-retry",
    "reconciliation-mismatch",
]


def run(scenario: str) -> dict[str, Any]:
    if settings().environment != "local":
        raise ValueError("Chaos probes are restricted to local environments")
    consumer = Consumer()
    with session() as db:
        events = list(db.scalars(select(Outbox).order_by(Outbox.aggregate_version.desc())))
    if not events:
        raise ValueError("Generate a business workload before running chaos probes")
    body = copy.deepcopy(events[0].body)
    data = json.dumps(body).encode()
    if scenario in ("duplicate-events", "consumer-failure", "consumer-failures"):
        consumer.process(data, crash_after_write=scenario != "duplicate-events")
        assert consumer.process(data)
        count = Warehouse().query(
            "select count(*) as n from raw_events where event_id='" + body["event_id"] + "'"
        )[0]["n"]
        assert count == 1
    elif scenario in ("invalid-schema", "missing-required-fields"):
        if scenario == "invalid-schema":
            body["event_version"] = 999
        else:
            del body["payload"]
        assert consumer.process(json.dumps(body).encode())
        with session() as db:
            assert db.scalar(select(DeadLetter).where(DeadLetter.event_id == body["event_id"]))
    elif scenario in ("late-events", "out-of-order-events"):
        from routeflow.operations import dbt_build

        order_events = [row for row in events if row.body["event_type"] == "DELIVERED"]
        if not order_events:
            raise ValueError("Generate a delivered order first")
        identifier = order_events[0].aggregate_id
        selected = [row for row in events if row.aggregate_id == identifier]
        for delivery in sorted(selected, key=lambda event: -event.aggregate_version):
            assert consumer.process(json.dumps(delivery.body).encode())
        # Ingestion is deliberately delayed relative to historical event time.
        assert now() - __import__("datetime").datetime.fromisoformat(
            selected[-1].body["event_time"]
        ) > timedelta(minutes=1)
        dbt_build()
        rows = Warehouse().query(
            f"select status from analytics.fact_order where order_id='{identifier}'"
        )
        assert rows[0]["status"] == "DELIVERED"
    elif scenario == "outbox-retry":
        from routeflow.relay import relay_once

        class FailingPublisher:
            def publish(self, data: bytes) -> str:
                raise ConnectionError("Injected broker outage")

        with session() as db, db.begin():
            row = db.get(Outbox, events[0].event_id)
            assert row
            row.published_at = None
            row.next_attempt_at = now()
            row.lease_until = None
        relay_once(FailingPublisher(), 1)
        with session() as db:
            assert db.scalar(select(Outbox).where(Outbox.error.is_not(None)))
    elif scenario == "reconciliation-mismatch":
        from routeflow.operations import dbt_build, reconcile

        dbt_build()
        with engine(True).begin() as conn:
            conn.execute(text("update analytics.fact_order set amount_cents=amount_cents+1"))
        detected = False
        try:
            reconcile(grace_seconds=0)
        except ValueError:
            detected = True
        finally:
            dbt_build()
        assert detected
    else:
        raise ValueError(f"Unknown scenario: {scenario}")
    return {"scenario": scenario, "verified": True}


def main() -> None:
    from routeflow.logging import configure

    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.scenario)))


if __name__ == "__main__":
    main()
