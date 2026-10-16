"""Bounded commands for Cloud Run Jobs; never starts a distributed Spark cluster."""

import argparse
import subprocess
import time
from datetime import datetime, timedelta

from sqlalchemy import select

from routeflow.config import settings
from routeflow.db import session
from routeflow.generator import generate
from routeflow.logging import configure
from routeflow.messaging import Publisher
from routeflow.models import Outbox, now
from routeflow.operations import dbt_build, pipeline, reconcile
from routeflow.relay import relay_once
from routeflow.storage import Warehouse


def wait_ingestion(since: datetime | None = None, timeout: int = 240) -> int:
    since = since or now() - timedelta(days=1)
    with session() as db:
        expected = set(db.scalars(select(Outbox.event_id).where(Outbox.created_at >= since)))
    cfg = settings()
    table = f"`{cfg.google_cloud_project}.{cfg.bigquery_dataset}.raw_events`"
    deadline = time.monotonic() + timeout
    while True:
        actual = {
            row["event_id"]
            for row in Warehouse().query(
                "select event_id from raw_events", f"select distinct event_id from {table}"
            )
        }
        if expected <= actual:
            return len(expected)
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Ingestion incomplete: {len(expected - actual)} missing event IDs")
        time.sleep(2)


def produce() -> None:
    with pipeline("produce_and_ingest") as run:
        since = now()
        generate(10)
        publisher = Publisher()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            relay_once(publisher)
            with session() as db:
                pending = db.scalar(
                    select(Outbox.event_id)
                    .where(Outbox.created_at >= since, Outbox.published_at.is_(None))
                    .limit(1)
                )
            if not pending:
                break
            time.sleep(2)
        else:
            raise TimeoutError("Outbox publication incomplete")
        run.records_written = wait_ingestion(since)


def main() -> None:
    configure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["produce", "transform", "migrate"])
    command = parser.parse_args().command
    if command == "migrate":
        subprocess.run(["alembic", "upgrade", "head"], check=True)
    elif command == "produce":
        produce()
    else:
        dbt_build()
        reconcile(grace_seconds=0)


if __name__ == "__main__":
    main()
