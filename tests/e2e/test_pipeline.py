import json
import time
from datetime import timedelta

import pytest
from google.api_core.exceptions import DeadlineExceeded
from sqlalchemy import func, select, text

from routeflow.consumer import Consumer
from routeflow.db import engine, session
from routeflow.generator import generate
from routeflow.messaging import Publisher, clients
from routeflow.models import Driver, Order, Outbox, now, uid
from routeflow.operations import backfill, dbt_build, reconcile, replay
from routeflow.relay import relay_once
from routeflow.storage import raw_events

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


def test_real_pubsub_to_marts_and_recovery(isolated: None) -> None:
    generate(12)
    from routeflow.domain import update_driver

    with session() as db, db.begin():
        driver = db.scalar(select(Driver))
        assert driver
        update_driver(db, driver.id, driver.zone_id, now() - timedelta(days=2))
    publisher, subscriber = clients()
    project = "routeflow-local"
    topic = publisher.topic_path(project, "test-" + uid())
    subscription = subscriber.subscription_path(project, "test-" + uid())
    publisher.create_topic(request={"name": topic})
    subscriber.create_subscription(request={"name": subscription, "topic": topic})
    transport = Publisher()
    transport.topic_path = topic
    try:
        with session() as db:
            expected = db.scalar(select(func.count()).select_from(Outbox))
            expected_orders = db.scalar(select(func.count()).select_from(Order))
        assert relay_once(transport, 1000) == expected
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            with engine(True).connect() as conn:
                if conn.scalar(select(func.count()).select_from(raw_events)) == expected:
                    break
            try:
                response = subscriber.pull(
                    request={"subscription": subscription, "max_messages": 100}, timeout=5
                )
            except DeadlineExceeded:
                continue
            for received in reversed(response.received_messages):
                assert Consumer().process(received.message.data)
                subscriber.acknowledge(
                    request={"subscription": subscription, "ack_ids": [received.ack_id]}
                )
        with engine(True).connect() as conn:
            assert conn.scalar(select(func.count()).select_from(raw_events)) == expected
        dbt_build()
        assert all(status == "PASS" for status in reconcile(grace_seconds=0).values())
        with engine(True).connect() as conn:
            assert conn.scalar(text("select count(*) from analytics.fact_order")) == expected_orders
            assert (
                conn.scalar(text("select count(*) from analytics.dim_driver where not is_current"))
                == 1
            )
        # Deliver IN_TRANSIT after DELIVERED and repeat the archive without rolling state backwards.
        with session() as db:
            older = db.scalar(
                select(Outbox).where(Outbox.body["event_type"].as_string() == "IN_TRANSIT")
            )
            assert older
            assert Consumer().process(json.dumps(older.body).encode())
        replay()
        day = (now() - timedelta(days=1)).date()
        backfill(day, day)
        backfill(day, day)
        with engine(True).connect() as conn:
            assert conn.scalar(text("select count(*) from analytics.fact_order")) == expected_orders
            assert conn.scalar(select(func.count()).select_from(raw_events)) == expected
        assert all(status == "PASS" for status in reconcile(grace_seconds=0).values())
        with engine(True).begin() as conn:
            conn.execute(text("update analytics.fact_order set amount_cents=amount_cents+1"))
        with pytest.raises(ValueError, match="Reconciliation mismatch"):
            reconcile(grace_seconds=0)
        dbt_build()
        reconcile(grace_seconds=0)
    finally:
        subscriber.delete_subscription(request={"subscription": subscription})
        publisher.delete_topic(request={"topic": topic})
        subscriber.close()
